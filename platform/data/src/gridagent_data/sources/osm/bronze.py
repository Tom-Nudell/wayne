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


# All 50 US states + DC. OSM's `power=*` and `man_made=pipeline /
# substance=gas` taggings are the canonical national source for the
# atlas; HIFLD's electric infrastructure dataset is stale and the
# brief defers to OSM for both. Per-region querying keeps each
# Overpass call within the 1024 MB / 180 s caps.
REGIONS: tuple[OverpassRegion, ...] = (
    OverpassRegion(name="us_al", area="US-AL", description="Alabama"),
    OverpassRegion(name="us_ak", area="US-AK", description="Alaska"),
    OverpassRegion(name="us_az", area="US-AZ", description="Arizona"),
    OverpassRegion(name="us_ar", area="US-AR", description="Arkansas"),
    OverpassRegion(name="us_ca", area="US-CA", description="California (CAISO footprint)"),
    OverpassRegion(name="us_co", area="US-CO", description="Colorado"),
    OverpassRegion(name="us_ct", area="US-CT", description="Connecticut"),
    OverpassRegion(name="us_dc", area="US-DC", description="District of Columbia"),
    OverpassRegion(name="us_de", area="US-DE", description="Delaware"),
    OverpassRegion(name="us_fl", area="US-FL", description="Florida"),
    OverpassRegion(name="us_ga", area="US-GA", description="Georgia"),
    OverpassRegion(name="us_hi", area="US-HI", description="Hawaii"),
    OverpassRegion(name="us_id", area="US-ID", description="Idaho"),
    OverpassRegion(name="us_il", area="US-IL", description="Illinois"),
    OverpassRegion(name="us_in", area="US-IN", description="Indiana"),
    OverpassRegion(name="us_ia", area="US-IA", description="Iowa"),
    OverpassRegion(name="us_ks", area="US-KS", description="Kansas"),
    OverpassRegion(name="us_ky", area="US-KY", description="Kentucky"),
    OverpassRegion(name="us_la", area="US-LA", description="Louisiana"),
    OverpassRegion(name="us_me", area="US-ME", description="Maine"),
    OverpassRegion(name="us_md", area="US-MD", description="Maryland"),
    OverpassRegion(name="us_ma", area="US-MA", description="Massachusetts"),
    OverpassRegion(name="us_mi", area="US-MI", description="Michigan"),
    OverpassRegion(name="us_mn", area="US-MN", description="Minnesota"),
    OverpassRegion(name="us_ms", area="US-MS", description="Mississippi"),
    OverpassRegion(name="us_mo", area="US-MO", description="Missouri"),
    OverpassRegion(name="us_mt", area="US-MT", description="Montana"),
    OverpassRegion(name="us_ne", area="US-NE", description="Nebraska"),
    OverpassRegion(name="us_nv", area="US-NV", description="Nevada"),
    OverpassRegion(name="us_nh", area="US-NH", description="New Hampshire"),
    OverpassRegion(name="us_nj", area="US-NJ", description="New Jersey"),
    OverpassRegion(name="us_nm", area="US-NM", description="New Mexico"),
    OverpassRegion(name="us_ny", area="US-NY", description="New York (NYISO footprint)"),
    OverpassRegion(name="us_nc", area="US-NC", description="North Carolina"),
    OverpassRegion(name="us_nd", area="US-ND", description="North Dakota"),
    OverpassRegion(name="us_oh", area="US-OH", description="Ohio"),
    OverpassRegion(name="us_ok", area="US-OK", description="Oklahoma"),
    OverpassRegion(name="us_or", area="US-OR", description="Oregon"),
    OverpassRegion(name="us_pa", area="US-PA", description="Pennsylvania"),
    OverpassRegion(name="us_ri", area="US-RI", description="Rhode Island"),
    OverpassRegion(name="us_sc", area="US-SC", description="South Carolina"),
    OverpassRegion(name="us_sd", area="US-SD", description="South Dakota"),
    OverpassRegion(name="us_tn", area="US-TN", description="Tennessee"),
    OverpassRegion(name="us_tx", area="US-TX", description="Texas (ERCOT footprint)"),
    OverpassRegion(name="us_ut", area="US-UT", description="Utah"),
    OverpassRegion(name="us_vt", area="US-VT", description="Vermont"),
    OverpassRegion(name="us_va", area="US-VA", description="Virginia"),
    OverpassRegion(name="us_wa", area="US-WA", description="Washington"),
    OverpassRegion(name="us_wv", area="US-WV", description="West Virginia"),
    OverpassRegion(name="us_wi", area="US-WI", description="Wisconsin"),
    OverpassRegion(name="us_wy", area="US-WY", description="Wyoming"),
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


def _write_parquet(target_dir: "_paths.Path", region: str, json_path: "_paths.Path") -> None:
    """Convert one state's bronze JSON to a sibling ``elements.parquet``.

    The dbt silver layer reads the parquet, not the JSON — parsing 3 GB
    of bronze JSON per dbt run OOMs on a 32 GB box. Per-state parquet
    pre-conversion keeps memory bounded (each call uses ~6 GB peak)
    and is dramatically faster on subsequent reads. The original JSON
    stays on disk as the immutable bronze artifact.
    """
    try:
        import duckdb
    except ImportError:  # pragma: no cover — duckdb is a hard dep of platform/data.
        return

    parquet_path = target_dir / "elements.parquet"
    con = duckdb.connect(":memory:")
    try:
        # 16 GB peak handles California (549 MB JSON, the biggest state).
        # Tune via OSM_PARQUET_MEMORY_LIMIT for low-RAM envs.
        con.execute(
            f"SET memory_limit='{os.environ.get('OSM_PARQUET_MEMORY_LIMIT', '16GB')}'"
        )
        con.execute("SET preserve_insertion_order=false")
        con.execute(
            f"""
            COPY (
                select
                    '{region}' as region,
                    src.filename as source_file,
                    u.unnest as element
                from read_json_auto(
                    '{json_path}',
                    maximum_object_size = 1073741824,
                    filename = true
                ) src,
                unnest(src.elements) u
            )
            TO '{parquet_path}'
            (FORMAT PARQUET, COMPRESSION ZSTD)
            """
        )
    finally:
        con.close()


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
    # Overpass main rejects requests with httpx's default User-Agent
    # (returns 406 Not Acceptable). Identify ourselves explicitly per
    # OSM API etiquette.
    client = client or httpx.Client(
        timeout=httpx.Timeout(30.0, read=900.0),
        follow_redirects=True,
        headers={"User-Agent": "wayne-gridagent/0.1 (+https://github.com/Tom-Nudell/wayne)"},
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
    _write_parquet(target_dir, region.name, target)

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
