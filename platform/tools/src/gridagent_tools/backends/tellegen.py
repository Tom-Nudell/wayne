"""Tellegen backend: subprocess shim over the ``tellegen`` CLI.

MIT-licensed Rust OPF engine (github.com/eigenergy/tellegen): DC OPF,
AC power flow, and the SOCWR relaxation, with analytical sensitivities.
The same code compiles to WASM — this backend is the native, server-side
face; the browser engine consumes the identical solve contract.

Covered here:

* ``power_flow``  → ``acpf`` (Newton AC power flow)
* ``dc_opf``      → ``dcopf`` (LMPs, dispatch, flows — the prices-on-map path)

``n1_contingency`` and ``production_cost`` intentionally raise
:class:`BackendUnavailable` — LODF screening stays on pandapower, UC/ED
stays on sienna. Tellegen complements those; it does not replace them.

Bridge: snapshot parquet → MATPOWER case text (written here; the snapshot
already carries per-unit branch data on the system base, which is exactly
MATPOWER's convention) → powerio (Python) → network JSON → ``tellegen``
subprocess (network on stdin, request JSON as argv, response on stdout).

Binary discovery: ``GRIDAGENT_TELLEGEN_BIN`` env var, else ``tellegen`` on
PATH. Both the binary and the ``powerio`` package are optional; missing
either raises :class:`BackendUnavailable` at call time, never at import.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Any

from ..snapshot import Snapshot
from .pandapower import _DEFAULT_FUEL_COST, _FUEL_COST_USD_PER_MWH
from .protocol import BackendUnavailable, register_backend

_SOLVE_TIMEOUT_S = 120


def _import_powerio():
    try:
        import powerio  # noqa: F401
        return powerio
    except ImportError as exc:  # pragma: no cover -- exercised when extra missing
        raise BackendUnavailable(
            "powerio not installed (bridges snapshot → tellegen network JSON). "
            "Install with: uv pip install powerio"
        ) from exc


def _tellegen_bin() -> str:
    binary = os.environ.get("GRIDAGENT_TELLEGEN_BIN") or shutil.which("tellegen")
    if not binary or not os.path.exists(binary) and shutil.which(binary) is None:
        raise BackendUnavailable(
            "tellegen binary not found. Build it (cargo build --release -p "
            "tellegen-cli) and set GRIDAGENT_TELLEGEN_BIN or add it to PATH."
        )
    return binary


# ---------------------------------------------------------------------------
# Snapshot → MATPOWER
# ---------------------------------------------------------------------------


def _apply_change_table(buses, branches, gens, loads, scenario: dict[str, Any]):
    """Same change-table semantics as ``pandapower._build_net``."""
    change_table = scenario.get("change_table", {}) or {}
    if "scale_load" in change_table:
        loads = loads.copy()
        loads["p_mw"] = loads["p_mw"] * float(change_table["scale_load"])
        loads["q_mvar"] = loads["q_mvar"] * float(change_table["scale_load"])
    if "scale_plant_capacity" in change_table:
        gens = gens.copy()
        for gen_id, factor in change_table["scale_plant_capacity"].items():
            mask = gens["generator_id"] == gen_id
            gens.loc[mask, "p_max_mw"] = gens.loc[mask, "p_max_mw"] * float(factor)
    if "out_of_service_branches" in change_table:
        branches = branches.copy()
        oos = set(change_table["out_of_service_branches"])
        branches.loc[branches["branch_id"].isin(oos), "in_service"] = False
    return buses, branches, gens, loads


def snapshot_to_matpower(
    snapshot: Snapshot, scenario: dict[str, Any]
) -> tuple[str, dict[str, Any]]:
    """Write a MATPOWER v2 case from a snapshot + scenario change-table.

    Returns ``(case_text, maps)`` where ``maps`` carries the 1-based
    MATPOWER row → Wayne string-id mappings needed to re-key results:
    ``bus_ids[i]``, ``gen_ids[i]``, ``branch_ids[i]`` (0-based lists in
    matrix row order).
    """
    buses, branches, gens, loads = _apply_change_table(
        snapshot.buses(), snapshot.branches(), snapshot.generators(), snapshot.loads(), scenario
    )
    base_mva = snapshot.base_mva

    buses = buses.sort_values("bus_id").reset_index(drop=True)
    bus_num = {str(b): i + 1 for i, b in enumerate(buses["bus_id"].astype(str))}

    gens_live = gens[gens["in_service"].astype(bool)].sort_values("generator_id")
    gens_live = gens_live[gens_live["bus_id"].astype(str).isin(bus_num)].reset_index(drop=True)

    # Same slack rule as the pandapower backend: largest unit, ties by id.
    slack_row = gens_live.sort_values(
        ["p_max_mw", "generator_id"], ascending=[False, True]
    ).iloc[0]
    slack_bus = str(slack_row.bus_id)

    # Aggregate demand per bus.
    loads_live = loads[loads["in_service"].astype(bool)]
    pd_by_bus = loads_live.groupby(loads_live["bus_id"].astype(str))["p_mw"].sum()
    qd_by_bus = loads_live.groupby(loads_live["bus_id"].astype(str))["q_mvar"].sum()
    gen_buses = set(gens_live["bus_id"].astype(str))

    bus_rows, bus_ids = [], []
    for row in buses.itertuples(index=False):
        bid = str(row.bus_id)
        btype = 3 if bid == slack_bus else (2 if bid in gen_buses else 1)
        bus_rows.append(
            f"\t{bus_num[bid]}\t{btype}\t{float(pd_by_bus.get(bid, 0.0)):.4f}"
            f"\t{float(qd_by_bus.get(bid, 0.0)):.4f}\t0\t0\t1\t1\t0"
            f"\t{float(row.base_kv):.2f}\t1\t1.1\t0.9;"
        )
        bus_ids.append(bid)

    # Same starting-dispatch rule as the pandapower backend: proportional to
    # capacity, scaled to total load (+2% loss margin), clipped to [pmin, pmax].
    total_pmax = float(gens_live["p_max_mw"].sum())
    total_load = float(loads_live["p_mw"].sum())
    dispatch_scale = min(1.0, 1.02 * total_load / total_pmax) if total_pmax > 0 else 0.0

    gen_rows, gencost_rows, gen_ids = [], [], []
    for row in gens_live.itertuples(index=False):
        p_start = min(
            max(dispatch_scale * float(row.p_max_mw), float(row.p_min_mw)),
            float(row.p_max_mw),
        )
        gen_rows.append(
            f"\t{bus_num[str(row.bus_id)]}\t{p_start:.4f}\t0"
            f"\t{float(row.q_max_mvar):.4f}\t{float(row.q_min_mvar):.4f}\t1"
            f"\t{base_mva:.1f}\t1\t{float(row.p_max_mw):.4f}\t{float(row.p_min_mw):.4f}"
            "\t0\t0\t0\t0\t0\t0\t0\t0\t0\t0\t0;"
        )
        fuel = str(getattr(row, "fuel", "") or "").strip().lower()
        cost = _FUEL_COST_USD_PER_MWH.get(fuel, _DEFAULT_FUEL_COST)
        gencost_rows.append(f"\t2\t0\t0\t2\t{cost:.4f}\t0;")
        gen_ids.append(str(row.generator_id))

    branch_rows, branch_ids = [], []
    for row in branches.itertuples(index=False):
        if not bool(row.in_service):
            continue
        f, t = bus_num.get(str(row.from_bus_id)), bus_num.get(str(row.to_bus_id))
        if f is None or t is None:
            continue
        rate = float(row.rating_a_mva) if row.rating_a_mva else 0.0
        branch_rows.append(
            f"\t{f}\t{t}\t{float(row.r_pu):.6f}\t{float(row.x_pu):.6f}"
            f"\t{float(row.b_pu):.6f}\t{rate:.2f}\t{rate:.2f}\t{rate:.2f}"
            "\t0\t0\t1\t-360\t360;"
        )
        branch_ids.append(str(row.branch_id))

    name = "wayne_snapshot"
    case = (
        f"function mpc = {name}\n"
        "mpc.version = '2';\n"
        f"mpc.baseMVA = {base_mva:.1f};\n\n"
        "mpc.bus = [\n" + "\n".join(bus_rows) + "\n];\n\n"
        "mpc.gen = [\n" + "\n".join(gen_rows) + "\n];\n\n"
        "mpc.branch = [\n" + "\n".join(branch_rows) + "\n];\n\n"
        "mpc.gencost = [\n" + "\n".join(gencost_rows) + "\n];\n"
    )
    return case, {"bus_ids": bus_ids, "gen_ids": gen_ids, "branch_ids": branch_ids}


def snapshot_to_network_json(
    snapshot: Snapshot, scenario: dict[str, Any]
) -> tuple[str, dict[str, Any], list[str]]:
    """Snapshot → powerio network JSON (what tellegen consumes) + id maps."""
    powerio = _import_powerio()
    case_text, maps = snapshot_to_matpower(snapshot, scenario)
    conv = powerio.convert_str(case_text, "powerio-json", "matpower")
    return conv.text, maps, list(conv.warnings)


# ---------------------------------------------------------------------------
# Solve
# ---------------------------------------------------------------------------


def _solve(network_json: str, request: dict[str, Any]) -> dict[str, Any]:
    binary = _tellegen_bin()
    proc = subprocess.run(
        [binary, json.dumps(request)],
        input=network_json,
        capture_output=True,
        text=True,
        timeout=_SOLVE_TIMEOUT_S,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"tellegen solve failed: {proc.stderr.strip()[:500]}")
    return json.loads(proc.stdout)


class TellegenBackend:
    name = "tellegen"

    def power_flow(self, snapshot: Snapshot, scenario: dict[str, Any]) -> dict[str, Any]:
        network_json, maps, warnings = snapshot_to_network_json(snapshot, scenario)
        try:
            resp = _solve(network_json, {"formulation": "acpf"})
        except (RuntimeError, subprocess.TimeoutExpired) as exc:
            return {
                "value": {"error": str(exc)},
                "signal": {"converged": False, "max_mismatch_mw": None},
            }

        converged = resp.get("status") in ("feasible", "optimal")
        iters = resp.get("iterations") or {}
        residual = iters.get("residual") if isinstance(iters, dict) else None
        vm = [b["value"] for b in resp.get("vm") or []]
        return {
            "value": {
                "n_buses": len(maps["bus_ids"]),
                "n_branches": len(maps["branch_ids"]),
                "newton_iterations": iters.get("count") if isinstance(iters, dict) else None,
                "vm_min_pu": min(vm) if vm else None,
                "vm_max_pu": max(vm) if vm else None,
                "bridge_warnings": warnings,
            },
            "signal": {
                "converged": converged,
                # Residual is per-unit on system base; MW at base_mva.
                "max_mismatch_mw": float(residual) * snapshot.base_mva
                if residual is not None
                else None,
            },
        }

    def dc_opf(self, snapshot: Snapshot, scenario: dict[str, Any]) -> dict[str, Any]:
        """DC OPF: LMPs, dispatch, branch flows. The prices-on-map study."""
        network_json, maps, warnings = snapshot_to_network_json(snapshot, scenario)
        try:
            resp = _solve(network_json, {"formulation": "dcopf"})
        except (RuntimeError, subprocess.TimeoutExpired) as exc:
            return {
                "value": {"error": str(exc)},
                "signal": {"solver_status": "ERROR", "objective": None},
            }

        bus_ids, gen_ids, branch_ids = maps["bus_ids"], maps["gen_ids"], maps["branch_ids"]
        lmp = [
            {"bus_id": bus_ids[b["bus"] - 1], "lmp_usd_per_mwh": float(b["value"])}
            for b in resp.get("lmp") or []
        ]
        dispatch = [
            {"generator_id": gen_ids[d["gen"] - 1], "p_mw": float(d["pg"])}
            for d in resp.get("dispatch") or []
        ]
        flows = [
            {
                "branch_id": branch_ids[f["branch"] - 1],
                "p_from_mw": float(f["pf"]),
                "loading_pct": 100.0 * float(f["loading"]),
            }
            for f in resp.get("flows") or []
        ]
        flows.sort(key=lambda r: r["loading_pct"], reverse=True)
        binding = [f for f in flows if f["loading_pct"] >= 99.99]
        lmp_vals = [r["lmp_usd_per_mwh"] for r in lmp]

        status = "OPTIMAL" if resp.get("status") == "optimal" else str(resp.get("status"))
        return {
            "value": {
                "objective_usd_per_hour": resp.get("objective"),
                "lmp": lmp,
                "dispatch": dispatch,
                "flows_top": flows[:50],
                "n_binding": len(binding),
                "binding_branches": [f["branch_id"] for f in binding],
                "bridge_warnings": warnings,
            },
            "signal": {
                "solver_status": status,
                "objective": resp.get("objective"),
                "lmp_min": min(lmp_vals) if lmp_vals else None,
                "lmp_max": max(lmp_vals) if lmp_vals else None,
                "lmp_spread": (max(lmp_vals) - min(lmp_vals)) if lmp_vals else None,
                "n_binding": len(binding),
            },
        }

    def n1_contingency(
        self, snapshot: Snapshot, scenario: dict[str, Any], *, monitored: list[str] | None = None
    ) -> dict[str, Any]:
        raise BackendUnavailable(
            "tellegen has no LODF N-1 screen; use executor='pandapower'."
        )

    def production_cost(
        self, snapshot: Snapshot, scenario: dict[str, Any], *, horizon_hours: int = 24
    ) -> dict[str, Any]:
        raise BackendUnavailable(
            "tellegen has no UC/ED; use executor='pandapower' (stopgap) or 'sienna'."
        )


register_backend(TellegenBackend())
