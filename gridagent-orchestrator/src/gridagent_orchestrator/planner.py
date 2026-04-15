"""pydantic-ai Agent over the gridagent tool surface.

Each tool exposed to the model is a thin typed wrapper around the corresponding
``gridagent_tools.TOOL_REGISTRY`` entry. The wrapper:

  1. invokes the underlying tool;
  2. appends an EpisodeStep to the episode log;
  3. asks the verifier what to do with the supervisory signal;
  4. on ADVANCE returns the value to the model;
  5. on RETRY / REPLAN raises ``ModelRetry`` with the signal as the error
     message — pydantic-ai feeds that back to the model so it re-plans;
  6. on ABORT raises ``RuntimeError`` to end the run.

Local-first: defaults to an OpenAI-compatible endpoint served by Ollama
(``http://localhost:11434/v1``) running an open-weight model. Default is
Gemma 4 E12B — Apache-2.0, native tool-calling, native system role,
released 2026-04-02 — which is the current sweet spot for desktop agent
work. Override ``GRIDAGENT_LLM_BASE_URL`` / ``GRIDAGENT_LLM_MODEL`` to
point at vLLM, llama.cpp's ``server`` binary, or a hosted provider.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from gridagent_tools import TOOL_REGISTRY
from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from .episode import Episode, EpisodeStep
from .verifier import Decision, Verifier


_DEFAULT_BASE_URL = "http://localhost:11434/v1"
_DEFAULT_MODEL = "gemma4:e12b"


_INSTRUCTIONS = """\
You drive an autonomous interconnection-study platform. Your only way to
affect the world is through the registered tools — never invent numbers,
never paraphrase tool output as your own analysis.

Each tool returns a value plus a *supervisory signal*. A rule-based verifier
inspects that signal before it reaches you. If the verifier rejects the
result, you will receive a ModelRetry telling you what failed; revise your
plan and try again. If the verifier accepts the result, the value is yours
to act on.

Standard playbook for an interconnection or contingency study:

  1. ``list_data_snapshots`` — confirm what data is available.
  2. ``query_grid`` — orient yourself in the network (buses, branches,
     generators, loads). Filter narrowly; the result is for *your* planning,
     not for the user.
  3. ``create_scenario`` — encode the user's intervention as a change-table.
     Supported keys: scale_load, scale_plant_capacity, add_plant, add_branch,
     add_dcline, out_of_service_branches.
  4. ``run_power_flow`` — sanity-check the scenario solves before any heavier
     study.
  5. ``run_n1_contingency`` — DC LODF screen; ranks branches by post-outage
     loading. Note: ``islanding_outages`` are reported separately because
     bridge contingencies are connectivity events, not thermal violations.
  6. If overloads exist, propose a mitigation as a *new* scenario (e.g.
     ``out_of_service_branches`` removed, capacity scaled, branch added) and
     re-screen. Do not loop more than two mitigation iterations without
     summarising.

