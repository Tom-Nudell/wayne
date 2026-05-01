"""Pull GridStatus daily CSV partitions into the bronze layer.

GridStatus exposes per-dataset daily CSV endpoints at
``https://api.gridstatus.io/v1/datasets/{dataset}/query?...``. We pin the
parameters for deterministic snapshot rebuilds: one file per
(dataset, iso, date). The manifest records the dataset, ISO, date window,
retrieved-at timestamp, SHA-256, and exact request URL.

Authentication: set ``GRIDSTATUS_API_KEY`` in the environment; the free
tier is sufficient for historical backfill at the daily cadence we use.
Bronze stores the raw CSV verbatim — no parsing here, that happens in
silver dbt models.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import asdict, dataclass
from datetime import date

import httpx

from gridagent_data import paths as _paths
from gridagent_data.paths import ensure_dirs
from gridagent_data.provenance import GRIDSTATUS, now_utc


ISOS: tuple[str, ...] = ("caiso", "ercot", "miso", "nyiso", "pjm", "isone", "spp")

# The three datasets we bind to gold_market. Each entry is the dataset slug
# that GridStatus publishes; silver models reshape to our canonical schema.
DATASETS: tuple[str, ...] = (
    "lmp_hourly",                # Hub + zonal LMPs, hourly
    "load_hourly",               # Actual load, hourly
    "fuel_mix_hourly",           # Generation by fuel type, hourly
)

_BASE_URL = "https://api.gridstatus.io/v1/datasets"


@dataclass(frozen=True)
class GridStatusPartition:
    dataset: str
    iso: str
    day: date


def _partition_url(part: GridStatusPartition) -> str:
    # ``start_time`` is inclusive, ``end_time`` exclusive — one calendar day.
    return (
        f"{_BASE_URL}/{part.iso}_{part.dataset}/query"
        f"?start_time={part.day.isoformat()}T00:00:00Z"
        f"&end_time={part.day.isoformat()}T24:00:00Z"
        f"&format=csv"
    )


def _partition_path(part: GridStatusPartition) -> str:
    return f"gridstatus/{part.dataset}/iso={part.iso}/date={part.day.isoformat()}.csv"


def fetch_day(
    part: GridStatusPartition,
    *,
    client: httpx.Client | None = None,
    api_key: str | None = None,
) -> dict:
    """Download one (dataset, iso, date) partition to bronze.

    Returns the manifest dict. Safe to re-run: overwrites partition bytes,
    leaves the manifest updated with the new etag/sha256.
    """
    ensure_dirs()
    relpath = _partition_path(part)
    target = _paths.BRONZE / relpath
    target.parent.mkdir(parents=True, exist_ok=True)

    url = _partition_url(part)
    key = api_key or os.environ.get("GRIDSTATUS_API_KEY", "")
    headers = {"x-api-key": key} if key else {}

    own_client = client is None
    client = client or httpx.Client(
        timeout=httpx.Timeout(30.0, read=300.0), follow_redirects=True
    )

    delays = (0, 2, 5, 10)
    last_error: Exception | None = None
    payload = b""
    etag = ""
    try:
        for delay in delays:
            if delay:
                time.sleep(delay)
            try:
                response = client.get(url, headers=headers)
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
        "dataset": part.dataset,
        "iso": part.iso,
        "date": part.day.isoformat(),
        "source": asdict(GRIDSTATUS),
        "url": url,
        "etag": etag,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "bytes": len(payload),
        "retrieved_at": now_utc().isoformat(),
        "path": relpath,
    }
    manifest_path = target.with_suffix(target.suffix + ".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return manifest
