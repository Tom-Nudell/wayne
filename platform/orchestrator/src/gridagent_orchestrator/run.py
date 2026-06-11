"""Episode driver: hand the goal to a pydantic-ai Agent and stream the run.

The agent loops internally — picking tools, receiving results, and replanning
when the verifier raises ModelRetry. We kick it off, render the event stream
(rich live panel by default, JSONL for machine consumers, plain prints for
CI), and persist the final summary.
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


def goal_from_substation(substation: str) -> str:
    """Template the canonical map/CLI intent: N-1 screen near a substation.

    The same goal text serves ``--from-substation`` on the CLI and the
    map's "Run N-1 study from here" action — one code path, two surfaces.
    """
    return (
        f"Load the newest data snapshot, create a baseline scenario, and run "
        f"an N-1 contingency screen focused on the network around substation "
        f"{substation!r}. Summarise the worst overload and name the branches "
        f"involved."
    )


def run_episode(
    goal: str,
    *,
    model: str | None = None,
    base_url: str | None = None,
    verifier: Verifier | None = None,
    atlas_overlay_dir: Path | None = None,
    on_event: Callable[[dict[str, Any]], None] | None = None,
    emit: Callable[[str], None] = print,
) -> Episode:
    """Drive a single episode end-to-end and return the persisted log.

    ``on_event`` observes every episode record as it is written (see
    ``Episode.on_event``); ``emit`` carries the human-facing side notes
    (overlay paths). Pass a no-op emit when stdout must stay machine-clean.
    """
    from pydantic_ai.exceptions import UsageLimitExceeded
    from pydantic_ai.usage import UsageLimits

    episode = Episode.new(goal=goal, root=_episode_root(), on_event=on_event)
    deps = OrchestratorDeps(verifier=verifier or Verifier.default(), episode=episode)
    agent = make_agent(model=model, base_url=base_url)

    # Hard ceiling on model requests so a looping planner produces a bounded
    # run instead of an open-ended one. A clean playbook run takes well under
    # ten requests; small local models have been observed re-running the
    # whole playbook indefinitely instead of summarising.
    request_limit = int(os.environ.get("GRIDAGENT_MAX_REQUESTS", "25"))

    try:
        result = agent.run_sync(
            _user_prompt(goal),
            deps=deps,
            usage_limits=UsageLimits(request_limit=request_limit),
        )
        episode.finish(summary=str(result.output))
    except UsageLimitExceeded:
        # The study work is usually already done (see the episode log);
        # finish with what the last successful N-1 step found so the
        # overlay export below still runs.
        n1_steps = [s for s in episode.steps if s.tool == "run_n1_contingency"]
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

    if atlas_overlay_dir is not None:
        from .overlay_export import write_episode_overlays

        try:
            n, ep_id = write_episode_overlays(episode.log_path, atlas_overlay_dir)
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

    return episode


def main() -> None:
    parser = argparse.ArgumentParser(prog="gridagent-orchestrator")
    goal_group = parser.add_mutually_exclusive_group(required=True)
    goal_group.add_argument("--goal", help="Free-form study goal for the agent.")
    goal_group.add_argument(
        "--from-substation",
        metavar="NAME_OR_ID",
        help="Shorthand: run the canonical N-1 screen around this substation.",
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

    goal = args.goal if args.goal else goal_from_substation(args.from_substation)

    if args.stream_events:
        from .render import JsonlRenderer

        renderer = JsonlRenderer()
        episode = run_episode(
            goal,
            model=args.model,
            base_url=args.base_url,
            atlas_overlay_dir=args.atlas_overlay_dir,
            on_event=renderer,
            emit=lambda msg: print(msg, file=sys.stderr),
        )
        return

    if args.plain or not sys.stdout.isatty():

        def plain_event(record: dict[str, Any]) -> None:
            event = record.get("event")
            if event == "step":
                print(
                    f"  step {record.get('step')}: {record.get('tool')} "
                    f"→ {record.get('decision')} "
                    f"signal={json.dumps(record.get('signal'), default=str)}"
                )
            elif event == "finish":
                print(f"Summary: {record.get('summary')}")

        episode = run_episode(
            goal,
            model=args.model,
            base_url=args.base_url,
            atlas_overlay_dir=args.atlas_overlay_dir,
            on_event=plain_event,
        )
        print(f"Episode {episode.episode_id} written to {episode.log_path}")
        return

    from .render import RichRenderer

    with RichRenderer() as renderer:
        episode = run_episode(
            goal,
            model=args.model,
            base_url=args.base_url,
            atlas_overlay_dir=args.atlas_overlay_dir,
            on_event=renderer,
            emit=renderer.console.print,
        )
    renderer.console.print(
        f"[dim]Episode {episode.episode_id} written to {episode.log_path}[/dim]"
    )


if __name__ == "__main__":
    main()
