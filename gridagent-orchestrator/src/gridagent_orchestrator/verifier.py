"""Rule-based verifier over (tool_name, signal) -> Decision.

Kept as explicit Python (not LLM-judged) so behavior is reproducible across
runs and trivially auditable. New tools register their own rule here.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable


class Decision(str, Enum):
    ADVANCE = "advance"
    RETRY = "retry"
    REPLAN = "replan"
    ABORT = "abort"


SignalRule = Callable[[dict[str, Any], int], Decision]
"""(signal, attempt) -> Decision. ``attempt`` is 1-indexed retry count."""


def _power_flow_rule(signal: dict[str, Any], attempt: int) -> Decision:
    if signal.get("converged"):
        return Decision.ADVANCE
    if attempt < 2:
        return Decision.RETRY  # planner is expected to flip to flat start
    return Decision.REPLAN


def _n1_rule(signal: dict[str, Any], attempt: int) -> Decision:
    if not signal.get("monotone", True):
        # Non-monotone overload ranking implies a numerical bug, not a fix-able state.
        return Decision.ABORT
    return Decision.ADVANCE  # n_overloads > 0 is fine; planner proposes mitigation


def _pcm_rule(signal: dict[str, Any], attempt: int) -> Decision:
    if signal.get("solver_status") != "OPTIMAL":
        return Decision.REPLAN
    if signal.get("slack_mw", 0.0) > _PCM_SLACK_THRESHOLD_MW:
        return Decision.REPLAN
    return Decision.ADVANCE


_PCM_SLACK_THRESHOLD_MW = 50.0


@dataclass
class Verifier:
    rules: dict[str, SignalRule]

    def decide(self, tool_name: str, signal: dict[str, Any], attempt: int = 1) -> Decision:
        rule = self.rules.get(tool_name)
        if rule is None:
            # No rule registered: trust the tool, keep going.
            return Decision.ADVANCE
        return rule(signal, attempt)

    @classmethod
    def default(cls) -> "Verifier":
        return cls(
            rules={
                "run_power_flow": _power_flow_rule,
                "run_n1_contingency": _n1_rule,
                "run_production_cost": _pcm_rule,
            }
        )
