"""In-process pandapower backend.

BSD-3 licensed; pure Python; default while bringing the platform up.

N-1 contingency uses **DC LODF screening** rather than re-solving N AC PFs
per branch — the same approach `PowerNetworkMatrices.jl` takes. Cheap and
gives a defensible first-cut overload ranking.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from ..snapshot import Snapshot
from .protocol import BackendUnavailable, register_backend


def _import_pandapower():
    try:
        import pandapower as pp  # noqa: F401
        return pp
    except ImportError as exc:  # pragma: no cover -- exercised when extra missing
        raise BackendUnavailable(
            "pandapower not installed. Install with: uv sync --extra pandapower"
        ) from exc


def _apply_injections(gens, loads, change_table: dict[str, Any]):
    """Apply ``add_injection`` ({bus_id: ±MW}) to the gen/load frames.

    Positive MW appends a **must-take generator** (pmin = pmax = MW) so the
    OPF cannot re-dispatch it away — an injection study asks "what does the
    grid do if this power shows up", not "would the market take it".
    Negative MW appends a load. Shared by every backend so the semantics
    can't drift.
    """
    import pandas as pd

    injections = change_table.get("add_injection") or {}
    if not injections:
        return gens, loads
    gen_rows, load_rows = [], []
    for bus_id, raw_mw in injections.items():
        mw = float(raw_mw)
        if mw > 0:
            gen_rows.append(
                {
                    "generator_id": f"injection_{bus_id}",
                    "bus_id": str(bus_id),
                    "p_max_mw": mw,
                    "p_min_mw": mw,
                    "q_max_mvar": 0.0,
                    "q_min_mvar": 0.0,
                    "fuel": "injection",
                    "in_service": True,
                }
            )
        elif mw < 0:
            load_rows.append(
                {
                    "load_id": f"withdrawal_{bus_id}",
                    "bus_id": str(bus_id),
                    "p_mw": -mw,
                    "q_mvar": 0.0,
                    "in_service": True,
                }
            )
    if gen_rows:
        gens = pd.concat([gens, pd.DataFrame(gen_rows)], ignore_index=True)
    if load_rows:
        loads = pd.concat([loads, pd.DataFrame(load_rows)], ignore_index=True)
    return gens, loads


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
    gens, loads = _apply_injections(gens, loads, change_table)

    net = pp.create_empty_network(sn_mva=base_mva)

    bus_idx: dict[str, int] = {}
    for row in buses.itertuples(index=False):
        idx = pp.create_bus(net, vn_kv=float(row.base_kv), name=str(row.bus_id), zone=str(row.zone or ""))
        bus_idx[str(row.bus_id)] = idx

    # Pick a slack: largest generator, deterministic by generator_id. We mark
    # it ``slack=True`` rather than spawning an ``ext_grid``, so OPF sees a
    # bounded dispatchable unit (with a real cost curve) at this bus — no
    # infinite penalty slack distorting the objective. Must-take injections
    # are excluded — a slack's output floats, which would silently un-fix
    # the very quantity an injection study holds constant.
    slack_candidates = gens[gens["fuel"].astype(str) != "injection"]
    slack_gen_row = slack_candidates.sort_values(
        ["p_max_mw", "generator_id"], ascending=[False, True]
    ).iloc[0]
    slack_generator_id = str(slack_gen_row.generator_id)

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

    # Dispatch proportional to capacity, scaled to meet total load (+2% loss
    # margin), so the PF starting point is electrically sane. The previous
    # midpoint cut left ~15% of RTS-GMLC load on the slack bus and NR diverged
    # on the *base case*.
    live_gens = gens[gens["in_service"].astype(bool)]
    total_pmax = float(live_gens["p_max_mw"].sum())
    total_load = float(loads.loc[loads["in_service"].astype(bool), "p_mw"].sum())
    dispatch_scale = min(1.0, 1.02 * total_load / total_pmax) if total_pmax > 0 else 0.0

    for row in gens.itertuples(index=False):
        if not bool(row.in_service):
            continue
        b = bus_idx.get(str(row.bus_id))
        if b is None:
            continue
        p_mw = float(np.clip(dispatch_scale * float(row.p_max_mw), float(row.p_min_mw), float(row.p_max_mw)))
        pp.create_gen(
            net,
            bus=b,
            p_mw=p_mw,
            max_p_mw=float(row.p_max_mw),
            min_p_mw=float(row.p_min_mw),
            name=str(row.generator_id),
            type=str(getattr(row, "fuel", "") or ""),  # used by OPF for cost lookup
            slack=(str(row.generator_id) == slack_generator_id),
            vm_pu=1.0,
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
        # The slack is a gen row (slack=True), not an ext_grid — report its dispatch.
        slack_mask = net.gen["slack"].astype(bool)
        slack_p = float(net.res_gen.loc[slack_mask, "p_mw"].sum()) if converged else None
        slack_q = float(net.res_gen.loc[slack_mask, "q_mvar"].sum()) if converged else None
        return {
            "value": {
                "n_buses": len(net.bus),
                "n_branches": len(net.line),
                "slack_p_mw": slack_p,
                "slack_q_mvar": slack_q,
            },
            "signal": {"converged": converged, "max_mismatch_mw": max_mismatch},
        }

    def dc_opf(self, snapshot: Snapshot, scenario: dict[str, Any]) -> dict[str, Any]:
        """Single-period DC OPF with LMP duals (``lam_p``) — parity twin of the
        tellegen backend's ``dc_opf``; same value/signal shape."""
        pp = _import_pandapower()
        net, _, _ = _build_net(snapshot, scenario)
        _attach_costs(net)
        try:
            pp.rundcopp(net)
            converged = bool(net.OPF_converged)
        except Exception as exc:  # noqa: BLE001 -- surface as signal, not crash
            return {
                "value": {"error": str(exc)},
                "signal": {"solver_status": "ERROR", "objective": None},
            }
        if not converged:
            return {
                "value": {"error": "OPF did not converge"},
                "signal": {"solver_status": "INFEASIBLE", "objective": None},
            }

        lmp = [
            {"bus_id": str(net.bus.at[i, "name"]), "lmp_usd_per_mwh": float(net.res_bus.at[i, "lam_p"])}
            for i in net.bus.index
        ]
        dispatch = [
            {"generator_id": str(net.gen.at[i, "name"]), "p_mw": float(net.res_gen.at[i, "p_mw"])}
            for i in net.gen.index
        ]
        flows = [
            {
                "branch_id": str(net.line.at[i, "name"]),
                "p_from_mw": float(net.res_line.at[i, "p_from_mw"]),
                "loading_pct": float(net.res_line.at[i, "loading_percent"]),
            }
            for i in net.line.index
        ]
        flows.sort(key=lambda r: r["loading_pct"], reverse=True)
        binding = [f for f in flows if f["loading_pct"] >= 99.99]
        lmp_vals = [r["lmp_usd_per_mwh"] for r in lmp]
        objective = float(net.res_cost)
        return {
            "value": {
                "objective_usd_per_hour": objective,
                "lmp": lmp,
                "dispatch": dispatch,
                "flows_top": flows[:50],
                "n_binding": len(binding),
                "binding_branches": [f["branch_id"] for f in binding],
            },
            "signal": {
                "solver_status": "OPTIMAL",
                "objective": objective,
                "lmp_min": min(lmp_vals) if lmp_vals else None,
                "lmp_max": max(lmp_vals) if lmp_vals else None,
                "lmp_spread": (max(lmp_vals) - min(lmp_vals)) if lmp_vals else None,
                "n_binding": len(binding),
            },
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
    ) -> dict[str, Any]:
        """Hourly DC-OPF sweep as a production-cost stopgap.

        This is *not* a full unit-commitment model. It solves an independent
        single-period DC-OPF per hour, so there are no ramping constraints,
        no min-up/down, and no reserves. It exists so the agent surface is
        fully callable before the Sienna (PowerSimulations.jl) container
        backend lands. Same ``value`` / ``signal`` shape, so trajectories
        don't change when we swap in the high-fidelity backend.

        Hourly load pattern is a simple diurnal multiplier applied to the
        snapshot's load; swap in a real profile from ``gold.market`` once
        that mart exists.

        Marginal costs are per-fuel placeholders until EIA-923 heat rates +
        ATB fuel prices are wired in via ``gold.market.generator_costs``.
        """
        pp = _import_pandapower()

        base_net, _, _ = _build_net(snapshot, scenario)
        _attach_costs(base_net)

        profile = _diurnal_profile(horizon_hours)
        base_load_p = base_net.load["p_mw"].to_numpy().copy()
        base_load_q = base_net.load["q_mvar"].to_numpy().copy()

        hours: list[dict[str, Any]] = []
        total_cost = 0.0
        total_slack = 0.0
        solver_status = "OPTIMAL"
        worst_slack = 0.0

        for hour, mult in enumerate(profile):
            base_net.load["p_mw"] = base_load_p * mult
            base_net.load["q_mvar"] = base_load_q * mult
            try:
                pp.rundcopp(base_net)
                converged = bool(base_net.OPF_converged)
            except Exception as exc:  # noqa: BLE001 -- report as solver failure
                solver_status = f"ERROR: {exc}"
                converged = False

            if not converged:
                solver_status = "INFEASIBLE"
                hours.append({"hour": hour, "converged": False})
                continue

            hour_cost = float(base_net.res_cost)
            total_cost += hour_cost
            gen_p = base_net.res_gen["p_mw"].to_numpy() if not base_net.res_gen.empty else np.array([])
            load_p = base_net.res_load["p_mw"].to_numpy() if not base_net.res_load.empty else np.array([])
            # Balance residual: in DC OPF without losses, gen should equal
            # load exactly. Any residual is numerical; > a few MW means the
            # problem was infeasible and the solver hit a bound.
            slack_p = abs(float(gen_p.sum()) - float(load_p.sum()))
            total_slack += slack_p
            worst_slack = max(worst_slack, slack_p)

            hours.append(
                {
                    "hour": hour,
                    "converged": True,
                    "load_multiplier": float(mult),
                    "cost_usd": hour_cost,
                    "slack_mw": slack_p,
                }
            )

        converged_hours = [h for h in hours if h.get("converged")]

        return {
            "value": {
                "horizon_hours": horizon_hours,
                "total_cost_usd": total_cost,
                "hours": hours,
                "backend_note": (
                    "pandapower DC-OPF stopgap: no UC, no ramping, no reserves; "
                    "costs are per-fuel placeholders; LMP duals not populated "
                    "(use the sienna backend once available for real LMPs)."
                ),
            },
            "signal": {
                "solver_status": solver_status,
                "objective": total_cost,
                "slack_mw": worst_slack,
                "n_hours_solved": len(converged_hours),
                "n_hours": horizon_hours,
            },
        }


