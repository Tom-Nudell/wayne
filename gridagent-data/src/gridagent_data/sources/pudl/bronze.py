"""Pull selected PUDL parquet tables into the bronze layer.

PUDL publishes each table as ``s3://pudl.catalyst.coop/nightly/{table}.parquet``
with corresponding HTTPS access. The bronze layer stores the parquet verbatim,
plus a ``manifest.json`` capturing version, retrieval timestamp, and source URL.

The first vertical slice ships ``core_eia860__scd_generators`` only. To add a
table:

    1. Append it to ``TABLES`` below.
    2. Add a corresponding silver dbt model under ``dbt/models/silver/pudl/``.
    3. Reference it from a gold mart model.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass

import httpx

from gridagent_data.paths import BRONZE, ensure_dirs
from gridagent_data.provenance import PUDL, now_utc


@dataclass(frozen=True)
class PudlTable:
    name: str
    description: str


TABLES: tuple[PudlTable, ...] = (
    PudlTable(
        name="core_eia860__scd_generators",
        description="EIA Form 860 generator-level annual snapshot (slowly changing).",
    ),
    PudlTable(
        name="core_eia860__scd_plants",
        description="EIA Form 860 plant-level annual snapshot with lat/lon and BA.",
    ),
    PudlTable(
        name="core_eia923__monthly_generation",
        description="EIA Form 923 monthly net generation by generator.",
    ),
)

# Stable URL for the nightly build. Pinned releases live under ``v{YYYY.MM.DD}``;
# we default to nightly so the developer experience is "just works", and the
# Dagster asset records the actual SHA256 + timestamp it received.
_BASE_URL = "https://s3.us-west-2.amazonaws.com/pudl.catalyst.coop/nightly"


def fetch_table(table: PudlTable, *, client: httpx.Client | None = None) -> dict:
    """Download a single PUDL parquet table and write it to bronze.

    Returns the manifest dict for inclusion in the asset's metadata.
    """
    ensure_dirs()
    target_dir = BRONZE / "pudl" / table.name
    target_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = target_dir / f"{table.name}.parquet"

    url = f"{_BASE_URL}/{table.name}.parquet"
    own_client = client is None
    client = client or httpx.Client(timeout=httpx.Timeout(60.0, read=600.0), follow_redirects=True)

    # PUDL S3 is intermittently rate-limited; retry with exponential backoff on 5xx/429.
    delays = (0, 2, 5, 10, 20, 30)
    last_error: Exception | None = None
    etag = ""
    content_length = 0
    try:
        for delay in delays:
            if delay:
                time.sleep(delay)
            try:
                with client.stream("GET", url) as response:
                    if response.status_code in (429, 500, 502, 503, 504):
                        response.read()
                        last_error = httpx.HTTPStatusError(
                            f"HTTP {response.status_code}", request=response.request, response=response
                        )
                        continue
                    response.raise_for_status()
                    with parquet_path.open("wb") as fh:
                        for chunk in response.iter_bytes(chunk_size=1 << 20):
                            fh.write(chunk)
                    etag = response.headers.get("etag", "")
                    content_length = int(response.headers.get("content-length", "0") or 0)
                    last_error = None
                    break
            except httpx.RequestError as exc:
                last_error = exc
        if last_error is not None:
            raise last_error
    finally:
        if own_client:
            client.close()

    manifest = {
        "table": table.name,
        "description": table.description,
        "source": asdict(PUDL),
        "url": url,
        "etag": etag,
        "bytes": content_length or parquet_path.stat().st_size,
        "retrieved_at": now_utc().isoformat(),
        "path": str(parquet_path.relative_to(BRONZE.parent)),
    }
    (target_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return manifest
