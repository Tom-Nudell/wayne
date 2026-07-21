"""Tellegen evaluation harness — evidence for three strategic questions.

Q1  Is tellegen (or powerio's PTDF/LODF) useful as a *pre-compute
    conditioner* in front of Wayne studies? Measured: conditioner
    wall-time vs the full pandapower LODF N-1, and recall@k — whether a
    base-case-loading top-k monitored set captures the overloads the full
    screen finds.

Q2  Is there value in porting Sienna / other solvers to Rust and adding
    robust-PF methods (holomorphic embedding etc.)? Proxy measured: AC PF
    convergence under load scaling — where Newton (pandapower and
    tellegen both use NR) stops converging vs where DC OPF still solves.
    A wide gap = the region where HELM-class methods would add value.

Q3  Should DC OPF (→ SCOPF later) power a prices-on-the-map view?
    Measured: solver parity on *identical* MATPOWER input (isolates the
    solver from net-construction differences), LMP dual quality, solve
    latency vs the interactivity budget, and a 24-period sweep estimate.

Run:  GRIDAGENT_TELLEGEN_BIN=... .venv/bin/python platform/tools/eval/tellegen_eval.py [snapshot_dir]
Writes JSON results next to this file (tellegen_eval_results.json).
"""

from __future__ import annotations

import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

from gridagent_tools.backends import get_backend
from gridagent_tools.backends.tellegen import (
    _solve,
    _tellegen_bin,
    snapshot_to_matpower,
    snapshot_to_network_json,
)
from gridagent_tools.snapshot import Snapshot

DEFAULT_SNAPSHOT = "data_root/bundle/snapshot_20260415_rts_gmlc"
SCENARIO: dict = {"change_table": {}}


def _t(fn, *a, **kw):
    t0 = time.perf_counter()
    out = fn(*a, **kw)
    return out, time.perf_counter() - t0


# ---------------------------------------------------------------------------
# Q3 — solver parity + latency (prices on the map)
# ---------------------------------------------------------------------------


def _reference_dcopf(snap: Snapshot, scenario: dict) -> dict:
    """Independent arbiter: the DC OPF LP built straight from the snapshot
    tables (same data the MATPOWER writer uses) and solved with
    scipy/HiGHS. Variables: bus angles θ (slack fixed) and generator
    injections pg, in p.u. Lossless balance per bus, flow limits ±rate on
    rated branches, box bounds on pg, linear fuel costs."""
    from scipy.optimize import linprog
    from scipy.sparse import lil_matrix

    from gridagent_tools.backends.pandapower import (
        _DEFAULT_FUEL_COST,
        _FUEL_COST_USD_PER_MWH,
    )
    from gridagent_tools.backends.tellegen import _apply_change_table

    buses, branches, gens, loads = _apply_change_table(
        snap.buses(), snap.branches(), snap.generators(), snap.loads(), scenario
    )
    base = snap.base_mva
    buses = buses.sort_values("bus_id").reset_index(drop=True)
    bus_pos = {str(b): i for i, b in enumerate(buses["bus_id"].astype(str))}
    nb = len(buses)

    gens = gens[gens["in_service"].astype(bool)].sort_values("generator_id").reset_index(drop=True)
    gens = gens[gens["bus_id"].astype(str).isin(bus_pos)].reset_index(drop=True)
    ng = len(gens)
    slack_bus = str(
        gens.sort_values(["p_max_mw", "generator_id"], ascending=[False, True]).iloc[0].bus_id
    )

    loads_live = loads[loads["in_service"].astype(bool)]
    pd_bus = np.zeros(nb)
    for r in loads_live.itertuples(index=False):
        pd_bus[bus_pos[str(r.bus_id)]] += float(r.p_mw) / base

    live = branches[branches["in_service"].astype(bool)]
    live = live[
        live["from_bus_id"].astype(str).isin(bus_pos)
        & live["to_bus_id"].astype(str).isin(bus_pos)
    ].reset_index(drop=True)

    n = nb + ng
    a_eq = lil_matrix((nb + 1, n))
    b_eq = np.zeros(nb + 1)
    for r in live.itertuples(index=False):
        f, t = bus_pos[str(r.from_bus_id)], bus_pos[str(r.to_bus_id)]
        b_l = 1.0 / float(r.x_pu)
        a_eq[f, f] += b_l
        a_eq[f, t] -= b_l
        a_eq[t, t] += b_l
        a_eq[t, f] -= b_l
    for g in range(ng):
        a_eq[bus_pos[str(gens.at[g, "bus_id"])], nb + g] = -1.0
    b_eq[:nb] = -pd_bus
    a_eq[nb, bus_pos[slack_bus]] = 1.0  # θ_slack = 0

    rated = [r for r in live.itertuples(index=False) if r.rating_a_mva and r.rating_a_mva > 0]
    a_ub = lil_matrix((2 * len(rated), n))
    b_ub = np.zeros(2 * len(rated))
    for row, r in enumerate(rated):
        f, t = bus_pos[str(r.from_bus_id)], bus_pos[str(r.to_bus_id)]
        b_l = 1.0 / float(r.x_pu)
        rate = float(r.rating_a_mva) / base
        a_ub[2 * row, f] = b_l
        a_ub[2 * row, t] = -b_l
        b_ub[2 * row] = rate
        a_ub[2 * row + 1, f] = -b_l
        a_ub[2 * row + 1, t] = b_l
        b_ub[2 * row + 1] = rate

    c = np.zeros(n)
    for g in range(ng):
        fuel = str(gens.at[g, "fuel"] or "").strip().lower()
        c[nb + g] = _FUEL_COST_USD_PER_MWH.get(fuel, _DEFAULT_FUEL_COST) * base
    bounds = [(-np.inf, np.inf)] * nb + [
        (float(gens.at[g, "p_min_mw"]) / base, float(gens.at[g, "p_max_mw"]) / base)
        for g in range(ng)
    ]
    res = linprog(c, A_ub=a_ub.tocsr(), b_ub=b_ub, A_eq=a_eq.tocsr(), b_eq=b_eq,
                  bounds=bounds, method="highs")
    lmp = -res.eqlin.marginals[:nb] / base if res.status == 0 else None
    return {
        "status": int(res.status),
        "objective": float(res.fun) if res.status == 0 else None,
        "lmp_min": float(lmp.min()) if lmp is not None else None,
        "lmp_max": float(lmp.max()) if lmp is not None else None,
    }