# Per-fuel marginal cost placeholder ($/MWh). Replace with EIA-923 heat rate ×
# ATB fuel price once ``gold.market.generator_costs`` is wired in.
_FUEL_COST_USD_PER_MWH: dict[str, float] = {
    "solar": 0.0,
    "wind": 0.0,
    "hydro": 5.0,
    "nuclear": 10.0,
    "coal": 30.0,
    "gas": 50.0,
    "ng": 50.0,
    "natural_gas": 50.0,
    "oil": 120.0,
    "biomass": 40.0,
    "geothermal": 15.0,
    "storage": 0.0,
    # Must-take injection-study resource: dispatch is pinned (pmin = pmax),
    # zero cost keeps the objective clean of placeholder pricing.
    "injection": 0.0,
}
_DEFAULT_FUEL_COST = 40.0


def _attach_costs(net) -> None:
    """Attach per-generator polycost rows so ``rundcopp`` has an objective.

    Fuel label is stored on the gen's ``type`` column by ``_build_net``; we
    normalize (lower-case, strip) and look it up in the cost table.
    """
    pp = _import_pandapower()
    for gen_idx in net.gen.index:
        fuel = str(net.gen.at[gen_idx, "type"] or "").strip().lower()
        cost = _FUEL_COST_USD_PER_MWH.get(fuel, _DEFAULT_FUEL_COST)
        pp.create_poly_cost(net, gen_idx, "gen", cp1_eur_per_mw=cost)


def _diurnal_profile(horizon_hours: int) -> np.ndarray:
    """Simple 24-hour diurnal load multiplier, repeated to fill the horizon.

    Peaks at hour 18 (~1.15×), trough at hour 4 (~0.80×). Deliberately
    tame — the real profile comes from ``gold.market`` once GridStatus is
    wired in. Same shape for any horizon so runs are reproducible.
    """
    hours = np.arange(horizon_hours)
    return 1.0 + 0.175 * np.cos((hours - 18) * 2 * np.pi / 24.0) - 0.025


register_backend(PandapowerBackend())
