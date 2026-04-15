"""Data tools: read-only DuckDB queries against a snapshot bundle.

Stubs for now; one tool is implemented end-to-end (``list_data_snapshots``)
so the registry/transport plumbing can be exercised before real data lands.
"""

from __future__ import annotations

import os
from pathlib import Path

from .registry import register
from .result import ToolResult


def _bundle_root() -> Path:
    return Path(os.environ.get("GRIDAGENT_DATA_ROOT", "data_root")) / "bundle"


@register(
    name="list_data_snapshots",
    description="Enumerate available gridagent-data snapshot bundles, newest first.",
    schema={"type": "object", "properties": {}, "additionalProperties": False},
)
def list_data_snapshots() -> ToolResult:
    root = _bundle_root()
    if not root.exists():
        snapshots: list[str] = []
    else:
        snapshots = sorted(
            (p.name for p in root.iterdir() if p.is_dir() and p.name.startswith("snapshot_")),
            reverse=True,
        )
    return ToolResult(
        tool="list_data_snapshots",
        value={"snapshots": snapshots, "root": str(root)},
        signal={"count": len(snapshots), "root_exists": root.exists()},
    )


@register(
    name="query_grid",
    description="Run a parameterised SQL filter over a gold mart table.",
    schema={
        "type": "object",
        "properties": {
            "table": {"type": "string", "description": "Fully-qualified gold mart table."},
            "filters": {"type": "object", "description": "Equality filters; ANDed together."},
            "limit": {"type": "integer", "default": 100},
        },
        "required": ["table"],
        "additionalProperties": False,
    },
)
def query_grid(table: str, filters: dict | None = None, limit: int = 100) -> ToolResult:
    raise NotImplementedError("Wired up once gridagent-data writes a snapshot.")
