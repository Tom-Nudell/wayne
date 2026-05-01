"""Pull OSM power + gas-pipeline features from Overpass into bronze.

Overpass QL returns JSON with separate ``elements`` for nodes, ways and
relations. We request:

* all ``power=*`` objects (nodes/ways/relations), and
* gas pipelines (ways/relations where ``man_made=pipeline`` and
  ``substance=gas``).

Retry policy is conservative — Overpass instances throttle aggressively.
Respect ``Retry-After`` when present and fall back to exponential
backoff otherwise.

Default endpoint is the main Overpass instance; override with
``OVERPASS_URL`` for self-hosted or mirror endpoints.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import asdict, dataclass

import httpx

from gridagent_data import paths as _paths
from gridagent_data.paths import ensure_dirs
from gridagent_data.provenance import OSM, now_utc


@dataclass(frozen=True)
class OverpassRegion:
    name: str
    # ISO 3166-2 code (e.g. "US-TX") or a bbox "south,west,north,east".
    area: str
    description: str = ""


# First vertical slice: three ERCOT-adjacent states. Expand as the
# silver/gold layers absorb OSM features.
REGIONS: tuple[OverpassRegion, ...] = (
    OverpassRegion(name="us_tx", area="US-TX", description="Texas (ERCOT footprint)."),
    OverpassRegion(name="us_ca", area="US-CA", description="California (CAISO footprint)."),
    OverpassRegion(name="us_ny", area="US-NY", description="New York (NYISO footprint)."),
)

_DEFAULT_ENDPOINT = "https://overpass-api.de/api/interpreter"

_QUERY_TEMPLATE = """
[out:json][timeout:180];
area["ISO3166-2"="{iso}"]->.searchArea;
(
  node["power"](area.searchArea);
  way["power"](area.searchArea);
  relation["power"](area.searchArea);
  way["man_made"="pipeline"]["substance"="gas"](area.searchArea);
  relation["man_made"="pipeline"]["substance"="gas"](area.searchArea);
);
out body geom;
"""


def _query_for(region: OverpassRegion) -> str:
    if "," in region.area:
        # bbox form: (south,west,north,east);
        south, west, north, east = region.area.split(",")
        return (
            "[out:json][timeout:180];"
            f"(node[\"power\"]({south},{west},{north},{east});"
            f" way[\"power\"]({south},{west},{north},{east});"
            f" relation[\"power\"]({south},{west},{north},{east});"
            f" way[\"man_made\"=\"pipeline\"][\"substance\"=\"gas\"]({south},{west},{north},{east});"
            f" relation[\"man_made\"=\"pipeline\"][\"substance\"=\"gas\"]({south},{west},{north},{east}););"
            "out body geom;"
        )
    return _QUERY_TEMPLATE.format(iso=region.area)


def fetch_region(
    region: OverpassRegion,
    *,
    client: httpx.Client | None = None,
    endpoint: str | None = None,
) -> dict:
    """Download one OSM region's ``power=*`` features to bronze.

    Returns the manifest dict. Respects Overpass ``Retry-After`` and caps
    a single call at five attempts.
    """
    ensure_dirs()
    target_dir = _paths.BRONZE / "osm" / region.name
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "power.json"

    url = endpoint or os.environ.get("OVERPASS_URL", _DEFAULT_ENDPOINT)
    query = _query_for(region)

    own_client = client is None
    client = client or httpx.Client(
        timeout=httpx.Timeout(30.0, read=900.0), follow_redirects=True
    )

    delays = (0, 5, 15, 30, 60)
    last_error: Exception | None = None
    payload = b""
    try:
        for delay in delays:
            if delay:
                time.sleep(delay)
            try:
                response = client.post(url, data={"data": query})
                if response.status_code in (429, 500, 502, 503, 504):
                    retry_after = response.headers.get("retry-after")
                    if retry_after and retry_after.isdigit():
                        time.sleep(min(int(retry_after), 120))
                    last_error = httpx.HTTPStatusError(
                        f"HTTP {response.status_code}",
                        request=response.request,
                        response=response,
                    )
                    continue
                response.raise_for_status()
                payload = response.content
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

    # Summarise counts without re-parsing for downstream asset metadata.
    try:
        summary = json.loads(payload or b"{}")
        elements = summary.get("elements", []) if isinstance(summary, dict) else []
        by_type: dict[str, int] = {}
        for el in elements:
            by_type[el.get("type", "unknown")] = by_type.get(el.get("type", "unknown"), 0) + 1
    except json.JSONDecodeError:
        by_type = {}

    manifest = {
        "region": region.name,
        "area": region.area,
        "description": region.description,
        "source": asdict(OSM),
        "url": url,
        "query_sha256": hashlib.sha256(query.encode()).hexdigest(),
        "payload_sha256": hashlib.sha256(payload).hexdigest(),
        "bytes": len(payload),
        "element_counts": by_type,
        "retrieved_at": now_utc().isoformat(),
        "path": str(target.relative_to(_paths.BRONZE.parent)),
    }
    (target_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return manifest
