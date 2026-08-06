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


def _directional_transfer_limits(
    flows: np.ndarray,
    load_factor: np.ndarray,
    limits: np.ndarray,
    valid: np.ndarray,
) -> np.ndarray:
    """Return the positive-load limit for every monitored/outage pair."""
    transfer = np.full(flows.shape, np.inf, dtype=float)
    positive = load_factor > 1e-9
    negative = load_factor < -1e-9
    upper = np.broadcast_to(limits, flows.shape)
    with np.errstate(divide="ignore", invalid="ignore"):
        transfer[positive] = ((upper - flows) / load_factor)[positive]
        transfer[negative] = ((flows + upper) / (-load_factor))[negative]
    transfer[~valid] = np.inf
    return transfer


def _capacity(transfer_limits: np.ndarray) -> float:
    return max(0.0, float(np.nanmin(transfer_limits)))


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
    contingency_factors = (
        ptdf[:, None, :] + safe_lodf[:, :, None] * ptdf[None, :, :]
    )
    ba_component = np.einsum("mcb,b->mc", contingency_factors, alpha)
    referenced_factors = contingency_factors - ba_component[:, :, None]

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
    ader_flow_change = np.einsum(
        "mcd,d->mc", referenced_factors[:, :, ader_bus_columns], ader_action
    )
    managed_contingency_flow = base_contingency_flow + ader_flow_change

    load_by_bus = (
        loads[loads["in_service"].astype(bool)]
        .assign(bus_id=lambda frame: frame["bus_id"].astype(str))
        .groupby("bus_id")["p_mw"]
        .sum()
    )

    pois: list[dict[str, Any]] = []
    for bus_id in TARGET_POI_BUS_IDS:
        # Added load at POI l, supplied by the BA, has g_q,l = -d_q,l.
        load_factor = -referenced_factors[:, :, bus_column[bus_id]]
        base_limits = _directional_transfer_limits(
            base_contingency_flow, load_factor, emergency_limits, valid
        )
        managed_limits = _directional_transfer_limits(
            managed_contingency_flow, load_factor, emergency_limits, valid
        )
        base_capacity = _capacity(base_limits)
        managed_capacity = _capacity(managed_limits)

        # The smallest managed transfer limits are the constraints the slider
        # reaches first. Tie-break by the base limit and stable matrix index.
        candidates = np.flatnonzero(np.isfinite(managed_limits).ravel())
        candidates = sorted(
            candidates,
            key=lambda flat: (
                managed_limits.ravel()[flat],
                base_limits.ravel()[flat],
                int(flat),
            ),
        )[:CONSTRAINTS_PER_POI]

        constraint_rows: list[dict[str, Any]] = []
        for rank, flat in enumerate(candidates, start=1):
            monitored_index, outage_index = np.unravel_index(flat, managed_limits.shape)
            monitored_id = branch_ids[monitored_index]
            outage_id = branch_ids[outage_index]
            monitored = branch_by_id.loc[monitored_id]
            outage = branch_by_id.loc[outage_id]
            monitored_from = bus_by_id.loc[str(monitored["from_bus_id"])]
            monitored_to = bus_by_id.loc[str(monitored["to_bus_id"])]
            outage_from = bus_by_id.loc[str(outage["from_bus_id"])]
            outage_to = bus_by_id.loc[str(outage["to_bus_id"])]
            constraint_rows.append(
                {
                    "id": f"{monitored_id}|{outage_id}",
                    "rank": rank,
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
                    "emergency_limit_mw": _round(emergency_limits[monitored_index, 0]),
                    "base_flow_mw": _round(base_contingency_flow[monitored_index, outage_index]),
                    "managed_flow_mw": _round(
                        managed_contingency_flow[monitored_index, outage_index]
                    ),
                    "ader_flow_change_mw": _round(ader_flow_change[monitored_index, outage_index]),
                    "poi_load_factor": _round(load_factor[monitored_index, outage_index], 6),
                    "base_transfer_limit_mw": _round(
                        max(0.0, base_limits[monitored_index, outage_index])
                    ),
                    "managed_transfer_limit_mw": _round(
                        max(0.0, managed_limits[monitored_index, outage_index])
                    ),
                }
            )

        bus = bus_by_id.loc[bus_id]
        pois.append(
            {
                "bus_id": bus_id,
                "name": str(bus["name"]),
                "coordinates": [_round(bus["lon"], 6), _round(bus["lat"], 6)],
                "existing_load_mw": _round(load_by_bus.get(bus_id, 0.0)),
                "base_capacity_mw": _round(base_capacity),
                "managed_capacity_mw": _round(managed_capacity),
                "unlocked_capacity_mw": _round(managed_capacity - base_capacity),
                "constraints": constraint_rows,
            }
        )

    pois.sort(key=lambda poi: (-poi["unlocked_capacity_mw"], poi["bus_id"]))
    for rank, poi in enumerate(pois, start=1):
        poi["rank"] = rank

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
