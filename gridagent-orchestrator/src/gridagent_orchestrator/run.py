"""Episode driver: hand the goal to a pydantic-ai Agent and stream the run.

The agent loops internally — picking tools, receiving results, and replanning
when the verifier raises ModelRetry. We just kick it off and persist the
final summary.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

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


def run_episode(
    goal: str,
    *,
    model: str | None = None,
    base_url: str | None = None,
    verifier: Verifier | None = None,
) -> Episode:
    """Drive a single episode end-to-end and return the persisted log."""
    episode = Episode.new(goal=goal, root=_episode_root())
    deps = OrchestratorDeps(verifier=verifier or Verifier.default(), episode=episode)
    agent = make_agent(model=model, base_url=base_url)

    try:
        result = agent.run_sync(_user_prompt(goal), deps=deps)
        episode.finish(summary=str(result.output))
    except RuntimeError as exc:
        # Verifier ABORT or unrecoverable model retry exhaustion.
        episode.finish(summary=f"Aborted: {exc}")
    return episode


def main() -> None:
    parser = argparse.ArgumentParser(prog="gridagent-orchestrator")
    parser.add_argument("--goal", required=True)
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
    args = parser.parse_args()

    episode = run_episode(args.goal, model=args.model, base_url=args.base_url)
    print(f"Episode {episode.episode_id} written to {episode.log_path}")


if __name__ == "__main__":
    main()
