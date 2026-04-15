"""Canonical snapshot format consumed by every backend.

A snapshot is a directory of small parquet files — the same shape regardless
of which upstream sources produced it (PUDL + RTS-GMLC today; PyPSA-USA +
HIFLD + OSM later). Backends bind to this on-disk format, *not* to any
particular study engine, so adding a new backend (pandapower, Sienna,
PowerWorld bridge, …) only requires writing a snapshot reader.

Per-table schemas are deliberately small and unit-stamped. Anything beyond
the minimum needed for AC PF + LODF lives in companion columns the backend
is free to ignore.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

# Column contracts the platform guarantees. Any extra columns are passed
# through as metadata; backends must not assume their absence breaks the file.

BUS_COLUMNS = {
    "bus_id": "string",        # canonical; stable across snapshots
    "name": "string",
    "base_kv": "float64",
    "area": "string",
    "zone": "string",
    "lat": "float64",
    "lon": "float64",
}

BRANCH_COLUMNS = {
    "branch_id": "string",
    "from_bus_id": "string",
    "to_bus_id": "string",
    "r_pu": "float64",         # per-unit on snapshot.base_mva
    "x_pu": "float64",
    "b_pu": "float64",
    "rating_a_mva": "float64", # normal continuous rating
    "in_service": "bool",
}

GENERATOR_COLUMNS = {
    "generator_id": "string",
    "bus_id": "string",
    "p_max_mw": "float64",
    "p_min_mw": "float64",
    "q_max_mvar": "float64",
    "q_min_mvar": "float64",
    "fuel": "string",
    "in_service": "bool",
}

LOAD_COLUMNS = {
    "load_id": "string",
    "bus_id": "string",
    "p_mw": "float64",
    "q_mvar": "float64",
    "in_service": "bool",
}


@dataclass(frozen=True)
class Snapshot:
    """Lightweight handle to a snapshot directory; lazy parquet reads."""

    root: Path
    base_mva: float = 100.0

    @classmethod
    def at(cls, path: str | Path) -> "Snapshot":
        root = Path(path)
        if not (root / "buses.parquet").exists():
            raise FileNotFoundError(f"No snapshot at {root} (missing buses.parquet)")
        return cls(root=root)

    def buses(self) -> pd.DataFrame:
        return pd.read_parquet(self.root / "buses.parquet")

    def branches(self) -> pd.DataFrame:
        return pd.read_parquet(self.root / "branches.parquet")

    def generators(self) -> pd.DataFrame:
        return pd.read_parquet(self.root / "generators.parquet")

    def loads(self) -> pd.DataFrame:
        return pd.read_parquet(self.root / "loads.parquet")

    def manifest_path(self) -> Path:
        return self.root / "manifest.json"


def write_snapshot(
    root: Path,
    *,
    buses: pd.DataFrame,
    branches: pd.DataFrame,
    generators: pd.DataFrame,
    loads: pd.DataFrame,
) -> Snapshot:
    """Validate column contracts and persist parquet files."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)

    for name, df, schema in (
        ("buses", buses, BUS_COLUMNS),
        ("branches", branches, BRANCH_COLUMNS),
        ("generators", generators, GENERATOR_COLUMNS),
        ("loads", loads, LOAD_COLUMNS),
    ):
        missing = [c for c in schema if c not in df.columns]
        if missing:
            raise ValueError(f"{name}: missing required columns {missing}")
        df.to_parquet(root / f"{name}.parquet", index=False)

    return Snapshot(root=root)
