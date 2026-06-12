"""Episode driver: run a fixed workflow or hand the goal to a pydantic-ai Agent.

Two entry paths share one episode/event pipeline:

* ``run_workflow_episode`` — a learned workflow (workflow.py) executes its
  fixed tool sequence with zero model requests; the planner only enters if
  a node fails verification and the run escalates.
* ``run_episode`` — free-form goals go to the agent, which loops internally:
  picking tools, receiving results, and replanning when the verifier raises
  ModelRetry.

Either way we render the event stream (rich live panel by default, JSONL for
machine consumers, plain prints for CI) and persist the final summary.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable

from .episode import Episode
from .planner import OrchestratorDeps, make_agent
from .retrieval import retrieve
from .verifier import Verifier

EventCallback = Callable[[dict[str, Any]], None]


def _user_prompt(goal: str) -> str:
    """Goal + a few retrieved exemplar trajectories.

    The trajectory store seeds the model with hand-vetted reasoning paths
    (PowerChain-style). Empty store is fine; the model still has the
    instructions baked into the agent.
    """
    trajectories = retrieve(goal, k=3)
    if not trajectories:
        return goal
    body = "\n\n---\n\n".join(t.text for t in trajectories)
    return (
        f"# Goal\n{goal}\n\n"
        f"# Reference trajectories (vetted exemplars; adapt, do not copy)\n{body}"
    )


def _episode_root() -> Path:
    return Path(os.environ.get("GRIDAGENT_EPISODE_ROOT", "episodes"))


def _drive_agent(
    episode: Episode,
    prompt: str,
    *,
    model: str | None,
    base_url: str | None,
    verifier: Verifier,
) -> None:
    """Run the planner agent against an (possibly mid-flight) episode.

    Finishes the episode in every branch. ``step_counter`` starts at the
    episode's current length so agent steps continue a workflow's numbering
    instead of colliding with it.
    """
    from pydantic_ai.exceptions import UsageLimitExceeded
    from pydantic_ai.usage import UsageLimits

    deps = OrchestratorDeps(
        verifier=verifier, episode=episode, step_counter=len(episode.steps)
    )
    agent = make_agent(model=model, base_url=base_url)

    # Hard ceiling on model requests so a looping planner produces a bounded
    # run instead of an open-ended one. A clean playbook run takes well under
    # ten requests; small local models have been observed re-running the
    # whole playbook indefinitely instead of summarising.
    request_limit = int(os.environ.get("GRIDAGENT_MAX_REQUESTS", "25"))

    try:
        result = agent.run_sync(
            prompt,
            deps=deps,
            usage_limits=UsageLimits(request_limit=request_limit),
        )
        episode.finish(summary=str(result.output))
    except UsageLimitExceeded:
        # The study work is usually already done (see the episode log);
        # finish with what the last successful N-1 step found so the
        # overlay export still runs. Verifier-rejected steps don't count —
        # quoting a non-monotone screen's numbers as the answer is silent
        # data corruption.
        from .verifier import Decision

        n1_steps = [
            s
            for s in episode.steps
            if s.tool == "run_n1_contingency" and s.decision is Decision.ADVANCE
        ]
        if n1_steps:
            sig = n1_steps[-1].signal
            episode.finish(
                summary=(
                    f"Stopped at the {request_limit}-request limit before the planner "
                    f"summarised. Last N-1 screen: {sig.get('n_overloads')} overloads "
                    f"across {sig.get('n_screened')} screened outages; worst loading "
                    f"{sig.get('worst_loading_pct')}%."
                )
            )
        else:
            episode.finish(
                summary=f"Stopped at the {request_limit}-request limit before any N-1 screen completed."
            )
    except RuntimeError as exc:
        # Verifier ABORT or unrecoverable model retry exhaustion.
        episode.finish(summary=f"Aborted: {exc}")


def _export_overlays(
    episode: Episode,
    atlas_overlay_dir: Path | None,
    emit: Callable[[str], None],
    on_event: EventCallback | None,
) -> None:
    if atlas_overlay_dir is None:
        return
    from .overlay_export import write_episode_overlays

    try:
        n, ep_id = write_episode_overlays(episode.log_path, atlas_overlay_dir)
        if n == 0:
            # Nothing was written (e.g. a clean screen with zero overloads).
            # Emitting an overlay event here would hand the client a URL
            # that 404s.
            emit("Atlas overlay skipped: no overlay features (0 overloads).")
            return
        ep_dir = atlas_overlay_dir / ep_id
        emit(f"Atlas overlay: {n} features → {ep_dir}/  (open atlas with ?episode={ep_id})")
        if on_event is not None:
            # Machine consumers learn where the overlay landed from the
            # stream itself — they cannot parse human prints.
            on_event(
                {
                    "event": "overlay",
                    "episode_id": ep_id,
                    "feature_count": n,
                    "overlay_dir": str(ep_dir),
                }
            )
    except (ValueError, FileNotFoundError) as exc:
        emit(f"Atlas overlay skipped: {exc}")


def run_episode(
    goal: str,
    *,
    model: str | None = None,
    base_url: str | None = None,
    verifier: Verifier | None = None,
    atlas_overlay_dir: Path | None = None,
    on_event: EventCallback | None = None,
    emit: Callable[[str], None] = print,
) -> Episode:
    """Drive a single agent episode end-to-end and return the persisted log.

    ``on_event`` observes every episode record as it is written (see
    ``Episode.on_event``); ``emit`` carries the human-facing side notes
    (overlay paths). Pass a no-op emit when stdout must stay machine-clean.
    """
    episode = Episode.new(goal=goal, root=_episode_root(), on_event=on_event)
    _drive_agent(
        episode,
        _user_prompt(goal),
        model=model,
        base_url=base_url,
        verifier=verifier or Verifier.default(),
    )
    _export_overlays(episode, atlas_overlay_dir, emit, on_event)
    return episode


def _escalation_prompt(goal: str, spec: Any, outcome: Any) -> str:
    """Context the agent gets when a workflow hands over a failed run.

    Renders each completed node's *ports* (not raw signals) — ports carry
    the identifiers the agent must reuse (snapshot id, scenario id), which
    signals alone don't always include.
    """
    from .workflow import resolved_ports

    workflow_name = spec.name
    done: list[str] = []
    for node_id, res in outcome.context.items():
        ports = resolved_ports(spec, node_id, res)
        rendered = ", ".join(
            f"{k}={json.dumps(v, default=str)[:120]}" for k, v in ports.items()
        )
        done.append(f"- {node_id}: {rendered or 'ok'}")
    completed = "\n".join(done) if done else "- none"
    return (
        f"# Goal\n{goal}\n\n"
        f"# Workflow escalation\n"
        f"The deterministic workflow '{workflow_name}' failed at node "
        f"'{outcome.failed_node}': {outcome.reason}.\n"
        f"Steps already completed — do NOT repeat them; reuse their outputs:\n"
        f"{completed}\n"
        f"Continue the study from this state and produce the final summary."
    )


def run_workflow_episode(
    name: str,
    inputs: dict[str, Any] | None = None,
    *,
    model: str | None = None,
    base_url: str | None = None,
    verifier: Verifier | None = None,
    atlas_overlay_dir: Path | None = None,
    on_event: EventCallback | None = None,
    emit: Callable[[str], None] = print,
) -> Episode:
    """Run a fixed workflow; fall back to the agent only on escalation.

    The happy path makes zero model requests: the workflow runner executes
    the spec, the verifier gates each node, and the summary renders from
    the spec's template. ``model``/``base_url`` are only touched if a node
    fails verification and the run escalates to the planner.
    """
    import time as _time

    from .workflow import (
        load_workflow,
        render_goal,
        render_summary,
        resolve_inputs,
        run_workflow,
    )

    spec = load_workflow(name)
    resolved = resolve_inputs(spec, inputs)
    goal = render_goal(spec, resolved)
    verifier = verifier or Verifier.default()

    episode = Episode.new(goal=goal, root=_episode_root(), on_event=on_event)
    outcome = run_workflow(spec, resolved, verifier=verifier, episode=episode)

    if outcome.status == "completed":
        episode.finish(summary=render_summary(spec, resolved, outcome.context))
    elif outcome.status == "aborted":
        episode.finish(
            summary=f"Aborted at workflow node '{outcome.failed_node}': {outcome.reason}"
        )
    else:
        episode.append_record(
            {
                "event": "escalate",
                "node": outcome.failed_node,
                "reason": outcome.reason,
                "ts": _time.time(),
            }
        )
        _drive_agent(
            episode,
            _escalation_prompt(goal, spec, outcome),
            model=model,
            base_url=base_url,
            verifier=verifier,
        )

    _export_overlays(episode, atlas_overlay_dir, emit, on_event)
    return episode


def main() -> None:
    parser = argparse.ArgumentParser(prog="gridagent-orchestrator")
    goal_group = parser.add_mutually_exclusive_group(required=True)
    goal_group.add_argument("--goal", help="Free-form study goal for the agent.")
    goal_group.add_argument(
        "--workflow",
        metavar="NAME",
        help="Run a fixed workflow with no planner (see workflows/; e.g. n1_contingency).",
    )
    goal_group.add_argument(
        "--from-substation",
        metavar="NAME_OR_ID",
        help=(
            "Shorthand: run the n1_contingency workflow (a grid-wide screen "
            "labeled with this substation; locational scoping is Phase 2)."
        ),
    )
    parser.add_argument(
        "--inputs",
        default=None,
        help="JSON object of workflow inputs (only with --workflow / --from-substation).",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model name (default: $GRIDAGENT_LLM_MODEL or 'gemma4:e12b').",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="OpenAI-compatible base URL (default: $GRIDAGENT_LLM_BASE_URL or http://localhost:11434/v1).",
    )
    parser.add_argument(
        "--atlas-overlay-dir",
        type=Path,
        default=None,
        help="Write per-episode overlay GeoJSON under this dir (atlas ?episode=…).",
    )
    render_group = parser.add_mutually_exclusive_group()
    render_group.add_argument(
        "--plain",
        action="store_true",
        help="Plain prints, no live panel (CI / dumb terminals).",
    )
    render_group.add_argument(
        "--stream-events",
        action="store_true",
        help=(
            "Emit each episode event as one JSON line on stdout and nothing "
            "else — the mode machine consumers (the web /api/study bridge) "
            "spawn this CLI in."
        ),
    )
    args = parser.parse_args()

    if args.inputs and not (args.workflow or args.from_substation):
        parser.error("--inputs requires --workflow or --from-substation")

    workflow_name: str | None = None
    workflow_inputs: dict[str, Any] = {}
    if args.workflow or args.from_substation:
        workflow_name = args.workflow or "n1_contingency"
        if args.inputs:
            try:
                workflow_inputs = json.loads(args.inputs)
            except json.JSONDecodeError as exc:
                parser.error(f"--inputs is not valid JSON: {exc}")
            if not isinstance(workflow_inputs, dict):
                parser.error("--inputs must be a JSON object, e.g. '{\"scenario_name\": \"...\"}'")
        if args.from_substation:
            workflow_inputs.setdefault(
                "scenario_name", f"N-1 near substation {args.from_substation}"
            )

    def _run(
        *,
        on_event: EventCallback | None,
        emit: Callable[[str], None] = print,
    ) -> Episode:
        if workflow_name is not None:
            return run_workflow_episode(
                workflow_name,
                workflow_inputs,
                model=args.model,
                base_url=args.base_url,
                atlas_overlay_dir=args.atlas_overlay_dir,
                on_event=on_event,
                emit=emit,
            )
        return run_episode(
            args.goal,
            model=args.model,
            base_url=args.base_url,
            atlas_overlay_dir=args.atlas_overlay_dir,
            on_event=on_event,
            emit=emit,
        )

    if args.stream_events:
        from .render import JsonlRenderer

        _run(on_event=JsonlRenderer(), emit=lambda msg: print(msg, file=sys.stderr))
        return

    if args.plain or not sys.stdout.isatty():

        def plain_event(record: dict[str, Any]) -> None:
            event = record.get("event")
            if event == "workflow":
                nodes = " → ".join(n["tool"] for n in record.get("nodes", []))
                print(f"workflow {record.get('workflow')}: {nodes}")
            elif event == "step":
                print(
                    f"  step {record.get('step')}: {record.get('tool')} "
                    f"→ {record.get('decision')} "
                    f"signal={json.dumps(record.get('signal'), default=str)}"
                )
            elif event == "escalate":
                print(
                    f"escalating to agent at node {record.get('node')}: {record.get('reason')}"
                )
            elif event == "finish":
                print(f"Summary: {record.get('summary')}")

        episode = _run(on_event=plain_event)
        print(f"Episode {episode.episode_id} written to {episode.log_path}")
        return

    from .render import RichRenderer

    with RichRenderer() as renderer:
        episode = _run(on_event=renderer, emit=renderer.console.print)
    renderer.console.print(
        f"[dim]Episode {episode.episode_id} written to {episode.log_path}[/dim]"
    )


if __name__ == "__main__":
    main()
