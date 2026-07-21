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
_EXECUTORS = ["pandapower", "sienna", "tellegen"]

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
    name="run_dc_opf",
    description="Solve DC OPF on a scenario; returns LMPs, dispatch, flows, binding branches.",
    schema=_STUDY_SCHEMA,
)
def run_dc_opf(scenario_id: str, executor: str = _DEFAULT_EXECUTOR) -> ToolResult:
    return _run("dc_opf", scenario_id, executor)


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


@register(
    name="run_injection_study",
    description=(
        "Impact of injecting (+MW) or withdrawing (-MW) power at a bus vs the "
        "base case: ΔLMP, Δsystem-cost, and new/relieved N-1 overloads. The "
        "interconnection-screening study."
    ),
    schema={
        "type": "object",
        "properties": {
            "bus_id": {"type": "string"},
            "p_mw": {
                "type": "number",
                "description": "Positive injects (must-take generation); negative withdraws (load).",
            },
            "scenario_id": {
                "type": "string",
                "description": "Base scenario to perturb; omit for the newest-snapshot baseline.",
            },
            "executor": {"type": "string", "enum": _EXECUTORS, "default": "tellegen"},
        },
        "required": ["bus_id", "p_mw"],
        "additionalProperties": True,
    },
)
def run_injection_study(
    bus_id: str,
    p_mw: float,
    scenario_id: str | None = None,
    executor: str = "tellegen",
) -> ToolResult:
    """Base-vs-change diff. LMPs/objective come from ``executor`` (default
    tellegen — the engine with verified duals); the N-1 screen always runs
    on pandapower's LODF path."""
    base_scenario = (
        load_scenario(scenario_id) if scenario_id else {"change_table": {}, "snapshot_id": None}
    )
    snapshot = _resolve_snapshot(base_scenario.get("snapshot_id"))

    buses = set(snapshot.buses()["bus_id"].astype(str))
    if str(bus_id) not in buses:
        raise ValueError(f"bus_id {bus_id!r} not in snapshot ({len(buses)} buses)")
    if float(p_mw) == 0.0:
        raise ValueError("p_mw must be nonzero (positive injects, negative withdraws)")

    change_table = dict(base_scenario.get("change_table") or {})
    injections = dict(change_table.get("add_injection") or {})
    injections[str(bus_id)] = float(injections.get(str(bus_id), 0.0)) + float(p_mw)
    modified_scenario = {**base_scenario, "change_table": {**change_table, "add_injection": injections}}

    opf = get_backend(executor)
    lodf = get_backend("pandapower")
    base_opf = opf.dc_opf(snapshot, base_scenario)
    mod_opf = opf.dc_opf(snapshot, modified_scenario)
    base_n1 = lodf.n1_contingency(snapshot, base_scenario)
    mod_n1 = lodf.n1_contingency(snapshot, modified_scenario)

    feasible = mod_opf["signal"].get("solver_status") == "OPTIMAL"

    def lmp_map(out: dict[str, Any]) -> dict[str, float]:
        return {r["bus_id"]: r["lmp_usd_per_mwh"] for r in out["value"].get("lmp") or []}

    base_lmp, mod_lmp = lmp_map(base_opf), lmp_map(mod_opf)
    delta_lmp = {b: mod_lmp[b] - base_lmp[b] for b in base_lmp if b in mod_lmp}
    delta_at_bus = delta_lmp.get(str(bus_id))
    max_bus, max_delta = None, 0.0
    for b, d in delta_lmp.items():
        if abs(d) > abs(max_delta):
            max_bus, max_delta = b, d

    def pairs(out: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
        return {
            (r["outage"], r["monitored"]): r for r in out["value"].get("ranking") or []
        }

    base_pairs, mod_pairs = pairs(base_n1), pairs(mod_n1)
    new_overloads = [mod_pairs[k] for k in mod_pairs.keys() - base_pairs.keys()]
    new_overloads.sort(key=lambda r: r.get("loading_pct", 0.0), reverse=True)
    n_relieved = len(base_pairs.keys() - mod_pairs.keys())

    base_obj = base_opf["signal"].get("objective")
    mod_obj = mod_opf["signal"].get("objective")
    delta_obj = (mod_obj - base_obj) if (base_obj is not None and mod_obj is not None) else None

    value: dict[str, Any] = {
        "bus_id": str(bus_id),
        "p_mw": float(p_mw),
        "direction": "injection" if p_mw > 0 else "withdrawal",
        "feasible": feasible,
        "objective_base_usd_per_hour": base_obj,
        "objective_modified_usd_per_hour": mod_obj,
        "delta_objective_usd_per_hour": delta_obj,
        "lmp_at_bus_base": base_lmp.get(str(bus_id)),
        "lmp_at_bus_modified": mod_lmp.get(str(bus_id)),
        "delta_lmp_at_bus": delta_at_bus,
        "max_abs_delta_lmp": {"bus_id": max_bus, "delta_usd_per_mwh": max_delta},
        "new_overloads": new_overloads[:20],
        "n_new_overloads": len(new_overloads),
        "n_relieved_overloads": n_relieved,
        "opf_error": mod_opf["value"].get("error"),
    }
    signal: dict[str, Any] = {
        "feasible": feasible,
        "delta_objective": delta_obj,
        "delta_lmp_at_bus": delta_at_bus,
        "n_new_overloads": len(new_overloads),
        "n_relieved_overloads": n_relieved,
        "worst_new_loading_pct": float(new_overloads[0]["loading_pct"]) if new_overloads else 0.0,
    }
    return ToolResult(tool="run_injection_study", value=value, signal=signal)


# Side-effect imports so registration happens when this module is loaded.
def _ensure_loaded() -> None:
    from . import data_tools, scenario_tools  # noqa: F401


_ensure_loaded()
del sys  # avoid leaking
