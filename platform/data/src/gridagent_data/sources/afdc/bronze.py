"""Pull EV charging stations from the NREL AFDC API into bronze.

The Alternative Fuels Data Center (AFDC) is operated by NREL under the
US DOE. Data is US public domain; no export restriction. API access
requires a free key from ``developer.nrel.gov``.

We fetch only ``ELEC`` fuel type (EV charging stations) for v1. The
bronze file is a GeoJSON FeatureCollection with one feature per station;
all AFDC attributes are preserved in ``properties`` so silver/gold models
can select what they need.

Set ``AFDC_API_KEY`` in the environment before calling ``fetch_ev_stations``.
Without a key the API returns a limited demo result — useful for local dev
but not for a national dataset.

API reference:
  https://developer.nrel.gov/docs/transportation/alt-fuel-stations-v1/
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx

from gridagent_data import paths as _paths
from gridagent_data.paths import ensure_dirs

_API_BASE = "https://developer.nrel.gov/api/alt-fuel-stations/v1.json"

# EV stations only; status=E means publicly open.
_DEFAULT_PARAMS: dict[str, str] = {
    "fuel_type": "ELEC",
    "status": "E",
    "country": "US",
    "limit": "10000",  # max per page; we page automatically
}


@dataclass(frozen=True)
class AFDCManifest:
    path: str
    station_count: int
    fetched_at: str
    api_version: str


def _to_feature(station: dict) -> dict | None:
    """Convert one AFDC station dict to a GeoJSON Feature.

    Returns ``None`` if the station has no valid coordinates.
    """
    lat = station.get("latitude")
    lon = station.get("longitude")
    if lat is None or lon is None:
        return None
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return None

    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": station,
    }


def fetch_ev_stations(
    *,
    api_key: str | None = None,
    out_dir: Path | None = None,
) -> AFDCManifest:
    """Fetch all publicly open US EV charging stations from the AFDC API.

    Writes ``bronze/afdc/ev_stations.geojson`` and a companion
    ``manifest.json`` capturing retrieval metadata.

    ``api_key`` defaults to the ``AFDC_API_KEY`` environment variable.
    When neither is set the API falls back to ``DEMO_KEY`` which is
    heavily rate-limited and returns only a small sample.
    """
    key = api_key or os.environ.get("AFDC_API_KEY", "DEMO_KEY")
    out_dir = Path(out_dir) if out_dir else _paths.BRONZE / "afdc"
    ensure_dirs(out_dir)

    features: list[dict] = []
    offset = 0
    page_size = 10000
    api_version: str = ""

    with httpx.Client(timeout=60) as client:
        while True:
            params = {
                **_DEFAULT_PARAMS,
                "api_key": key,
                "offset": str(offset),
                "limit": str(page_size),
            }
            resp = client.get(_API_BASE, params=params)
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", "30"))
                time.sleep(retry_after)
                continue
            resp.raise_for_status()

            body = resp.json()
            if not api_version:
                api_version = body.get("metadata", {}).get("version", "v1")

            stations = body.get("alt_fuel_stations", [])
            for s in stations:
                f = _to_feature(s)
                if f:
                    features.append(f)

            total = int(body.get("total_results", 0))
            offset += len(stations)
            if offset >= total or not stations:
                break

    geojson = {"type": "FeatureCollection", "features": features}
    out_path = out_dir / "ev_stations.geojson"
    out_path.write_text(json.dumps(geojson))

    manifest: dict = {
        "source": "AFDC / NREL DOE",
        "license": "Public Domain",
        "url": "https://developer.nrel.gov/docs/transportation/alt-fuel-stations-v1/",
        "fuel_type": "ELEC",
        "station_count": len(features),
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "api_version": api_version,
        "path": str(out_path),
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))

    return AFDCManifest(
        path=str(out_path),
        station_count=len(features),
        fetched_at=manifest["fetched_at"],
        api_version=api_version,
    )
