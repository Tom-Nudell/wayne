"""Export gold marts to a single portable DuckDB file for DuckDB-WASM use.

The atlas frontend loads this file via HTTP range requests (DuckDB-WASM
supports partial reads), which lets us run SQL filters over the feature
catalog and market tables without a backend.

Input: the dbt warehouse under ``DATA_ROOT/warehouse.duckdb``.
Output: a single ``bundle.duckdb`` containing flat (non-schema-prefixed)
copies of every gold_* table.  Keeping the table names flat in the
exported file means the frontend can do ``SELECT * FROM plants`` without
knowing about dbt's schema layout.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import duckdb

# Map of ``(source_schema, source_table)`` → exported flat table name.
# Keep names stable; the atlas SQL layer binds to them.
_EXPORTS: dict[tuple[str, str], str] = {
    ("main_gold_network", "gold_network__buses"): "buses",
    ("main_gold_network", "gold_network__branches"): "branches",
    ("main_gold_network", "gold_network__loads"): "loads",
    ("main_gold_network", "gold_network__generators"): "generators",
    ("main_gold_atlas", "gold_atlas__infrastructure_features"): "infrastructure_features",
    ("main_gold_market", "gold_market__lmp_hourly"): "lmp_hourly",
    ("main_gold_market", "gold_market__load_hourly"): "load_hourly",
    ("main_gold_market", "gold_market__generation_by_ba_hourly"): "generation_by_ba_hourly",
    ("main_gold_market", "gold_market__queue_snapshot"): "queue_snapshot",
}


def export(warehouse_path: Path, out_path: Path) -> Path:
    """Build a portable ``bundle.duckdb`` containing every flat gold table.

    Args:
        warehouse_path: The dbt-managed warehouse (e.g. ``data_root/warehouse.duckdb``).
        out_path: Where to write ``bundle.duckdb``. Overwritten if it exists.
    """
    warehouse_path = Path(warehouse_path)
    out_path = Path(out_path)
    if not warehouse_path.is_file():
        raise FileNotFoundError(f"Warehouse not found at {warehouse_path}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        out_path.unlink()

    # ATTACH both databases in a fresh process so the warehouse can stay
    # write-locked by Dagster without us blocking it.
    conn = duckdb.connect(str(out_path))
    try:
        conn.execute(f"ATTACH '{warehouse_path}' AS src (READ_ONLY)")
        for (schema, table), flat_name in _EXPORTS.items():
            conn.execute(
                f'CREATE OR REPLACE TABLE "{flat_name}" AS '
                f'SELECT * FROM src."{schema}"."{table}"'
            )
    finally:
        conn.close()

    return out_path


def copy_to_atlas_public(bundle_path: Path, atlas_public_dir: Path) -> Path:
    """Drop ``bundle.duckdb`` into the atlas frontend's public/ dir.

    Convenience for local dev: after ``export`` you can run this to make
    the bundle visible to ``vite dev`` under ``/bundle.duckdb``.
    """
    bundle_path = Path(bundle_path)
    atlas_public_dir = Path(atlas_public_dir)
    atlas_public_dir.mkdir(parents=True, exist_ok=True)
    target = atlas_public_dir / "bundle.duckdb"
    shutil.copy2(bundle_path, target)
    return target
