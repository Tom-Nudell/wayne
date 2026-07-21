"""Open-Meteo NWP forecasts → bronze.

Open-Meteo (CC-BY-4.0, attribution required) aggregates public NWP models
(GFS, HRRR, ICON, …) behind one keyless API. This is the platform's first
weather source; it feeds renewable capacity-factor context (wind speed at
hub height, irradiance) and demand context (temperature) for study
scenarios and the atlas forecast layers.

v1 fetches hourly forecasts at one representative load-center point per US
ISO. That is deliberately coarse — the "right" points are generation- and
load-weighted centroids per BA, which needs the gold marts to compute. The
point set is a registry, so refining it later is additive.

Bronze output: one JSON file per point per fetch (the API response stored
verbatim) under ``bronze/open_meteo/{point}/``, plus ``manifest.json``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import httpx

from gridagent_data import paths as _paths
from gridagent_data.provenance import OPEN_METEO, now_utc

_API_URL = "https://api.open-meteo.com/v1/forecast"

HOURLY_VARS: tuple[str, ...] = (
    "temperature_2m",       # demand driver
    "wind_speed_100m",      # ~hub height for modern onshore turbines
    "wind_speed_10m",
    "shortwave_radiation",  # GHI proxy for PV output
    "cloud_cover",
)


@dataclass(frozen=True)
class ForecastPoint:
    name: str      # bronze subdirectory
    iso: str       # ISO/RTO this point is meant to represent
    lat: float
    lon: float
    note: str = ""


# One load-center point per ISO for v1; see module docstring for the
# planned refinement to weighted centroids.
FORECAST_POINTS: tuple[ForecastPoint, ...] = (
    ForecastPoint("caiso_los_angeles", "CAISO", 34.05, -118.25),
    ForecastPoint("ercot_dallas", "ERCOT", 32.78, -96.80),
    ForecastPoint("miso_chicago", "MISO", 41.88, -87.63),
    ForecastPoint("nyiso_new_york", "NYISO", 40.71, -74.01),
    ForecastPoint("pjm_philadelphia", "PJM", 39.95, -75.17),
    ForecastPoint("isone_boston", "ISO-NE", 42.36, -71.06),
    ForecastPoint("spp_oklahoma_city", "SPP", 35.47, -97.52),
)


def fetch_forecast(
    point: ForecastPoint,
    *,
    forecast_days: int = 3,
    past_days: int = 1,
    client: httpx.Client | None = None,
    out_dir: Path | None = None,
) -> dict:
    """Fetch the hourly forecast for one point into bronze.

    ``past_days=1`` keeps yesterday's hours in the same file so downstream
    models can splice consecutive fetches without gaps at the seam.
    """
    out_dir = Path(out_dir) if out_dir else _paths.BRONZE / "open_meteo" / point.name
    out_dir.mkdir(parents=True, exist_ok=True)

    own_client = client is None
    client = client or httpx.Client(timeout=60)
    try:
        resp = client.get(
            _API_URL,
            params={
                "latitude": str(point.lat),
                "longitude": str(point.lon),
                "hourly": ",".join(HOURLY_VARS),
                "forecast_days": str(forecast_days),
                "past_days": str(past_days),
                "timezone": "UTC",
            },
        )
        resp.raise_for_status()
        body = resp.json()
    finally:
        if own_client:
            client.close()

    fetched_at = now_utc()
    out_path = out_dir / f"forecast_{fetched_at.strftime('%Y%m%dT%H%M%SZ')}.json"
    out_path.write_text(json.dumps(body))

    n_hours = len((body.get("hourly") or {}).get("time") or [])
    manifest = {
        "point": point.name,
        "iso": point.iso,
        "latitude": point.lat,
        "longitude": point.lon,
        "hourly_vars": list(HOURLY_VARS),
        "n_hours": n_hours,
        "forecast_days": forecast_days,
        "past_days": past_days,
        "source": {
            "name": OPEN_METEO.name,
            "url": OPEN_METEO.url,
            "license": OPEN_METEO.license,
        },
        "bytes": out_path.stat().st_size,
        "retrieved_at": fetched_at.isoformat(),
        "path": str(out_path),
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return manifest
