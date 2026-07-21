"""National Grid ESO Carbon Intensity API → bronze (GB, CC-BY-4.0).

Half-hourly GB carbon intensity, forecast + actual + index band, keyless.
One JSON file per day under ``bronze/carbon_intensity/``.

API: https://carbon-intensity.github.io/api-definitions/
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import httpx

from gridagent_data import paths as _paths
from gridagent_data.provenance import NG_ESO_CARBON_INTENSITY, now_utc

_API_BASE = "https://api.carbonintensity.org.uk"


def fetch_day(
    day: date,
    *,
    client: httpx.Client | None = None,
    out_dir: Path | None = None,
) -> dict:
    """Fetch one UTC day of half-hourly GB carbon intensity into bronze."""
    out_dir = Path(out_dir) if out_dir else _paths.BRONZE / "carbon_intensity"
    out_dir.mkdir(parents=True, exist_ok=True)

    own_client = client is None
    client = client or httpx.Client(timeout=60)
    try:
        resp = client.get(f"{_API_BASE}/intensity/date/{day.isoformat()}")
        resp.raise_for_status()
        body = resp.json()
    finally:
        if own_client:
            client.close()

    out_path = out_dir / f"intensity_{day.isoformat()}.json"
    out_path.write_text(json.dumps(body))

    manifest = {
        "day": day.isoformat(),
        "n_periods": len(body.get("data") or []),
        "source": {
            "name": NG_ESO_CARBON_INTENSITY.name,
            "url": NG_ESO_CARBON_INTENSITY.url,
            "license": NG_ESO_CARBON_INTENSITY.license,
        },
        "bytes": out_path.stat().st_size,
        "retrieved_at": now_utc().isoformat(),
        "path": str(out_path),
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return manifest
