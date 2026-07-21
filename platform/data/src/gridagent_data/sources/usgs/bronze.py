"""USGS renewable asset registries: USWTDB (wind) + USPVDB (solar) → bronze.

Both databases are US public domain and served from the same PostgREST API
at ``energy.usgs.gov`` (note: the older ``eersc.usgs.gov`` host 301s here):

  * USWTDB — one row per **wind turbine** (~76k): location, manufacturer,
    model, hub height, rotor diameter, capacity, plus ``eia_id`` which joins
    to the EIA-860 plant registry we already carry via PUDL.
  * USPVDB — one row per **large-scale PV facility**: location, footprint
    area, axis/tilt, AC/DC capacity, also ``eia_id``-keyed.

These are finer-grained than EIA-860 (per-turbine / per-array vs per-plant)
and are the geometry source for individual-asset rendering on the atlas.

Bronze output: one GeoJSON FeatureCollection per dataset with every API
attribute preserved in ``properties``, plus the usual ``manifest.json``.
Paging is PostgREST ``limit``/``offset``; we stop on the first short page.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import httpx

from gridagent_data import paths as _paths
from gridagent_data.provenance import USGS_USPVDB, USGS_USWTDB, Source, now_utc

_API_BASE = "https://energy.usgs.gov/api"
_PAGE_SIZE = 5000


@dataclass(frozen=True)
class UsgsDataset:
    name: str          # bronze subdirectory + file stem
    endpoint: str      # path under the API base
    source: Source
    description: str


DATASETS: tuple[UsgsDataset, ...] = (
    UsgsDataset(
        name="uswtdb_turbines",
        endpoint="uswtdb/v1/turbines",
        source=USGS_USWTDB,
        description="US Wind Turbine Database — one feature per turbine.",
    ),
    UsgsDataset(
        name="uspvdb_projects",
        endpoint="uspvdb/v1/projects",
        source=USGS_USPVDB,
        description="US Large-Scale Solar PV Database — one feature per facility.",
    ),
)


def _to_feature(row: dict) -> dict | None:
    """One API row → GeoJSON Feature. Rows without coordinates are dropped."""
    lon, lat = row.get("xlong"), row.get("ylat")
    if lon is None or lat is None:
        return None
    try:
        lon, lat = float(lon), float(lat)
    except (TypeError, ValueError):
        return None
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": row,
    }


def fetch_dataset(
    dataset: UsgsDataset,
    *,
    client: httpx.Client | None = None,
    out_dir: Path | None = None,
) -> dict:
    """Fetch one USGS dataset into bronze. Returns the manifest dict."""
    out_dir = Path(out_dir) if out_dir else _paths.BRONZE / "usgs" / dataset.name
    out_dir.mkdir(parents=True, exist_ok=True)

    own_client = client is None
    client = client or httpx.Client(timeout=120, follow_redirects=True)

    features: list[dict] = []
    dropped = 0
    offset = 0
    try:
        while True:
            resp = client.get(
                f"{_API_BASE}/{dataset.endpoint}",
                params={"limit": str(_PAGE_SIZE), "offset": str(offset)},
            )
            resp.raise_for_status()
            rows = resp.json()
            for row in rows:
                f = _to_feature(row)
                if f is None:
                    dropped += 1
                else:
                    features.append(f)
            offset += len(rows)
            if len(rows) < _PAGE_SIZE:
                break
    finally:
        if own_client:
            client.close()

    out_path = out_dir / f"{dataset.name}.geojson"
    out_path.write_text(
        json.dumps({"type": "FeatureCollection", "features": features})
    )

    manifest = {
        "dataset": dataset.name,
        "description": dataset.description,
        "source": {
            "name": dataset.source.name,
            "url": dataset.source.url,
            "license": dataset.source.license,
        },
        "api": f"{_API_BASE}/{dataset.endpoint}",
        "feature_count": len(features),
        "dropped_no_coords": dropped,
        "bytes": out_path.stat().st_size,
        "retrieved_at": now_utc().isoformat(),
        "path": str(out_path),
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return manifest
