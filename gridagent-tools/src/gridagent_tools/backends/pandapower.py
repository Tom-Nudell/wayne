"""In-process pandapower backend.

BSD-3 licensed; pure Python; default while bringing the platform up.

N-1 contingency uses **DC LODF screening** rather than re-solving N AC PFs
per branch — the same approach `PowerNetworkMatrices.jl` takes. Cheap and
gives a defensible first-cut overload ranking.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from ..snapshot import Snapshot
from .protocol import Backend, BackendUnavailable, register_backend


def _import_pandapower():
    try:
        import pandapower as pp  # noqa: F401
        return pp
    except ImportError as exc:  # pragma: no cover -- exercised when extra missing
        raise BackendUnavailable(
            "pandapower not installed. Install with: uv sync --extra pandapower"
        ) from exc


def _build_net(snapshot: Snapshot, scenario: dict[str, Any]):
    """Materialize a pandapower Network from a snapshot + scenario change-table."""
    pp = _import_pandapower()
    buses = snapshot.buses()
    branches = snapshot.branches()
    gens = snapshot.generators()
    loads = snapshot.loads()
    base_mva = snapshot.base_mva

    # Apply change-table mutations *before* materializing the net.
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

    net = pp.create_empty_network(sn_mva=base_mva)

    bus_idx: dict[str, int] = {}
    for row in buses.itertuples(index=False):
        idx = pp.create_bus(net, vn_kv=float(row.base_kv), name=str(row.bus_id), zone=str(row.zone or ""))
        bus_idx[str(row.bus_id)] = idx

    # Pick a slack bus: largest generator's bus, deterministic by generator_id.
    slack_gen = gens.sort_values(["p_max_mw", "generator_id"], ascending=[False, True]).iloc[0]
    slack_bus_idx = bus_idx[str(slack_gen.bus_id)]
    pp.create_ext_grid(net, bus=slack_bus_idx, vm_pu=1.0, name="slack")

    branch_id_to_pp: dict[str, int] = {}
    for row in branches.itertuples(index=False):
        if not bool(row.in_service):
            continue
        f = bus_idx.get(str(row.from_bus_id))
        t = bus_idx.get(str(row.to_bus_id))
        if f is None or t is None:
            continue
        # Convert per-unit (on system base) to ohm at line nominal voltage.
        v_kv = float(buses.loc[buses["bus_id"] == str(row.from_bus_id), "base_kv"].iloc[0])
        z_base_ohm = (v_kv ** 2) / base_mva
        idx = pp.create_line_from_parameters(
            net,
            from_bus=f,
            to_bus=t,
            length_km=1.0,
            r_ohm_per_km=float(row.r_pu) * z_base_ohm,
            x_ohm_per_km=float(row.x_pu) * z_base_ohm,
            c_nf_per_km=max(float(row.b_pu) * 1e3, 1.0),  # placeholder; LODF doesn't use it
            max_i_ka=float(row.rating_a_mva) / (np.sqrt(3) * v_kv) if row.rating_a_mva else 1.0,
            name=str(row.branch_id),
        )
        branch_id_to_pp[str(row.branch_id)] = idx

    for row in gens.itertuples(index=False):
        if not bool(row.in_service):
            continue
        b = bus_idx.get(str(row.bus_id))
        if b is None:
            continue
        # Dispatch each gen to its mid-point as a starting cut; PF will balance via slack.
        p_mw = max(0.0, 0.5 * float(row.p_max_mw))
        pp.create_gen(
            net,
            bus=b,
            p_mw=p_mw,
            max_p_mw=float(row.p_max_mw),
            min_p_mw=float(row.p_min_mw),
            name=str(row.generator_id),
        )

    for row in loads.itertuples(index=False):
        if not bool(row.in_service):
            continue
        b = bus_idx.get(str(row.bus_id))
        if b is None:
            continue
        pp.create_load(
            net,
            bus=b,
            p_mw=float(row.p_mw),
            q_mvar=float(row.q_mvar),
            name=str(row.load_id),
        )

    return net, bus_idx, branch_id_to_pp


class PandapowerBackend:
    name = "pandapower"

    def power_flow(self, snapshot: Snapshot, scenario: dict[str, Any]) -> dict[str, Any]:
        pp = _import_pandapower()
        net, _, _ = _build_net(snapshot, scenario)
        try:
            pp.runpp(net, algorithm="nr", init="auto")
            converged = bool(net["converged"])
        except Exception as exc:  # noqa: BLE001 -- surface as signal, not crash
            return {
                "value": {"error": str(exc)},
                "signal": {"converged": False, "max_mismatch_mw": None},
            }

        max_mismatch = float(np.abs(net.res_bus[["p_mw", "q_mvar"]].values).max()) if converged else None
        return {
            "value": {
                "n_buses": len(net.bus),
                "n_branches": len(net.line),
                "slack_p_mw": float(net.res_ext_grid["p_mw"].iloc[0]) if converged else None,
                "slack_q_mvar": float(net.res_ext_grid["q_mvar"].iloc[0]) if converged else None,
            },
            "signal": {"converged": converged, "max_mismatch_mw": max_mismatch},
        }

    def n1_contingency(
        self, snapshot: Snapshot, scenario: dict[str, Any], *, monitored: list[str] | None = None
    ) -> dict[str, Any]:
        """DC LODF N-1 screen: rank monitored branches by post-contingency loading."""
        pp = _import_pandapower()
        from pandapower.pypower.makeLODF import makeLODF
        from pandapower.pypower.makePTDF import makePTDF
        from pandapower.pd2ppc import _pd2ppc

        net, _, branch_idx = _build_net(snapshot, scenario)
        # DC PF gives the base-case branch flows we'll perturb with LODF.
        pp.rundcpp(net)

        ppc, _ = _pd2ppc(net)
        baseMVA = ppc["baseMVA"]
        bus = ppc["bus"]
        branch = ppc["branch"]
        slack_idx = int(np.flatnonzero(bus[:, 1] == 3)[0])

        ptdf = makePTDF(baseMVA, bus, branch, slack=slack_idx)
        # makeLODF emits a RuntimeWarning + inf/nan for radial (bridge) outages
        # because the diagonal-correction step divides by 1 - PTDF_jj ≈ 0. We
        # detect those columns and exclude them from the ranking — outaging a
        # bridge islands the network, which is a *connectivity* event, not a
        # thermal overload, and would otherwise dominate the ranking with inf%.
        with np.errstate(divide="ignore", invalid="ignore"):
            lodf = makeLODF(branch, ptdf)  # shape: (n_lines, n_outages)

        base_flow_mw = net.res_line["p_from_mw"].values  # signed
        ratings_mva = np.array(
            [
                float(net.line["max_i_ka"].iloc[i]) * np.sqrt(3) * float(net.bus.loc[net.line["from_bus"].iloc[i], "vn_kv"])
                for i in range(len(net.line))
            ]
        )
        # Avoid divide-by-zero on lines without a rating.
        ratings_mva = np.where(ratings_mva > 0, ratings_mva, np.inf)

        line_names = net.line["name"].astype(str).values

        # Bridge / islanding detection: any non-finite entry in column j means
        # outage j disconnects the network; surface separately.
        islanding_mask = ~np.isfinite(lodf).all(axis=0)
        islanding_outages = [str(line_names[j]) for j in np.where(islanding_mask)[0]]

        if monitored:
            monitored_set = set(monitored)
            monitor_mask = np.array([n in monitored_set for n in line_names])
        else:
            monitor_mask = np.ones(len(line_names), dtype=bool)

        # post-flow_ij = base_i + LODF_ij * base_j  (Wood & Wollenberg, 11.13).
        # Skip islanding columns so they don't generate inf-loading rows.
        valid_outages = ~islanding_mask
        post = base_flow_mw[:, None] + lodf * base_flow_mw[None, :]
        # Outage of branch j shouldn't show flow on j itself.
        np.fill_diagonal(post, 0.0)
        loading_pct = 100.0 * np.abs(post) / ratings_mva[:, None]
        # Zero out islanding columns and any residual non-finite entries.
        loading_pct[:, islanding_mask] = 0.0
        post[:, islanding_mask] = 0.0
        loading_pct = np.where(np.isfinite(loading_pct), loading_pct, 0.0)

        overloads: list[dict[str, Any]] = []
        for j in np.where(valid_outages)[0]:
            for i in np.where(monitor_mask & (loading_pct[:, j] > 100.0))[0]:
                overloads.append(
                    {
                        "outage": str(line_names[j]),
                        "monitored": str(line_names[i]),
                        "post_flow_mw": float(post[i, j]),
                        "rating_mva": float(ratings_mva[i]),
                        "loading_pct": float(loading_pct[i, j]),
                    }
                )
        overloads.sort(key=lambda r: r["loading_pct"], reverse=True)
        # Monotonicity: ranking is sorted desc by construction. Surface as signal.
        monotone = all(
            overloads[i]["loading_pct"] >= overloads[i + 1]["loading_pct"]
            for i in range(len(overloads) - 1)
        )

        n_screened = int(monitor_mask.sum()) * int(valid_outages.sum())
        return {
            "value": {
                "n_screened": n_screened,
                "ranking": overloads[:50],  # top 50; full list streams to log on demand
                "ranking_total": len(overloads),
                "islanding_outages": islanding_outages,
            },
            "signal": {
                "n_overloads": len(overloads),
                "n_screened": n_screened,
                "n_islanding": len(islanding_outages),
                "monotone": monotone,
                "worst_loading_pct": float(overloads[0]["loading_pct"]) if overloads else 0.0,
            },
        }

    def production_cost(
        self, snapshot: Snapshot, scenario: dict[str, Any], *, horizon_hours: int = 24
    ) -> dict[str, Any]:  # pragma: no cover
        # Production cost is out of scope for the in-process backend in v1.
        # Sienna (PowerSimulations.jl + HiGHS) is the right home for this.
        raise NotImplementedError(
            "production_cost not implemented in pandapower backend; "
            "use the 'sienna' backend (requires Julia)."
        )


register_backend(PandapowerBackend())
