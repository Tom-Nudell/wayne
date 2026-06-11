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
You drive an autonomous power-grid analysis platform. Your only way to
affect the world is through the registered tools — never invent numbers,
never paraphrase tool output as your own analysis.

CRITICAL RULES:
- Execute each playbook step exactly once, in order. Never repeat a step.
- After step 1, use the first snapshot_id you received for all subsequent calls.
- After step 2, proceed immediately to step 3 regardless of what the data shows.
- If the data does not match the goal (e.g. goal says ERCOT but data is a test
  system), run the study anyway and note the limitation in your summary.
- Never ask for clarification. Never exit early. Complete all 5 steps.

Each tool returns a value plus a *supervisory signal*. A rule-based verifier
inspects that signal before it reaches you. If the verifier rejects the
result you will receive a ModelRetry — revise and retry that single step only.

Playbook — four steps, execute each exactly once:

  STEP 1: ``list_data_snapshots``
    → Record the first snapshot_id in the result. Use it everywhere below.

  STEP 2: ``query_grid`` with table="branches" and the snapshot_id from STEP 1.
    → One call only. Note the schema. Then move to STEP 3 immediately.

  STEP 3: ``create_scenario`` with change_table={} and the snapshot_id from STEP 1.
    → Record the scenario_id returned. Use it in STEP 4.

  STEP 4: ``run_n1_contingency`` with the scenario_id from STEP 3, executor="pandapower".
    → Returns ranked overload list. This is the answer. Always use pandapower.

After STEP 4, return a summary with: snapshot used, worst overload
(monitored branch, outage branch, loading %), total overload count,
and any data limitations.
"""


@dataclass
class OrchestratorDeps:
    """Shared state threaded through every tool call."""

    verifier: Verifier
    episode: Episode
    scenario_state: dict[str, Any] | None = None
    attempts: dict[str, int] = field(default_factory=dict)
    step_counter: int = 0
    call_totals: dict[str, int] = field(default_factory=dict)  # total calls per tool name


def _call_tool(registry_name: str, **kwargs: Any) -> Any:
    """Invoke a tool from the registry, converting execution errors to ModelRetry.

    pydantic-ai does not auto-convert unhandled tool exceptions to ModelRetry
    in this version — they re-raise and crash the entire run. Wrapping here
    lets the model see the error and self-correct (e.g. bad snapshot_id).
    """
    try:
        return TOOL_REGISTRY[registry_name].fn(**kwargs)
    except (FileNotFoundError, ValueError, KeyError) as exc:
        raise ModelRetry(
            f"Tool '{registry_name}' failed: {exc}. "
            "Revise your arguments. If the snapshot_id is wrong, call list_data_snapshots first."
        )


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
    deps.call_totals[tool_name] = deps.call_totals.get(tool_name, 0) + 1

    # Repetition guard: orientation tools (list_data_snapshots, query_grid) are
    # one-shot steps. If the model calls them more than twice it is stuck in a
    # loop — force REPLAN so it moves on.
    _ONE_SHOT_TOOLS = {"list_data_snapshots", "query_grid"}
    if tool_name in _ONE_SHOT_TOOLS and deps.call_totals[tool_name] > 2:
        signal = {**signal, "_replan_reason": f"{tool_name} called {deps.call_totals[tool_name]} times — proceed to create_scenario"}
        decision = Decision.REPLAN
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
        raise ModelRetry(
            f"{tool_name} has been called {deps.call_totals[tool_name]} times. "
            "You have enough data. Stop querying and proceed to STEP 3: create_scenario."
        )

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
        result = _call_tool("list_data_snapshots")
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
        result = _call_tool("query_grid", table=table, snapshot_id=snapshot_id, filters=filters, limit=limit)
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
        result = _call_tool("create_scenario", name=name, change_table=change_table, snapshot_id=snapshot_id)
        ctx.deps.scenario_state = result.value if isinstance(result.value, dict) else None
        args = {"name": name, "change_table": change_table, "snapshot_id": snapshot_id}
        return _step_with_args(ctx, "create_scenario", args, result.value, result.signal)

    @agent.tool
    def inspect_scenario(ctx: RunContext[OrchestratorDeps], scenario_id: str) -> Any:
        """Read back a scenario by ID."""
        result = _call_tool("inspect_scenario", scenario_id=scenario_id)
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
        result = _call_tool("run_power_flow", scenario_id=scenario_id, executor=executor)
        args = {"scenario_id": scenario_id, "executor": executor}
        return _step_with_args(ctx, "run_power_flow", args, result.value, result.signal)

    @agent.tool
    def run_n1_contingency(
        ctx: RunContext[OrchestratorDeps],
        scenario_id: str,
        monitored: list[str] | None = None,
    ) -> Any:
        """DC LODF N-1 contingency screen; returns ranked overload list.

        Always uses the pandapower backend. Do not pass an executor parameter.
        ``islanding_outages`` lists bridge branches whose outage disconnects
        the network — surfaced separately rather than as thermal overloads.
        """
        result = _call_tool("run_n1_contingency", scenario_id=scenario_id, executor="pandapower", monitored=monitored)
        args = {"scenario_id": scenario_id, "executor": "pandapower", "monitored": monitored}
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
        result = _call_tool("run_production_cost", scenario_id=scenario_id, executor=executor, horizon_hours=horizon_hours
        )
        args = {
            "scenario_id": scenario_id,
            "executor": executor,
            "horizon_hours": horizon_hours,
        }
        return _step_with_args(ctx, "run_production_cost", args, result.value, result.signal)

    return agent
