"""Per-step prompt assembly.

Concatenates: system rules + retrieved trajectories + scenario state summary +
last tool result + last supervisory signal. Kept as plain strings so it's
trivially diffable in episode logs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .retrieval import Trajectory

_SYSTEM_RULES = """\
You drive an autonomous interconnection-study platform. You may only act
through the tool surface; do not invent data. Each tool returns a
supervisory signal that the verifier inspects — your job is to make the
next decision conditional on that signal, not to second-guess it.
"""


@dataclass
class StepContext:
    system: str
    trajectories: str
    scenario_state: str
    last_result: str
    last_signal: str

    def render(self) -> str:
        return "\n\n".join(
            [
                f"# System\n{self.system}",
                f"# Reference trajectories\n{self.trajectories}",
                f"# Scenario state\n{self.scenario_state}",
                f"# Last tool result\n{self.last_result}",
                f"# Last supervisory signal\n{self.last_signal}",
            ]
        )


def assemble(
    *,
    trajectories: list[Trajectory],
    scenario_state: dict[str, Any] | None,
    last_value: Any | None,
    last_signal: dict[str, Any] | None,
) -> StepContext:
    return StepContext(
        system=_SYSTEM_RULES,
        trajectories="\n\n---\n\n".join(t.text for t in trajectories) or "(none)",
        scenario_state=str(scenario_state or "(no scenario yet)"),
        last_result=str(last_value or "(no prior result)"),
        last_signal=str(last_signal or "(no prior signal)"),
    )
