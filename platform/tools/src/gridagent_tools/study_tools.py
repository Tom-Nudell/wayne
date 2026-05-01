"""Study tools: dispatch to a registered backend.

The agent never picks an engine — it picks an ``executor`` string. The
dispatcher looks up the right backend (pandapower in-process, Sienna via
container, future GPU/distributed variants) and forwards the call.
"""

from __future__ import annotations

import sys
from typing import Any

from .backends import get_backend
from .data_tools import _resolve_snapshot
from .registry import register
from .result import ToolResult
from .scenario_tools import load_scenario


_DEFAULT_EXECUTOR = "pandapower"
_EXECUTORS = ["pandapower", "sienna"]

_STUDY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "scenario_id": {"type": "string"},
        "executor": {"type": "string", "enum": _EXECUTORS, "default": _DEFAULT_EXECUTOR},
    },
    "required": ["scenario_id"],
    "additionalProperties": True,
}


def _run(study: str, scenario_id: str, executor: str, **kwargs) -> ToolResult:
    scenario = load_scenario(scenario_id)
    snapshot = _resolve_snapshot(scenario.get("snapshot_id"))
    backend = get_backend(executor)
    method = getattr(backend, study)
    out = method(snapshot, scenario, **kwargs)
    return ToolResult(tool=f"run_{study}", value=out["value"], signal=out["signal"])


@register(
    name="run_power_flow",
    description="Solve AC power flow on a scenario.",
    schema=_STUDY_SCHEMA,
)
def run_power_flow(scenario_id: str, executor: str = _DEFAULT_EXECUTOR) -> ToolResult:
    return _run("power_flow", scenario_id, executor)


@register(
    name="run_n1_contingency",
    description="LODF-based N-1 contingency screening; returns ranked overload list.",
    schema={
        **_STUDY_SCHEMA,
        "properties": {
            **_STUDY_SCHEMA["properties"],
            "monitored": {"type": "array", "items": {"type": "string"}},
        },
    },
)
def run_n1_contingency(
    scenario_id: str,
    executor: str = _DEFAULT_EXECUTOR,
    monitored: list[str] | None = None,
) -> ToolResult:
    return _run("n1_contingency", scenario_id, executor, monitored=monitored)


@register(
    name="run_production_cost",
    description="UC + ED production cost simulation; returns LMPs and dispatch.",
    schema={
        **_STUDY_SCHEMA,
        "properties": {
            **_STUDY_SCHEMA["properties"],
            "horizon_hours": {"type": "integer", "default": 24},
        },
    },
)
def run_production_cost(
    scenario_id: str,
    executor: str = _DEFAULT_EXECUTOR,
    horizon_hours: int = 24,
) -> ToolResult:
    return _run("production_cost", scenario_id, executor, horizon_hours=horizon_hours)


# Side-effect imports so registration happens when this module is loaded.
def _ensure_loaded() -> None:
    from . import data_tools, scenario_tools  # noqa: F401


_ensure_loaded()
del sys  # avoid leaking
