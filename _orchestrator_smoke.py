"""Offline smoke test for the pydantic-ai orchestrator.

Uses pydantic-ai's FunctionModel to script a deterministic plan — no LLM,
no network. Drives the same tool surface the real agent will, so we can
verify wiring + verifier hook + episode log on every commit.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.environ.setdefault("GRIDAGENT_DATA_ROOT", str(ROOT / "data_root"))
os.environ.setdefault("GRIDAGENT_SCENARIO_ROOT", str(ROOT / "data_root" / "scenarios"))
os.environ.setdefault("GRIDAGENT_EPISODE_ROOT", str(ROOT / "data_root" / "episodes"))

from pydantic_ai.messages import (  # noqa: E402
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel  # noqa: E402

from gridagent_orchestrator import Episode, OrchestratorDeps, Verifier  # noqa: E402
from gridagent_orchestrator.planner import make_agent  # noqa: E402


# --- scripted "model" ---------------------------------------------------------
# Mirrors the canonical playbook: list -> query -> create -> n1.
_SCRIPT: list[dict] = [
    {"tool": "list_data_snapshots", "args": {}},
    {"tool": "query_grid", "args": {"table": "branches", "limit": 5}},
    {
        "tool": "create_scenario",
        "args": {
            "name": "scripted_baseline",
            "change_table": {},
        },
    },
    # scenario_id is filled in by reading the previous tool return below.
    {"tool": "run_n1_contingency", "args": {"executor": "pandapower"}},
]


def _scripted_planner(messages: list[ModelRequest | ModelResponse], info: AgentInfo) -> ModelResponse:
    """Walk down ``_SCRIPT``, plucking arguments dynamically when needed."""
    # Count tool returns so far: that's our index into the script.
    n_returned = 0
    last_create_scenario_value: dict | None = None
    for m in messages:
        for part in getattr(m, "parts", []):
            if part.part_kind == "tool-return":
                n_returned += 1
                # Capture create_scenario's scenario_id for the n-1 call.
                if part.tool_name == "create_scenario":
                    content = part.content
                    if isinstance(content, str):
                        try:
                            content = json.loads(content)
                        except json.JSONDecodeError:
                            content = None
                    if isinstance(content, dict):
                        last_create_scenario_value = content

    if n_returned >= len(_SCRIPT):
        return ModelResponse(parts=[TextPart(content="Scripted plan complete.")])

    step = _SCRIPT[n_returned]
    args = dict(step["args"])
    if step["tool"] == "run_n1_contingency" and "scenario_id" not in args:
        assert last_create_scenario_value is not None, "create_scenario must run first"
        args["scenario_id"] = last_create_scenario_value["scenario_id"]

    return ModelResponse(
        parts=[ToolCallPart(tool_name=step["tool"], args=args, tool_call_id=f"call-{n_returned}")]
    )


def main() -> int:
    agent = make_agent()
    # Swap in the scripted model for this run.
    model = FunctionModel(_scripted_planner)
    episode = Episode.new(goal="scripted plan", root=Path(os.environ["GRIDAGENT_EPISODE_ROOT"]))
    deps = OrchestratorDeps(verifier=Verifier.default(), episode=episode)

    with agent.override(model=model):
        result = agent.run_sync("Run the scripted plan.", deps=deps)

    episode.finish(summary=str(result.output))

    expected = ["list_data_snapshots", "query_grid", "create_scenario", "run_n1_contingency"]
    actual = [s.tool for s in episode.steps]
    assert actual == expected, f"Unexpected tool sequence: {actual}"

    n1_step = episode.steps[-1]
    assert n1_step.signal["monotone"], "N-1 ranking not monotone"
    assert n1_step.decision.value == "advance", f"Verifier rejected N-1: {n1_step.decision}"

    print(f"Episode {episode.episode_id} OK; {len(episode.steps)} tool calls executed.")
    print(f"  worst loading: {n1_step.signal.get('worst_loading_pct'):.1f}%")
    print(f"  log: {episode.log_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
