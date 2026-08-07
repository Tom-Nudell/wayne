#!/usr/bin/env python3
"""Build the Texas 7k beneficiary-load map demo fixture.

Same output schema as ``beneficiary_load_demo.py`` (the RTS-GMLC fixture),
but the Texas 7k network is too large to screen with the full (M, C, B)
OTDF cube that script materializes. This script is cube-free throughout:

* the monitored set is restricted to the 345 kV network (~400 branches,
  not the full ~9,000+ branch set);
* the BA-referenced sensitivity factors are built for ONLY the bus columns
  that matter -- the 8 ADER nodes and 8 candidate POIs -- via
  ``d_base_sel = H[:, sel] - (H @ alpha)[:, None]``, then broadcast against
  LODF restricted to the monitored rows;
* contingencies are all branch outages (9,139) plus the intact network via
  :func:`gridagent_tools.beneficiary_screen.append_intact_contingency`.

Tier 0/1/2 screening (headroom / certified bound / exact DC recourse) is
unaffected by this restriction: those functions only ever need the ADER and
POI bus columns, never a full cube. The legacy fixed-dispatch fields (the
schema this fixture shares with the RTS-GMLC demo) are computed the same
way, just against the restricted arrays instead of the full cube.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandapower as pp
from pandapower.pd2ppc import _pd2ppc
from pandapower.pypower.makeLODF import makeLODF
from pandapower.pypower.makePTDF import makePTDF

from gridagent_tools import beneficiary_screen as bs
from gridagent_tools.backends.pandapower import _build_net
from gridagent_tools.snapshot import Snapshot


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SNAPSHOT = REPO_ROOT / "data_root/bundle/snapshot_20250509_texas7k"
DEFAULT_OUTPUT = REPO_ROOT / "web/src/lib/study/beneficiary-load-texas7k.json"
EMERGENCY_RATING_MULTIPLIER = 1.25
CONSTRAINTS_PER_POI = 4

# Per-node dispatch capability screened by Tier 1/Tier 2 (the certified
# bound and exact recourse value are independent of the specific example
# dispatch below -- they use these bounds, not a fixed action).
ADER_BOUND_MW = 100.0

# Example fixed, signed dispatch used only for the legacy (pre-tier-funnel)
# base/managed/unlocked capacity fields and the ader_nodes' dispatch_mw
# display value -- an illustrative single action, not the tier screen.
ADER_DISPATCH_MW = [80.0, 60.0, 50.0, -30.0, 40.0, 20.0, -20.0, 50.0]


def _round(value: float, digits: int = 3) -> float:
    return round(float(value), digits)


def build_fixture(snapshot_path: Path) -> dict[str, Any]:
    snapshot = Snapshot.at(snapshot_path)
    buses = snapshot.buses()
    branches = snapshot.branches()
    generators = snapshot.generators()
    loads = snapshot.loads()

    net, _, _ = _build_net(snapshot, {})
    pp.rundcpp(net, numba=False)
    ppc, _ = _pd2ppc(net)
    slack_index = int(np.flatnonzero(ppc["bus"][:, 1] == 3)[0])
    ptdf = makePTDF(ppc["baseMVA"], ppc["bus"], ppc["branch"], slack=slack_index)
    with np.errstate(divide="ignore", invalid="ignore"):
        lodf = makeLODF(ppc["branch"], ptdf)

    bus_ids = net.bus["name"].astype(str).to_numpy()
    branch_ids = net.line["name"].astype(str).to_numpy()
    bus_column = {bus_id: index for index, bus_id in enumerate(bus_ids)}
    bus_by_id = buses.assign(bus_id=buses["bus_id"].astype(str)).set_index("bus_id")
    branch_by_id = branches.assign(branch_id=branches["branch_id"].astype(str)).set_index(
        "branch_id"
    )

    # BA reference: live generator Pmax pro rata (same policy as the RTS demo).
    alpha = np.zeros(len(bus_ids), dtype=float)
    live_generation = (
        generators[generators["in_service"].astype(bool)]
        .assign(bus_id=lambda frame: frame["bus_id"].astype(str))
        .groupby("bus_id")["p_max_mw"]
        .sum()
    )
    for bus_id, p_max_mw in live_generation.items():
        alpha[bus_column[bus_id]] += float(p_max_mw)
    alpha /= alpha.sum()

    # Monitored set: 345 kV network branches (both ends 345 kV), in service.
    kv_by_bus = buses.set_index(buses["bus_id"].astype(str))["base_kv"]
    live_branches = branches[branches["in_service"].astype(bool)].copy()
    monitored_mask = (
        live_branches["from_bus_id"].astype(str).map(kv_by_bus) == 345
    ) & (live_branches["to_bus_id"].astype(str).map(kv_by_bus) == 345)
    monitored_branch_ids = set(live_branches[monitored_mask]["branch_id"].astype(str))
    mon_idx = np.array(
        [i for i, name in enumerate(branch_ids) if name in monitored_branch_ids]
    )

    # ADER + POI selection: COAST-area 138 kV load buses, largest loads.
    load_by_bus = (
        loads[loads["in_service"].astype(bool)]
        .assign(bus_id=lambda frame: frame["bus_id"].astype(str))
        .groupby("bus_id")["p_mw"]
        .sum()
    )
    bus_info = buses.set_index(buses["bus_id"].astype(str))
    coast_138_by_load = [
        bus_id
        for bus_id in load_by_bus.sort_values(ascending=False).index
        if bus_id in bus_column
        and bus_info.loc[bus_id, "area"] == "COAST"
        and bus_info.loc[bus_id, "base_kv"] == 138.0
    ]
    ader_buses = coast_138_by_load[:8]
    poi_buses = coast_138_by_load[8:16]
    ader_bus_columns_global = np.array([bus_column[bus_id] for bus_id in ader_buses])
    poi_bus_columns_global = [bus_column[bus_id] for bus_id in poi_buses]

    ader_injection_max_mw = np.full(len(ader_buses), ADER_BOUND_MW)
    ader_withdrawal_max_mw = np.full(len(ader_buses), ADER_BOUND_MW)

    # --- Cube-free tier arrays -------------------------------------------
    # BA-referenced base factors for ONLY the ADER+POI bus columns -- never
    # materialize the full (M, C, B) cube.
    sel = np.concatenate([ader_bus_columns_global, np.array(poi_bus_columns_global)])
    d_base_sel = ptdf[:, sel] - (ptdf @ alpha)[:, None]  # (all_branches, n_sel)
    safe_lodf = np.where(np.isfinite(lodf), lodf, 0.0)
    base_branch_flow = net.res_line["p_from_mw"].to_numpy(dtype=float)

    d = (
        d_base_sel[mon_idx][:, None, :]
        + safe_lodf[mon_idx][:, :, None] * d_base_sel[None, :, :]
    )  # (M_mon, C_all, n_sel)
    base_contingency_flow = (
        base_branch_flow[mon_idx][:, None] + safe_lodf[mon_idx] * base_branch_flow[None, :]
    )  # (M_mon, C_all)

    islanding_outage = ~np.isfinite(lodf).all(axis=0)
    valid = np.broadcast_to(~islanding_outage[None, :], base_contingency_flow.shape).copy()
    for row_index, global_branch_index in enumerate(mon_idx):
        valid[row_index, global_branch_index] = False  # self-outage

    ratings = branch_by_id.loc[branch_ids, "rating_a_mva"].to_numpy(dtype=float)
    emergency_limits = (EMERGENCY_RATING_MULTIPLIER * ratings[mon_idx])[:, None]

    (
        tier_referenced_factors,
        tier_base_contingency_flow,
        tier_valid,
        intact_index,
    ) = bs.append_intact_contingency(
        d, base_contingency_flow, valid, d_base_sel[mon_idx], base_branch_flow[mon_idx]
    )

    ader_columns_local = np.arange(len(ader_buses))
    poi_columns_local = list(range(len(ader_buses), len(sel)))

    poi_potentials = bs.screen_poi_potential(
        tier_referenced_factors,
        tier_base_contingency_flow,
        emergency_limits,
        tier_valid,
        ader_bus_columns=ader_columns_local,
        ader_injection_max_mw=ader_injection_max_mw,
        ader_withdrawal_max_mw=ader_withdrawal_max_mw,
        poi_bus_columns=poi_columns_local,
        poi_sort_keys=poi_buses,
    )
    poi_potential_by_index = {result.poi_index: result for result in poi_potentials}

    recourse_by_index: dict[int, bs.RecourseResult] = {}
    for poi_index, bus_column_local in enumerate(poi_columns_local):
        recourse_by_index[poi_index] = bs.poi_recourse_capacity(
            tier_referenced_factors,
            tier_base_contingency_flow,
            emergency_limits,
            tier_valid,
            ader_bus_columns=ader_columns_local,
            ader_injection_max_mw=ader_injection_max_mw,
            ader_withdrawal_max_mw=ader_withdrawal_max_mw,
            poi_bus_column=bus_column_local,
        )

    for poi_index in range(len(poi_columns_local)):
        potential = poi_potential_by_index[poi_index]
        recourse = recourse_by_index[poi_index]
        assert potential.headroom_mw - 1e-6 <= recourse.capacity_mw <= potential.potential_capacity_mw + 1e-6, (
            f"sandwich violated for POI index {poi_index}: "
            f"headroom={potential.headroom_mw} recourse={recourse.capacity_mw} "
            f"potential={potential.potential_capacity_mw}"
        )

    # --- Legacy fixed-dispatch fields (same semantics as the RTS script,
    # via the cube-free restricted arrays) --------------------------------
    ader_action = np.array(ADER_DISPATCH_MW, dtype=float)
    ader_flow_change = bs.dispatch_flow_change(
        tier_referenced_factors, ader_columns_local, ader_action
    )
    managed_contingency_flow = tier_base_contingency_flow + ader_flow_change

    def _contingency_branch_id(contingency_index: int) -> str:
        if contingency_index == intact_index:
            return "INTACT"
        return str(branch_ids[contingency_index])

    def _screened_constraint_dict(constraint: bs.ScreenedConstraint) -> dict[str, Any]:
        return {
            "monitored_branch_id": str(branch_ids[mon_idx[constraint.monitored_index]]),
            "outage_branch_id": _contingency_branch_id(constraint.contingency_index),
            "transfer_limit_mw": _round(constraint.transfer_limit_mw),
            "flow_mw": _round(constraint.flow_mw),
            "limit_mw": _round(constraint.limit_mw),
            "load_factor": _round(constraint.load_factor, 6),
        }

    pois: list[dict[str, Any]] = []
    for poi_index, bus_id in enumerate(poi_buses):
        bus_column_local = poi_columns_local[poi_index]
        load_factor = -tier_referenced_factors[:, :, bus_column_local]
        base_limits = bs.transfer_limits(
            tier_base_contingency_flow, load_factor, emergency_limits, tier_valid
        )
        managed_limits = bs.transfer_limits(
            managed_contingency_flow, load_factor, emergency_limits, tier_valid
        )
        base_capacity = max(0.0, float(np.nanmin(base_limits)))
        managed_capacity = max(0.0, float(np.nanmin(managed_limits)))
        unlocked_capacity = managed_capacity - base_capacity

        candidates = np.flatnonzero(np.isfinite(managed_limits).ravel())
        candidates = sorted(
            candidates,
            key=lambda flat: (
                managed_limits.ravel()[flat],
                base_limits.ravel()[flat],
                int(flat),
            ),
        )[:CONSTRAINTS_PER_POI]

        limit_broadcast = np.broadcast_to(emergency_limits, tier_base_contingency_flow.shape)
        constraint_rows: list[dict[str, Any]] = []
        for rank, flat in enumerate(candidates, start=1):
            m, c = np.unravel_index(flat, managed_limits.shape)
            monitored_id = str(branch_ids[mon_idx[m]])
            outage_id = _contingency_branch_id(int(c))
            monitored = branch_by_id.loc[monitored_id]
            monitored_from = bus_by_id.loc[str(monitored["from_bus_id"])]
            monitored_to = bus_by_id.loc[str(monitored["to_bus_id"])]
            monitored_coordinates = [
                [_round(monitored_from["lon"], 6), _round(monitored_from["lat"], 6)],
                [_round(monitored_to["lon"], 6), _round(monitored_to["lat"], 6)],
            ]
            if outage_id == "INTACT":
                outage_coordinates = monitored_coordinates
            else:
                outage = branch_by_id.loc[outage_id]
                outage_from = bus_by_id.loc[str(outage["from_bus_id"])]
                outage_to = bus_by_id.loc[str(outage["to_bus_id"])]
                outage_coordinates = [
                    [_round(outage_from["lon"], 6), _round(outage_from["lat"], 6)],
                    [_round(outage_to["lon"], 6), _round(outage_to["lat"], 6)],
                ]
            constraint_rows.append(
                {
                    "id": f"{monitored_id}|{outage_id}",
                    "rank": rank,
                    "monitored_branch_id": monitored_id,
                    "outage_branch_id": outage_id,
                    "monitored_coordinates": monitored_coordinates,
                    "outage_coordinates": outage_coordinates,
                    "emergency_limit_mw": _round(float(limit_broadcast[m, c])),
                    "base_flow_mw": _round(float(tier_base_contingency_flow[m, c])),
                    "managed_flow_mw": _round(float(managed_contingency_flow[m, c])),
                    "ader_flow_change_mw": _round(float(ader_flow_change[m, c])),
                    "poi_load_factor": _round(float(load_factor[m, c]), 6),
                    "base_transfer_limit_mw": _round(max(0.0, float(base_limits[m, c]))),
                    "managed_transfer_limit_mw": _round(max(0.0, float(managed_limits[m, c]))),
                }
            )

        potential = poi_potential_by_index[poi_index]
        recourse = recourse_by_index[poi_index]
        next_capacity_mw = (
            None
            if not np.isfinite(potential.next_capacity_mw)
            else _round(potential.next_capacity_mw)
        )
        screen = {
            "rank": potential.rank,
            "headroom_mw": _round(potential.headroom_mw),
            "next_capacity_mw": next_capacity_mw,
            "potential_capacity_mw": _round(potential.potential_capacity_mw),
            "potential_unlock_mw": _round(potential.potential_unlock_mw),
            "recourse_capacity_mw": _round(recourse.capacity_mw),
            "binding": _screened_constraint_dict(potential.binding),
            "potential_binding": _screened_constraint_dict(potential.potential_binding),
            "co_binding_count": len(potential.co_binding),
            "ader_relief_mw": [
                {"bus_id": ader_bus_id, "relief_mw": _round(relief_mw)}
                for ader_bus_id, relief_mw in zip(ader_buses, potential.ader_relief_mw)
            ],
        }

        bus = bus_by_id.loc[bus_id]
        pois.append(
            {
                "bus_id": bus_id,
                "name": str(bus["name"]),
                "coordinates": [_round(bus["lon"], 6), _round(bus["lat"], 6)],
                "existing_load_mw": _round(load_by_bus.get(bus_id, 0.0)),
                "base_capacity_mw": _round(base_capacity),
                "managed_capacity_mw": _round(managed_capacity),
                "unlocked_capacity_mw": _round(unlocked_capacity),
                "constraints": constraint_rows,
                "rank": potential.rank,
                "screen": screen,
            }
        )

    # POI ordering: by tier screen.rank (there is no meaningful legacy
    # unlock signal in this case -- headroom is 0 for all eight POIs).
    pois.sort(key=lambda poi: poi["screen"]["rank"])

    ader_nodes: list[dict[str, Any]] = []
    for bus_id, dispatch_mw in zip(ader_buses, ADER_DISPATCH_MW):
        bus = bus_by_id.loc[bus_id]
        ader_nodes.append(
            {
                "bus_id": bus_id,
                "name": str(bus["name"]),
                "coordinates": [_round(bus["lon"], 6), _round(bus["lat"], 6)],
                "min_dispatch_mw": -ADER_BOUND_MW,
                "max_dispatch_mw": ADER_BOUND_MW,
                "dispatch_mw": dispatch_mw,
            }
        )

    return {
        "metadata": {
            "study": "beneficiary_load_transfer_texas7k",
            "snapshot": snapshot_path.name,
            "model": "DC PTDF + single-outage LODF (345 kV monitored set, cube-free)",
            "balance_policy": "live generator Pmax pro rata",
            "emergency_rating_multiplier": EMERGENCY_RATING_MULTIPLIER,
            "islanding_outages_excluded": int(islanding_outage.sum()),
            "screened_constraint_pairs": int(tier_valid.sum()),
            "ader_net_dispatch_mw": _round(ader_action.sum()),
            "ba_reference_dispatch_mw": _round(-ader_action.sum()),
            "screen_method": "poi_potential_v1",
            "screen_ader_bounds_mw": float(ader_injection_max_mw[0]),
            "screen_includes_intact": True,
            "screen_note": (
                "potential_capacity_mw is a certified optimistic bound (Tier 1); "
                "recourse_capacity_mw is the exact DC recourse value (Tier 2); "
                "headroom <= recourse <= potential holds for every POI."
            ),
            "monitored_branch_count": int(len(mon_idx)),
            "contingency_count": int(len(branch_ids)),
            "case_attribution": "Texas A&M University released open synthetic test case (Texas 7k)",
        },
        "ader_nodes": ader_nodes,
        "pois": pois,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    fixture = build_fixture(args.snapshot)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(fixture, indent=2) + "\n")
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
