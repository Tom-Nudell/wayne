"""Data tools: read-only DuckDB queries against a snapshot bundle."""

from __future__ import annotations

import json
import os
from pathlib import Path

import duckdb

from .registry import register
from .result import ToolResult
from .snapshot import Snapshot


def _bundle_root() -> Path:
    return Path(os.environ.get("GRIDAGENT_DATA_ROOT", "data_root")) / "bundle"


def _resolve_snapshot(snapshot_id: str | None) -> Snapshot:
    root = _bundle_root()
    if snapshot_id:
        return Snapshot.at(root / snapshot_id)
    # Only consider directories that actually contain parquet files — tile-bundle
    # directories (e.g. snapshot_latest) share the snapshot_ prefix but hold
    # bundle.duckdb + tiles/ instead of buses.parquet, and must be skipped.
    candidates = sorted(
        (
            p for p in root.iterdir()
            if p.is_dir() and p.name.startswith("snapshot_") and (p / "buses.parquet").exists()
        ),
        reverse=True,
    )
    if not candidates:
        raise FileNotFoundError(f"No parquet snapshots in {root}.")
    return Snapshot.at(candidates[0])


@register(
    name="list_data_snapshots",
    description="Enumerate available snapshot bundles, newest first.",
    schema={"type": "object", "properties": {}, "additionalProperties": False},
)
def list_data_snapshots() -> ToolResult:
    root = _bundle_root()
    snapshots: list[dict] = []
    if root.exists():
        for p in sorted(
            (
                p for p in root.iterdir()
                if p.is_dir() and p.name.startswith("snapshot_") and (p / "buses.parquet").exists()
            ),
            reverse=True,
        ):
            counts = None
            manifest = p / "manifest.json"
            if manifest.exists():
                counts = json.loads(manifest.read_text()).get("counts")
            snapshots.append({"id": p.name, "counts": counts})
    return ToolResult(
        tool="list_data_snapshots",
        value={"snapshots": snapshots, "root": str(root)},
        signal={"count": len(snapshots), "root_exists": root.exists()},
    )


_QUERY_TABLES = {"buses", "branches", "generators", "loads"}


@register(
    name="query_grid",
    description="Equality-filtered read against a snapshot table (buses, branches, generators, loads).",
    schema={
        "type": "object",
        "properties": {
            "table": {"type": "string", "enum": sorted(_QUERY_TABLES)},
            "snapshot_id": {"type": "string", "description": "Snapshot bundle ID; omit for newest."},
            "filters": {
                "type": "object",
                "description": "Equality filters; ANDed together. Values may be scalars or arrays.",
            },
            "limit": {"type": "integer", "minimum": 1, "maximum": 5000, "default": 100},
        },
        "required": ["table"],
        "additionalProperties": False,
    },
)
def query_grid(
    table: str,
    snapshot_id: str | None = None,
    filters: dict | None = None,
    limit: int = 100,
) -> ToolResult:
    if table not in _QUERY_TABLES:
        raise ValueError(f"Unknown table {table!r}")
    snapshot = _resolve_snapshot(snapshot_id)
    parquet = snapshot.root / f"{table}.parquet"

    where_clauses: list[str] = []
    params: list = []
    for col, val in (filters or {}).items():
        # Allowlist column names so DuckDB SQL can't be injected via filter keys.
        if not col.replace("_", "").isalnum():
            raise ValueError(f"Invalid filter column: {col!r}")
        if isinstance(val, list):
            placeholders = ", ".join("?" * len(val))
            where_clauses.append(f"{col} IN ({placeholders})")
            params.extend(val)
        else:
            where_clauses.append(f"{col} = ?")
            params.append(val)

    where = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    sql = f"SELECT * FROM read_parquet(?) {where} LIMIT {int(limit)}"
    rows = duckdb.execute(sql, [str(parquet), *params]).fetch_df().to_dict(orient="records")

    return ToolResult(
        tool="query_grid",
        value={"table": table, "snapshot_id": snapshot.root.name, "rows": rows},
        signal={"row_count": len(rows), "truncated": len(rows) == limit},
    )