When the study is complete, return a brief plain-text summary naming each
scenario you created, the worst overload, and any proposed mitigation.
"""


@dataclass
class OrchestratorDeps:
    """Shared state threaded through every tool call."""

    verifier: Verifier
    episode: Episode
    scenario_state: dict[str, Any] | None = None
    attempts: dict[str, int] = field(default_factory=dict)
    step_counter: int = 0


def _step_with_args(
    ctx: RunContext[OrchestratorDeps],
    tool_name: str,
    arguments: dict[str, Any],
    value: Any,
    signal: dict[str, Any],
) -> Any:
    """Same as ``_record_and_gate`` but stamps real arguments onto the log."""
    deps = ctx.deps
    attempt = deps.attempts.get(tool_name, 0) + 1
    deps.attempts[tool_name] = attempt
    deps.step_counter += 1

    decision = deps.verifier.decide(tool_name, signal, attempt=attempt)
    deps.episode.append_step(
        EpisodeStep(
            step=deps.step_counter,
            tool=tool_name,
            arguments=arguments,
            value=value,
            signal=signal,
            decision=decision,
            attempt=attempt,
        )
    )

    if decision is Decision.ADVANCE:
        deps.attempts[tool_name] = 0
        return value
    if decision is Decision.ABORT:
        raise RuntimeError(
            f"Verifier aborted after {tool_name}: signal={signal}. Run terminated."
        )
    raise ModelRetry(
        f"Verifier requested {decision.value} after {tool_name}. "
        f"Supervisory signal: {signal}. Revise your plan."
    )


def _resolve_model(model: str | None, base_url: str | None, api_key: str | None) -> OpenAIChatModel:
    provider = OpenAIProvider(
        base_url=base_url or os.environ.get("GRIDAGENT_LLM_BASE_URL", _DEFAULT_BASE_URL),
        # Local servers ignore the key but the SDK requires a non-empty value.
        api_key=api_key or os.environ.get("GRIDAGENT_LLM_API_KEY", "ollama"),
    )
    return OpenAIChatModel(
        model_name=model or os.environ.get("GRIDAGENT_LLM_MODEL", _DEFAULT_MODEL),
        provider=provider,
    )


def make_agent(
    *,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
) -> Agent[OrchestratorDeps, str]:
    """Build the gridagent Agent. All gridagent tools are registered here.

    The agent is stateless; per-run state (verifier, episode log, scenario
    cursor, retry counters) lives in ``OrchestratorDeps`` and is passed at
    ``run`` / ``run_sync`` time.
    """
    agent: Agent[OrchestratorDeps, str] = Agent(
        model=_resolve_model(model, base_url, api_key),
        deps_type=OrchestratorDeps,
        instructions=_INSTRUCTIONS,
        retries=3,
    )

    # ----- data tools -------------------------------------------------------

    @agent.tool
    def list_data_snapshots(ctx: RunContext[OrchestratorDeps]) -> Any:
        """List every data snapshot available locally with row counts per table."""
        result = TOOL_REGISTRY["list_data_snapshots"].fn()
        return _step_with_args(ctx, "list_data_snapshots", {}, result.value, result.signal)

    @agent.tool
    def query_grid(
        ctx: RunContext[OrchestratorDeps],
        table: str,
        snapshot_id: str | None = None,
        filters: dict[str, Any] | None = None,
        limit: int = 50,
    ) -> Any:
        """Read rows from a snapshot table.

        Args:
            table: One of ``buses``, ``branches``, ``generators``, ``loads``.
            snapshot_id: Bundle ID; omit for the newest snapshot.
            filters: Equality filters keyed by column name. Optional.
            limit: Cap on rows returned (default 50).
        """
        result = TOOL_REGISTRY["query_grid"].fn(
            table=table, snapshot_id=snapshot_id, filters=filters, limit=limit
        )
        args = {"table": table, "snapshot_id": snapshot_id, "filters": filters, "limit": limit}
        return _step_with_args(ctx, "query_grid", args, result.value, result.signal)

    # ----- scenario tools ---------------------------------------------------

    @agent.tool
    def create_scenario(
        ctx: RunContext[OrchestratorDeps],
        name: str,
        change_table: dict[str, Any],
        snapshot_id: str | None = None,
    ) -> Any:
        """Persist a named scenario as a change-table over a snapshot.

        The change-table is a declarative description of grid mutations.
        Supported keys: ``scale_load`` (float), ``scale_plant_capacity``
        (mapping generator_id → factor), ``add_plant``, ``add_branch``,
        ``add_dcline``, ``out_of_service_branches`` (list of branch_ids).
        Returns the scenario_id; remember it for follow-up study calls.
        """
        result = TOOL_REGISTRY["create_scenario"].fn(
            name=name, change_table=change_table, snapshot_id=snapshot_id
        )
        ctx.deps.scenario_state = result.value if isinstance(result.value, dict) else None
        args = {"name": name, "change_table": change_table, "snapshot_id": snapshot_id}
        return _step_with_args(ctx, "create_scenario", args, result.value, result.signal)

    @agent.tool
    def inspect_scenario(ctx: RunContext[OrchestratorDeps], scenario_id: str) -> Any:
        """Read back a scenario by ID."""
        result = TOOL_REGISTRY["inspect_scenario"].fn(scenario_id=scenario_id)
        args = {"scenario_id": scenario_id}
        return _step_with_args(ctx, "inspect_scenario", args, result.value, result.signal)

    # ----- study tools ------------------------------------------------------

    @agent.tool
    def run_power_flow(
        ctx: RunContext[OrchestratorDeps],
        scenario_id: str,
        executor: str = "pandapower",
    ) -> Any:
        """Solve AC power flow on a scenario. Returns convergence + slack injection."""
        result = TOOL_REGISTRY["run_power_flow"].fn(scenario_id=scenario_id, executor=executor)
        args = {"scenario_id": scenario_id, "executor": executor}
        return _step_with_args(ctx, "run_power_flow", args, result.value, result.signal)

    @agent.tool
    def run_n1_contingency(
        ctx: RunContext[OrchestratorDeps],
        scenario_id: str,
        executor: str = "pandapower",
        monitored: list[str] | None = None,
    ) -> Any:
        """DC LODF N-1 contingency screen; returns ranked overload list.

        ``islanding_outages`` lists bridge branches whose outage disconnects
        the network — surfaced separately rather than as thermal overloads.
        """
        result = TOOL_REGISTRY["run_n1_contingency"].fn(
            scenario_id=scenario_id, executor=executor, monitored=monitored
        )
        args = {"scenario_id": scenario_id, "executor": executor, "monitored": monitored}
        return _step_with_args(ctx, "run_n1_contingency", args, result.value, result.signal)

    @agent.tool
    def run_production_cost(
        ctx: RunContext[OrchestratorDeps],
        scenario_id: str,
        executor: str = "pandapower",
        horizon_hours: int = 24,
    ) -> Any:
        """Production-cost simulation over ``horizon_hours``.

        Default pandapower backend solves an hourly DC-OPF sweep — no UC,
        no ramping, no reserves. Swap to the Sienna backend once the
        container is wired up; the shape of the result is identical.
        """
        result = TOOL_REGISTRY["run_production_cost"].fn(
            scenario_id=scenario_id, executor=executor, horizon_hours=horizon_hours
        )
        args = {
            "scenario_id": scenario_id,
            "executor": executor,
            "horizon_hours": horizon_hours,
        }
        return _step_with_args(ctx, "run_production_cost", args, result.value, result.signal)

    return agent
