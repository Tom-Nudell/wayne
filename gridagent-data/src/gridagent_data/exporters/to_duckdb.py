"""Export gold marts to a single DuckDB file for in-browser DuckDB-WASM use.

The atlas frontend loads this file over HTTP range requests, which lets us run
SQL filters on the feature catalog with no backend.
"""

from __future__ import annotations

from pathlib import Path


def export(snapshot_dir: Path, out_path: Path) -> Path:
    """Build a portable ``bundle.duckdb`` containing all gold mart tables."""
    raise NotImplementedError("Wired up once at least one gold mart has rows.")
