"""Episode driver: plan -> tool call -> verify -> repeat.

CLI entrypoint. Stays small; everything interesting lives in planner / verifier.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from gridagent_tools import TOOL_REGISTRY, ToolResult

from .context import assemble
from .episode import Episode, EpisodeStep
from .planner import AnthropicLLM, LLM, ToolCall, tools_for_llm
from .retrieval import retrieve
from .verifier import Decision, Verifier

MAX_STEPS = 25


def _episode_root() -> Path:
    return Path(os.environ.get("GRIDAGENT_EPISODE_ROOT", "episodes"))


def run_episode(goal: str, llm: LLM, verifier: Verifier | None = None) -> Episode:
    verifier = verifier or Verifier.default()
    episode = Episode.new(goal=goal, root=_episode_root())

    last_value = None
    last_signal: dict | None = None
    scenario_state: dict | None = None
    attempts: dict[str, int] = {}

    for step_num in range(1, MAX_STEPS + 1):
        ctx = assemble(
            trajectories=retrieve(goal),
            scenario_state=scenario_state,
            last_value=last_value,
            last_signal=last_signal,
        )
        prompt = f"Goal: {goal}\n\n{ctx.render()}"

        call: ToolCall | None = llm.propose(prompt, tools_for_llm())
        if call is None:
            episode.finish(summary="Planner returned no tool call; episode ended.")
            return episode

        spec = TOOL_REGISTRY.get(call.name)
        if spec is None:
            episode.finish(summary=f"Planner requested unknown tool {call.name!r}; abort.")
            return episode

        attempt = attempts.get(call.name, 0) + 1
        attempts[call.name] = attempt
        result: ToolResult = spec.fn(**call.arguments)
        decision = verifier.decide(call.name, result.signal, attempt=attempt)

        episode.append_step(
            EpisodeStep(
                step=step_num,
                tool=call.name,
                arguments=call.arguments,
                value=result.value,
                signal=result.signal,
                decision=decision,
                attempt=attempt,
            )
        )

        last_value = result.value
        last_signal = result.signal
        if call.name == "create_scenario":
            scenario_state = result.value if isinstance(result.value, dict) else None

        if decision is Decision.ABORT:
            episode.finish(summary=f"Verifier aborted after {call.name}.")
            return episode
        if decision is Decision.ADVANCE:
            attempts[call.name] = 0  # reset retry counter on success
            continue
        # RETRY / REPLAN: loop again; planner sees the failed signal in context.

    episode.finish(summary=f"Reached MAX_STEPS={MAX_STEPS} without completion.")
    return episode


def main() -> None:
    parser = argparse.ArgumentParser(prog="gridagent-orchestrator")
    parser.add_argument("--goal", required=True)
    parser.add_argument("--model", default="claude-sonnet-4-6")
    args = parser.parse_args()

    llm = AnthropicLLM(model=args.model)
    episode = run_episode(args.goal, llm=llm)
    print(f"Episode {episode.episode_id} written to {episode.log_path}")


if __name__ == "__main__":
    main()
