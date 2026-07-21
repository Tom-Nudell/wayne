"""Elexon BMRS (Insights Solution API) → bronze: GB market data.

Keyless JSON API under the Elexon Open Data Licence ("contains BSC data
© Elexon Limited" — attribution required). Day-partitioned like the
GridStatus loader: one JSON file per (dataset, day).

v1 datasets:

  * ``generation_actual_per_type`` — AGPT, half-hourly actual generation
    by PSR type (the GB analogue of our EIA-930 fuel-mix mart).
  * ``demand_outturn`` — INDO/ITSDO national demand outturn.

API: https://developer.data.elexon.co.uk/
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import httpx

from gridagent_data import paths as _paths
from gridagent_data.provenance import ELEXON_BMRS, now_utc

_API_BASE = "https://data.elexon.co.uk/bmrs/api/v1"


@dataclass(frozen=True)
class BmrsDataset:
    name: str      # bronze subdirectory
    endpoint: str  # path under the API base
    description: str


DATASETS: tuple[BmrsDataset, ...] = (
    BmrsDataset(
        name="generation_actual_per_type",
        endpoint="generation/actual/per-type",
        description="AGPT — half-hourly actual generation by PSR type.",
    ),
    BmrsDataset(
        name="demand_outturn",
        endpoint="demand/outturn",
        description="INDO — initial national demand outturn per settlement period.",
    ),
)


def fetch_day(
    dataset: BmrsDataset,
    day: date,
    *,
    client: httpx.Client | None = None,
    out_dir: Path | None = None,
) -> dict:
    """Fetch one UTC day of one BMRS dataset into bronze."""
    out_dir = Path(out_dir) if out_dir else _paths.BRONZE / "elexon_bmrs" / dataset.name
    out_dir.mkdir(parents=True, exist_ok=True)

    own_client = client is None
    client = client or httpx.Client(timeout=120)
    try:
        resp = client.get(
            f"{_API_BASE}/{dataset.endpoint}",
            params={
                "from": f"{day.isoformat()}T00:00Z",
                "to": f"{(day + timedelta(days=1)).isoformat()}T00:00Z",
                "format": "json",
            },
        )
        resp.raise_for_status()
        body = resp.json()
    finally:
        if own_client:
            client.close()

    out_path = out_dir / f"{dataset.name}_{day.isoformat()}.json"
    out_path.write_text(json.dumps(body))

    rows = body.get("data") or []
    manifest = {
        "dataset": dataset.name,
        "description": dataset.description,
        "day": day.isoformat(),
        "n_rows": len(rows),
        "source": {
            "name": ELEXON_BMRS.name,
            "url": ELEXON_BMRS.url,
            "license": ELEXON_BMRS.license,
        },
        "attribution": "Contains BSC data © Elexon Limited",
        "bytes": out_path.stat().st_size,
        "retrieved_at": now_utc().isoformat(),
        "path": str(out_path),
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return manifest
