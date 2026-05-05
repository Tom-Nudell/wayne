"""Filesystem layout for the ETL.

All paths are derived from one root directory. The default lives next to the
package for local dev; in deployed environments override with
``GRIDAGENT_DATA_ROOT``.
"""

from __future__ import annotations

import os
from pathlib import Path

# `__file__` is at platform/data/src/gridagent_data/paths.py; parents[4]
# resolves to the wayne/ repo root so data_root/ sits alongside platform/.
_DEFAULT_ROOT = Path(__file__).resolve().parents[4] / "data_root"

DATA_ROOT = Path(os.environ.get("GRIDAGENT_DATA_ROOT", _DEFAULT_ROOT))

BRONZE = DATA_ROOT / "bronze"
SILVER = DATA_ROOT / "silver"
GOLD = DATA_ROOT / "gold"
BUNDLE = DATA_ROOT / "bundle"
WAREHOUSE = DATA_ROOT / "warehouse.duckdb"


def ensure_dirs() -> None:
    """Create all expected directories. Cheap; safe to call repeatedly."""
    for p in (BRONZE, SILVER, GOLD, BUNDLE):
        p.mkdir(parents=True, exist_ok=True)
