"""Pull HIFLD archived electricity layers into the bronze layer.

HIFLD is a US-public-domain geospatial catalogue archived in 2022. For
transmission topology and substation geography it remains the canonical
open source. Each layer is a GeoJSON download from the ArcGIS hub.

The layers we ingest:

    * ``electric_substations``   — points with voltage / type / owner
    * ``electric_transmission``  — lines with voltage / owner / length

Silver dbt models normalise voltages, owners and geometry to the
canonical network mart. Layers are pinned by archived URL so rebuilds
remain deterministic even as ArcGIS URL schemes rotate.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass

import httpx

from gridagent_data import paths as _paths
from gridagent_data.paths import ensure_dirs
from gridagent_data.provenance import HIFLD, now_utc


@dataclass(frozen=True)
class HifldLayer:
    name: str
    url: str
    description: str


LAYERS: tuple[HifldLayer, ...] = (
    HifldLayer(
        name="electric_substations",
        url=(
            "https://opendata.arcgis.com/api/v3/datasets/"
            "e68b4d25-7d7b-4c6e-8eec-a8e5dbbb74e3_0/downloads/data?"
            "format=geojson&spatialRefId=4326"
        ),
        description="Electric substations, points, WGS-84.",
    ),
    HifldLayer(
        name="electric_transmission",
        url=(
            "https://opendata.arcgis.com/api/v3/datasets/"
            "d4090758322c4d32a4cd002ffaa0aa12_0/downloads/data?"
            "format=geojson&spatialRefId=4326"
        ),
        description="Electric transmission lines, linestrings, WGS-84.",
    ),
)


def fetch_layer(layer: HifldLayer, *, client: httpx.Client | None = None) -> dict:
    """Download one HIFLD layer GeoJSON to bronze."""
    ensure_dirs()
    target_dir = _paths.BRONZE / "hifld" / layer.name
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{layer.name}.geojson"

    own_client = client is None
    client = client or httpx.Client(
        timeout=httpx.Timeout(60.0, read=600.0), follow_redirects=True
    )

    delays = (0, 2, 5, 10, 20)
    last_error: Exception | None = None
    payload = b""
    etag = ""
    try:
        for delay in delays:
            if delay:
                time.sleep(delay)
            try:
                response = client.get(layer.url)
                if response.status_code in (429, 500, 502, 503, 504):
                    last_error = httpx.HTTPStatusError(
                        f"HTTP {response.status_code}",
                        request=response.request,
                        response=response,
                    )
                    continue
                response.raise_for_status()
                payload = response.content
                etag = response.headers.get("etag", "")
                last_error = None
                break
            except httpx.RequestError as exc:
                last_error = exc
        if last_error is not None:
            raise last_error
    finally:
        if own_client:
            client.close()

    target.write_bytes(payload)

    manifest = {
        "layer": layer.name,
        "description": layer.description,
        "source": asdict(HIFLD),
        "url": layer.url,
        "etag": etag,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "bytes": len(payload),
        "retrieved_at": now_utc().isoformat(),
        "path": str(target.relative_to(_paths.BRONZE.parent)),
    }
    (target_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return manifest
