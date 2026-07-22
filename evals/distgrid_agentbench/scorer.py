"""Workflow scoring for DistGrid-AgentBench planning evals.

Our own strict re-implementation of the benchmark's headline metrics — we do
NOT vendor or import the upstream evaluator (the repo ships no license):

* **success** (→ P@1): every ground-truth step appears in the agent workflow,
  in order, with matching tool name and arguments (subsequence match).
* **precision**: 1.0 only if the agent made no tool calls beyond the ground
  truth, else 0.0 — the upstream definition.

Upstream applies extra per-family leniency rules (implicit network loads,
query-dependent optional args). We deliberately skip those: our numbers are
a strict lower bound and are indicative, not directly comparable.
"""

from __future__ import annotations

from typing import Any


def _norm(value: Any) -> Any:
    """Normalize argument values: numbers compare numerically ("14" == 14),
    strings case/space-insensitively, containers recursively."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        s = value.strip().lower()
        try:
            return float(s)
        except ValueError:
            return s
    if isinstance(value, dict):
        return {str(k).lower(): _norm(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_norm(v) for v in value]
    return value


def args_match(agent_args: dict | None, ref_args: dict | None) -> bool:
    """Every ground-truth argument must be present and equal. Extra agent
    arguments don't fail the step (upstream tolerates harmless extras)."""
    agent_args = agent_args or {}
    for key, ref_value in (ref_args or {}).items():
        if key not in agent_args:
            return False
        if _norm(agent_args[key]) != _norm(ref_value):
            return False
    return True


def analyze(
    agent_wf: list[dict] | None, ref_wf: list[dict] | None
) -> tuple[bool, str, float]:
    """Score one workflow. Returns (success, failure_reason, precision)."""
    agent = list(agent_wf or [])
    ref = list(ref_wf or [])
    i = 0
    for ref_step in ref:
        found = False
        while i < len(agent):
            step = agent[i]
            i += 1
            if str(step.get("name")) == str(ref_step.get("name")) and args_match(
                step.get("arguments"), ref_step.get("arguments")
            ):
                found = True
                break
        if not found:
            return (
                False,
                f"missing step {ref_step.get('name')}({ref_step.get('arguments')})",
                0.0,
            )
    return True, "", 1.0 if len(agent) == len(ref) else 0.0


def hallucinated_tools(agent_wf: list[dict] | None, known: set[str]) -> list[str]:
    """Tool names the agent invented — not in the benchmark manifest."""
    return sorted(
        {str(s.get("name")) for s in (agent_wf or []) if str(s.get("name")) not in known}
    )
