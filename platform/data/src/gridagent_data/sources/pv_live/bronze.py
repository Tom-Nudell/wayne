"""PV_Live (University of Sheffield) → bronze: GB solar outturn estimates.

Half-hourly estimated GB PV generation. ``gsp_id=0`` is the national
total; per-GSP series use the same endpoint with that GSP's id, so the
loader takes the id as a parameter and v1 pulls national only. Keyless;
attribution required ("PV_Live, University of Sheffield").

API: https://www.solar.sheffield.ac.uk/pvlive/api/
Response shape: ``{"meta": [...column names...], "data": [[...rows...]]}``.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import httpx

from gridagent_data import paths as _paths
from gridagent_data.provenance import PV_LIVE, now_utc

_API_BASE = "https://api.pvlive.uk/pvlive/api/v4"


def fetch_day(
    day: date,
    *,
    gsp_id: int = 0,
    client: httpx.Client | None = None,
    out_dir: Path | None = None,
) -> dict:
    """Fetch one UTC day of half-hourly PV outturn for one GSP into bronze."""
    out_dir = Path(out_dir) if out_dir else _paths.BRONZE / "pv_live" / f"gsp_{gsp_id}"
    out_dir.mkdir(parents=True, exist_ok=True)

    own_client = client is None
    client = client or httpx.Client(timeout=60)
    try:
        resp = client.get(
            f"{_API_BASE}/gsp/{gsp_id}",
            params={
                "start": f"{day.isoformat()}T00:00:00",
                "end": f"{(day + timedelta(days=1)).isoformat()}T00:00:00",
            },
        )
        resp.raise_for_status()
        body = resp.json()
    finally:
        if own_client:
            client.close()

    out_path = out_dir / f"pv_{day.isoformat()}.json"
    out_path.write_text(json.dumps(body))

    manifest = {
        "day": day.isoformat(),
        "gsp_id": gsp_id,
        "columns": body.get("meta"),
        "n_rows": len(body.get("data") or []),
        "source": {
            "name": PV_LIVE.name,
            "url": PV_LIVE.url,
            "license": PV_LIVE.license,
        },
        "bytes": out_path.stat().st_size,
        "retrieved_at": now_utc().isoformat(),
        "path": str(out_path),
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return manifest
