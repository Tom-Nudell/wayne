"""Build a canonical Snapshot parquet bundle.

This is the contract every backend binds to. The snapshot is the *grid
state*; backends are *what you can do to it*. Two source paths supported
today:

* RTS-GMLC bronze CSVs → Snapshot directly. This is what the first study
  runs against — full transmission topology, generators, loads.
* Gold marts (network) → Snapshot. Once the gold marts cover topology
  (after PyPSA-USA or HIFLD ingest lands), this becomes the production
  path.

The output goes to ``BUNDLE / "snapshot_{date}_{label}"``.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from gridagent_data.paths import BRONZE, BUNDLE


def _bus_type_to_zone(bus_type: str) -> str:
    return {"PQ": "load", "PV": "gen", "Ref": "slack"}.get(str(bus_type), "load")


def from_rts_gmlc(label: str = "rts_gmlc") -> Path:
    """Convert RTS-GMLC bronze CSVs to a Snapshot bundle.

    Returns the snapshot directory path.
    """
    bronze = BRONZE / "rts_gmlc"
    if not (bronze / "bus.csv").exists():
        raise FileNotFoundError(
            f"RTS-GMLC bronze missing at {bronze}. Run the bronze fetcher first."
        )

    raw_buses = pd.read_csv(bronze / "bus.csv")
    raw_branches = pd.read_csv(bronze / "branch.csv")
    raw_gens = pd.read_csv(bronze / "gen.csv")

    # ----- buses -----
    buses = pd.DataFrame(
        {
            "bus_id": raw_buses["Bus ID"].astype(str),
            "name": raw_buses["Bus Name"].astype(str),
            "base_kv": raw_buses["BaseKV"].astype(float),
            "area": raw_buses["Area"].astype(str),
            "zone": raw_buses["Zone"].astype(str),
            "lat": raw_buses["lat"].astype(float),
            "lon": raw_buses["lng"].astype(float),
        }
    )

    # ----- loads (rolled up from bus PQ values) -----
    loads = pd.DataFrame(
        {
            "load_id": "L_" + raw_buses["Bus ID"].astype(str),
            "bus_id": raw_buses["Bus ID"].astype(str),
            "p_mw": raw_buses["MW Load"].astype(float),
            "q_mvar": raw_buses["MVAR Load"].astype(float),
            "in_service": True,
        }
    )
    # Drop zero-load rows so the snapshot is honest about where load actually is.
    loads = loads[loads["p_mw"].abs() + loads["q_mvar"].abs() > 0].reset_index(drop=True)

    # ----- branches -----
    branches = pd.DataFrame(
        {
            "branch_id": raw_branches["UID"].astype(str),
            "from_bus_id": raw_branches["From Bus"].astype(str),
            "to_bus_id": raw_branches["To Bus"].astype(str),
            "r_pu": raw_branches["R"].astype(float),
            "x_pu": raw_branches["X"].astype(float),
            "b_pu": raw_branches["B"].astype(float),
            "rating_a_mva": raw_branches["Cont Rating"].astype(float),
            "in_service": True,
        }
    )

    # ----- generators -----
    gens = pd.DataFrame(
        {
            "generator_id": raw_gens["GEN UID"].astype(str),
            "bus_id": raw_gens["Bus ID"].astype(str),
            "p_max_mw": raw_gens["PMax MW"].astype(float),
            "p_min_mw": raw_gens["PMin MW"].astype(float),
            "q_max_mvar": raw_gens["QMax MVAR"].astype(float),
            "q_min_mvar": raw_gens["QMin MVAR"].astype(float),
            "fuel": raw_gens["Fuel"].astype(str).str.lower().str.replace(" ", "_"),
            "in_service": True,
        }
    )

    date = datetime.now(tz=timezone.utc).strftime("%Y%m%d")
    snapshot_dir = BUNDLE / f"snapshot_{date}_{label}"
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    buses.to_parquet(snapshot_dir / "buses.parquet", index=False)
    branches.to_parquet(snapshot_dir / "branches.parquet", index=False)
    gens.to_parquet(snapshot_dir / "generators.parquet", index=False)
    loads.to_parquet(snapshot_dir / "loads.parquet", index=False)

    manifest = {
        "label": label,
        "built_at": datetime.now(tz=timezone.utc).isoformat(),
        "sources": ["rts_gmlc"],
        "counts": {
            "buses": int(len(buses)),
            "branches": int(len(branches)),
            "generators": int(len(gens)),
            "loads": int(len(loads)),
        },
        "base_mva": 100.0,
    }
    (snapshot_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return snapshot_dir