def q3_prices(snap: Snapshot) -> dict:
    import pandapower as pp

    import powerio

    case_text, maps = snapshot_to_matpower(snap, SCENARIO)
    network_json, _, warnings = snapshot_to_network_json(snap, SCENARIO)

    # --- identical-input parity: same MATPOWER case into all three solvers ---
    conv = powerio.convert_str(case_text, "pandapower", "matpower")
    net = pp.from_json_string(conv.text)
    pp.rundcopp(net)
    pp_obj = float(net.res_cost)
    pp_lam = net.res_bus["lam_p"].to_numpy()

    reference = _reference_dcopf(snap, SCENARIO)

    tg = _solve(network_json, {"formulation": "dcopf"})
    tg_obj = float(tg["objective"])
    tg_lmp = np.array([b["value"] for b in tg["lmp"]])

    # --- latency: repeated solves ---
    n_rep = 10
    tg_times = []
    for _ in range(n_rep):
        _, dt = _t(_solve, network_json, {"formulation": "dcopf"})
        tg_times.append(dt)
    pp_times = []
    for _ in range(n_rep):
        _, dt = _t(pp.rundcopp, net)
        pp_times.append(dt)

    # bridge overhead (snapshot -> network JSON)
    _, bridge_dt = _t(snapshot_to_network_json, snap, SCENARIO)

    # --- socwr, if this build carries the conic feature ---
    socwr: dict = {"available": False}
    try:
        r, dt = _t(_solve, network_json, {"formulation": "socwr"})
        socwr = {"available": True, "status": r.get("status"), "objective": r.get("objective"), "seconds": dt}
    except RuntimeError as exc:
        socwr = {"available": False, "error": str(exc)[:200]}

    return {
        "identical_input_parity": {
            "reference_scipy_highs": reference,
            "pandapower_objective": pp_obj,
            "tellegen_objective": tg_obj,
            "objective_rel_diff": abs(pp_obj - tg_obj) / max(abs(pp_obj), 1e-9),
            "pandapower_lam_p_max_abs": float(np.abs(pp_lam).max()),
            "pandapower_duals_usable": bool(np.abs(pp_lam).max() > 1e-3),
            "tellegen_lmp_min": float(tg_lmp.min()),
            "tellegen_lmp_max": float(tg_lmp.max()),
            "tellegen_n_binding": sum(1 for f in tg["flows"] if f["loading"] >= 0.9999),
        },
        "latency_s": {
            "tellegen_dcopf_median": statistics.median(tg_times),
            "pandapower_dcopf_median": statistics.median(pp_times),
            "bridge_snapshot_to_json": bridge_dt,
            "sweep_24_periods_est_tellegen": 24 * statistics.median(tg_times) + bridge_dt,
        },
        "socwr": socwr,
        "bridge_warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Q1 — conditioner value
# ---------------------------------------------------------------------------


def q1_conditioner(snap: Snapshot) -> dict:
    pandapower_backend = get_backend("pandapower")

    # Ground truth + baseline cost: the full LODF screen.
    full, full_dt = _t(pandapower_backend.n1_contingency, snap, SCENARIO)
    truth_pairs = {(r["outage"], r["monitored"]) for r in full["value"]["ranking"]}
    truth_monitored = {r["monitored"] for r in full["value"]["ranking"]}

    # Conditioner A: tellegen DC OPF base-case loading ranking.
    network_json, maps, _ = snapshot_to_network_json(snap, SCENARIO)
    tg, tg_dt = _t(_solve, network_json, {"formulation": "dcopf"})
    loading = sorted(
        ((maps["branch_ids"][f["branch"] - 1], f["loading"]) for f in tg["flows"]),
        key=lambda x: x[1],
        reverse=True,
    )

    recall = {}
    for k in (10, 20, 30):
        topk = {b for b, _ in loading[:k]}
        hit = len(truth_monitored & topk)
        recall[f"monitored_recall@{k}"] = hit / max(len(truth_monitored), 1)

    # Screened-set cost: LODF restricted to top-20 monitored.
    top20 = [b for b, _ in loading[:20]]
    screened, screened_dt = _t(
        pandapower_backend.n1_contingency, snap, SCENARIO, monitored=top20
    )
    screened_pairs = {(r["outage"], r["monitored"]) for r in screened["value"]["ranking"]}

    # Conditioner B: powerio-native PTDF/LODF (Rust, in-process).
    powerio_lodf: dict = {"available": False}
    try:
        import powerio

        case_text, _ = snapshot_to_matpower(snap, SCENARIO)
        pnet = powerio.convert_str(case_text, "powerio-json", "matpower")
        pn = powerio.from_json(pnet.text)
        _, lodf_dt = _t(pn.lodf)
        _, ptdf_dt = _t(pn.ptdf)
        powerio_lodf = {"available": True, "lodf_seconds": lodf_dt, "ptdf_seconds": ptdf_dt}
    except Exception as exc:  # noqa: BLE001
        powerio_lodf = {"available": False, "error": str(exc)[:200]}

    return {
        "full_lodf_screen_s": full_dt,
        "full_overload_pairs": len(truth_pairs),
        "tellegen_dcopf_s": tg_dt,
        "recall_of_truth_monitored_set": recall,
        "screened_top20": {
            "seconds": screened_dt,
            "pairs_found": len(screened_pairs),
            "pairs_missed_vs_full": len(truth_pairs - screened_pairs),
            "pair_recall": len(truth_pairs & screened_pairs) / max(len(truth_pairs), 1),
        },
        "powerio_native_factors": powerio_lodf,
    }


# ---------------------------------------------------------------------------
# Q2 — robustness gap (HELM / Rust-port value proxy)
# ---------------------------------------------------------------------------


def q2_robustness(snap: Snapshot) -> dict:
    pandapower_backend = get_backend("pandapower")
    tellegen_backend = get_backend("tellegen")

    scales = [round(1.0 + 0.2 * i, 1) for i in range(9)]  # 1.0 .. 2.6
    rows = []
    for s in scales:
        scen = {"change_table": {"scale_load": s}}
        pp_out = pandapower_backend.power_flow(snap, scen)
        tg_out = tellegen_backend.power_flow(snap, scen)
        # DC OPF feasibility at the same scale (does the *optimization*
        # still find a dispatch, even where a fixed-dispatch AC PF fails?)
        try:
            nj, _, _ = snapshot_to_network_json(snap, scen)
            dc = _solve(nj, {"formulation": "dcopf"})
            dc_ok = dc.get("status") == "optimal"
        except (RuntimeError, subprocess.TimeoutExpired):
            dc_ok = False
        rows.append(
            {
                "scale_load": s,
                "pandapower_acpf_converged": bool(pp_out["signal"]["converged"]),
                "tellegen_acpf_converged": bool(tg_out["signal"]["converged"]),
                "tellegen_newton_iters": tg_out["value"].get("newton_iterations"),
                "dcopf_optimal": dc_ok,
            }
        )

    def onset(key):
        for r in rows:
            if not r[key]:
                return r["scale_load"]
        return None

    return {
        "sweep": rows,
        "pandapower_acpf_failure_onset": onset("pandapower_acpf_converged"),
        "tellegen_acpf_failure_onset": onset("tellegen_acpf_converged"),
        "dcopf_failure_onset": onset("dcopf_optimal"),
    }


def main() -> None:
    snap_dir = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SNAPSHOT
    snap = Snapshot.at(snap_dir)
    print(f"snapshot: {snap_dir} | tellegen: {_tellegen_bin()}", file=sys.stderr)

    results = {
        "snapshot": str(snap_dir),
        "q3_prices_on_map": q3_prices(snap),
        "q1_conditioner": q1_conditioner(snap),
        "q2_robustness": q2_robustness(snap),
    }
    out = Path(__file__).parent / "tellegen_eval_results.json"
    out.write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
