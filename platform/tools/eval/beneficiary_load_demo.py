#!/usr/bin/env python3
"""Build the deterministic RTS-GMLC beneficiary-load map demo fixture.

The demo deliberately keeps the two transfers separate:

* signed ADER action is balanced by the BA participation vector; and
* added POI load is independently supplied by that same BA vector.

It is a DC screening demonstration, not an AC-feasible operating plan.  The
committed JSON lets the web demo run without a Python solver in production,
while this script keeps every displayed number reproducible from the snapshot.
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

from gridagent_tools import beneficiary_screen
from gridagent_tools.backends.pandapower import _build_net
from gridagent_tools.snapshot import Snapshot


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SNAPSHOT = REPO_ROOT / "data_root/bundle/snapshot_20260415_rts_gmlc"
DEFAULT_OUTPUT = REPO_ROOT / "web/src/lib/study/beneficiary-load-demo.json"
EMERGENCY_RATING_MULTIPLIER = 1.25

# Assumed distributed-node portfolio. Positive means injection at the ADER
# node and compensating withdrawal across the BA reference; negative is the
# reverse. These are actions against the BA, never supply to a target POI.
ADER_ACTIONS_MW = {
    "304": 50.0,
    "305": 25.0,
    "306": 50.0,
    "307": -20.0,
    "308": 40.0,
    "309": 20.0,
}
ADER_LIMITS_MW = {bus_id: (-60.0, 60.0) for bus_id in ADER_ACTIONS_MW}

# Candidate target POIs are the larger load buses in the RTS area around the
# assumed ADER portfolio. Bus 318 is intentionally not included: in this
# snapshot an independent pre-existing contingency issue gives it zero base
# transfer capability under the demo's emergency-rating policy.
TARGET_POI_BUS_IDS = ("313", "310", "314", "319", "303", "315")
CONSTRAINTS_PER_POI = 4


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
    ppc_bus = ppc["bus"]
    ppc_branch = ppc["branch"]
    slack_index = int(np.flatnonzero(ppc_bus[:, 1] == 3)[0])
    ptdf = makePTDF(ppc["baseMVA"], ppc_bus, ppc_branch, slack=slack_index)
    with np.errstate(divide="ignore", invalid="ignore"):
        lodf = makeLODF(ppc_branch, ptdf)

    bus_ids = net.bus["name"].astype(str).to_numpy()
    branch_ids = net.line["name"].astype(str).to_numpy()
    bus_column = {bus_id: index for index, bus_id in enumerate(bus_ids)}
    bus_by_id = buses.assign(bus_id=buses["bus_id"].astype(str)).set_index("bus_id")
    branch_by_id = branches.assign(branch_id=branches["branch_id"].astype(str)).set_index(
        "branch_id"
    )

    # Canonical demo BA policy: live generator Pmax pro rata. H columns are
    # converted into BA-referenced factors d_q,b = a_q,b - a_q^T alpha.
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

    # Replace invalid LODF entries only for the arithmetic. Their complete
    # columns are excluded below as connectivity/islanding events.
    safe_lodf = np.where(np.isfinite(lodf), lodf, 0.0)
    referenced_factors = beneficiary_screen.ba_referenced_factors(
        beneficiary_screen.otdf_from_ptdf_lodf(ptdf, lodf), alpha
    )

    base_branch_flow = net.res_line["p_from_mw"].to_numpy(dtype=float)
    base_contingency_flow = (
        base_branch_flow[:, None] + safe_lodf * base_branch_flow[None, :]
    )
    islanding_outage = ~np.isfinite(lodf).all(axis=0)
    valid = np.broadcast_to(~islanding_outage[None, :], base_contingency_flow.shape).copy()
    valid &= ~np.eye(len(branch_ids), dtype=bool)

    live_branches = branches[branches["in_service"].astype(bool)]
    ratings = live_branches["rating_a_mva"].to_numpy(dtype=float)
    emergency_limits = (EMERGENCY_RATING_MULTIPLIER * ratings)[:, None]

    ader_bus_columns = np.array([bus_column[bus_id] for bus_id in ADER_ACTIONS_MW])
    ader_action = np.array(list(ADER_ACTIONS_MW.values()), dtype=float)

    load_by_bus = (
        loads[loads["in_service"].astype(bool)]
        .assign(bus_id=lambda frame: frame["bus_id"].astype(str))
        .groupby("bus_id")["p_mw"]
        .sum()
    )

    poi_bus_columns = [bus_column[bus_id] for bus_id in TARGET_POI_BUS_IDS]
    poi_results = beneficiary_screen.screen_beneficiary_loads(
        referenced_factors,
        base_contingency_flow,
        emergency_limits,
        valid,
        action_bus_columns=ader_bus_columns,
        action_mw=ader_action,
        poi_bus_columns=poi_bus_columns,
        constraints_per_poi=CONSTRAINTS_PER_POI,
        poi_sort_keys=TARGET_POI_BUS_IDS,
    )

    # --- Tier-screen section (additive; does not alter the fixed-dispatch
    # computation above). See beneficiary_screen module docstring's "Tiered
    # screening funnel" for semantics.
    d_base = ptdf - (ptdf @ alpha)[:, None]
    (
        tier_referenced_factors,
        tier_base_contingency_flow,
        tier_valid,
        intact_index,
    ) = beneficiary_screen.append_intact_contingency(
        referenced_factors, base_contingency_flow, valid, d_base, base_branch_flow
    )

    ader_withdrawal_max_mw = np.array(
        [-ADER_LIMITS_MW[bus_id][0] for bus_id in ADER_ACTIONS_MW], dtype=float
    )
    ader_injection_max_mw = np.array(
        [ADER_LIMITS_MW[bus_id][1] for bus_id in ADER_ACTIONS_MW], dtype=float
    )

    poi_potentials = beneficiary_screen.screen_poi_potential(
        tier_referenced_factors,
        tier_base_contingency_flow,
        emergency_limits,
        tier_valid,
        ader_bus_columns=ader_bus_columns,
        ader_injection_max_mw=ader_injection_max_mw,
        ader_withdrawal_max_mw=ader_withdrawal_max_mw,
        poi_bus_columns=poi_bus_columns,
        poi_sort_keys=TARGET_POI_BUS_IDS,
    )
    poi_potential_by_index = {result.poi_index: result for result in poi_potentials}

    recourse_by_index: dict[int, beneficiary_screen.RecourseResult] = {}
    for poi_index, bus_column in enumerate(poi_bus_columns):
        recourse_by_index[poi_index] = beneficiary_screen.poi_recourse_capacity(
            tier_referenced_factors,
            tier_base_contingency_flow,
            emergency_limits,
            tier_valid,
            ader_bus_columns=ader_bus_columns,
            ader_injection_max_mw=ader_injection_max_mw,
            ader_withdrawal_max_mw=ader_withdrawal_max_mw,
            poi_bus_column=bus_column,
        )

    for poi_index in range(len(poi_bus_columns)):
        potential = poi_potential_by_index[poi_index]
        recourse = recourse_by_index[poi_index]
        assert potential.headroom_mw - 1e-6 <= recourse.capacity_mw <= potential.potential_capacity_mw + 1e-6, (
            f"sandwich violated for POI index {poi_index}: "
            f"headroom={potential.headroom_mw} recourse={recourse.capacity_mw} "
            f"potential={potential.potential_capacity_mw}"
        )

    def _contingency_branch_id(contingency_index: int) -> str:
        if contingency_index == intact_index:
            return "INTACT"
        return str(branch_ids[contingency_index])

    def _screened_constraint_dict(
        constraint: beneficiary_screen.ScreenedConstraint,
    ) -> dict[str, Any]:
        return {
            "monitored_branch_id": str(branch_ids[constraint.monitored_index]),
            "outage_branch_id": _contingency_branch_id(constraint.contingency_index),
            "transfer_limit_mw": _round(constraint.transfer_limit_mw),
            "flow_mw": _round(constraint.flow_mw),
            "limit_mw": _round(constraint.limit_mw),
            "load_factor": _round(constraint.load_factor, 6),
        }

    pois: list[dict[str, Any]] = []
    for result in poi_results:
        bus_id = TARGET_POI_BUS_IDS[result.poi_index]
        poi_bus_column = poi_bus_columns[result.poi_index]

        # Per-contingency recourse dispatch x_c for this POI's displayed
        # rows. Cached because two rows can share a contingency; x_c is
        # per-(POI, contingency) since the LP depends on the POI's g. The
        # legacy row's outage_index already indexes the same contingency
        # columns as the tier arrays (append_intact_contingency only
        # appends a column after them), so it is used directly here.
        dispatch_cache: dict[int, np.ndarray] = {}

        constraint_rows: list[dict[str, Any]] = []
        for constraint in result.constraints:
            monitored_id = branch_ids[constraint.monitored_index]
            outage_id = branch_ids[constraint.outage_index]
            monitored = branch_by_id.loc[monitored_id]
            outage = branch_by_id.loc[outage_id]
            monitored_from = bus_by_id.loc[str(monitored["from_bus_id"])]
            monitored_to = bus_by_id.loc[str(monitored["to_bus_id"])]
            outage_from = bus_by_id.loc[str(outage["from_bus_id"])]
            outage_to = bus_by_id.loc[str(outage["to_bus_id"])]

            contingency_index = constraint.outage_index
            if contingency_index not in dispatch_cache:
                _, x_c = beneficiary_screen.recourse_dispatch_for_contingency(
                    tier_referenced_factors,
                    tier_base_contingency_flow,
                    emergency_limits,
                    tier_valid,
                    ader_bus_columns=ader_bus_columns,
                    ader_injection_max_mw=ader_injection_max_mw,
                    ader_withdrawal_max_mw=ader_withdrawal_max_mw,
                    poi_bus_column=poi_bus_column,
                    contingency_index=contingency_index,
                )
                dispatch_cache[contingency_index] = np.asarray(x_c, dtype=float)
            x_c = dispatch_cache[contingency_index]
            d_row = tier_referenced_factors[constraint.monitored_index, contingency_index, ader_bus_columns]
            recourse_flow_mw = constraint.base_flow_mw + float(d_row @ x_c)
            pre_existing_violation = abs(constraint.base_flow_mw) > constraint.limit_mw

            if pre_existing_violation:
                assert (
                    np.sign(constraint.base_flow_mw) * (recourse_flow_mw - constraint.base_flow_mw)
                    <= 1e-6
                ), (
                    f"recourse dispatch worsened a pre-violated pair for POI {bus_id}: "
                    f"{monitored_id}|{outage_id} base={constraint.base_flow_mw} "
                    f"recourse={recourse_flow_mw}"
                )
            else:
                assert abs(recourse_flow_mw) <= constraint.limit_mw + 1e-6, (
                    f"recourse dispatch created a new violation at T=0 for POI {bus_id}: "
                    f"{monitored_id}|{outage_id} recourse={recourse_flow_mw} "
                    f"limit={constraint.limit_mw}"
                )

            constraint_rows.append(
                {
                    "id": f"{monitored_id}|{outage_id}",
                    "rank": constraint.rank,
                    "monitored_branch_id": monitored_id,
                    "outage_branch_id": outage_id,
                    "monitored_coordinates": [
                        [_round(monitored_from["lon"], 6), _round(monitored_from["lat"], 6)],
                        [_round(monitored_to["lon"], 6), _round(monitored_to["lat"], 6)],
                    ],
                    "outage_coordinates": [
                        [_round(outage_from["lon"], 6), _round(outage_from["lat"], 6)],
                        [_round(outage_to["lon"], 6), _round(outage_to["lat"], 6)],
                    ],
                    "emergency_limit_mw": _round(constraint.limit_mw),
                    "base_flow_mw": _round(constraint.base_flow_mw),
                    "managed_flow_mw": _round(constraint.managed_flow_mw),
                    "ader_flow_change_mw": _round(constraint.ader_flow_change_mw),
                    "poi_load_factor": _round(constraint.poi_load_factor, 6),
                    "base_transfer_limit_mw": _round(constraint.base_transfer_limit_mw),
                    "managed_transfer_limit_mw": _round(constraint.managed_transfer_limit_mw),
                    "recourse_flow_mw": _round(recourse_flow_mw),
                    "pre_existing_violation": bool(pre_existing_violation),
                }
            )

        potential = poi_potential_by_index[result.poi_index]
        recourse = recourse_by_index[result.poi_index]
        next_capacity_mw = (
            None
            if not np.isfinite(potential.next_capacity_mw)
            else _round(potential.next_capacity_mw)
        )
        if recourse.binding_contingency_index is None:
            recourse_binding_contingency = None
            recourse_binding_dispatch = None
        else:
            recourse_binding_contingency = _contingency_branch_id(recourse.binding_contingency_index)
            recourse_binding_dispatch = [
                {"bus_id": ader_bus_id, "p_mw": _round(p_mw)}
                for ader_bus_id, p_mw in zip(ADER_ACTIONS_MW, recourse.binding_dispatch_mw)
            ]

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
                for ader_bus_id, relief_mw in zip(ADER_ACTIONS_MW, potential.ader_relief_mw)
            ],
            "recourse_binding_contingency": recourse_binding_contingency,
            "recourse_binding_dispatch": recourse_binding_dispatch,
        }

        bus = bus_by_id.loc[bus_id]
        pois.append(
            {
                "bus_id": bus_id,
                "name": str(bus["name"]),
                "coordinates": [_round(bus["lon"], 6), _round(bus["lat"], 6)],
                "existing_load_mw": _round(load_by_bus.get(bus_id, 0.0)),
                "base_capacity_mw": _round(result.base_capacity_mw),
                "managed_capacity_mw": _round(result.managed_capacity_mw),
                "unlocked_capacity_mw": _round(result.unlocked_capacity_mw),
                "constraints": constraint_rows,
                "rank": result.rank,
                "screen": screen,
            }
        )

    ader_nodes: list[dict[str, Any]] = []
    for bus_id, dispatch_mw in ADER_ACTIONS_MW.items():
        bus = bus_by_id.loc[bus_id]
        minimum_mw, maximum_mw = ADER_LIMITS_MW[bus_id]
        ader_nodes.append(
            {
                "bus_id": bus_id,
                "name": str(bus["name"]),
                "coordinates": [_round(bus["lon"], 6), _round(bus["lat"], 6)],
                "min_dispatch_mw": minimum_mw,
                "max_dispatch_mw": maximum_mw,
                "dispatch_mw": dispatch_mw,
            }
        )

    return {
        "metadata": {
            "study": "beneficiary_load_transfer_demo",
            "snapshot": snapshot_path.name,
            "model": "DC PTDF + single-outage LODF",
            "balance_policy": "live generator Pmax pro rata",
            "emergency_rating_multiplier": EMERGENCY_RATING_MULTIPLIER,
            "islanding_outages_excluded": int(islanding_outage.sum()),
            "screened_constraint_pairs": int(valid.sum()),
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
