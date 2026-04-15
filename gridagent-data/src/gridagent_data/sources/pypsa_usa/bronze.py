"""Adopt a PyPSA-USA ``elec.nc`` netCDF into the bronze layer.

Two supported paths:

  * ``adopt_elec_nc(path)`` — copy an existing ``elec.nc`` from anywhere
    on disk into bronze. This is the common case: the user runs
    ``snakemake -c4 results/Default/networks/elec_s_<n>.nc`` in their
    pypsa-usa checkout and hands us the path.

  * ``fetch_elec_nc(url)`` — download a published ``elec.nc`` from a
    mirror URL. Useful when a maintained snapshot is being hosted for
    the team, otherwise the Snakemake path is authoritative.

In both cases bronze stores the netCDF bytes verbatim + a manifest with
SHA-256 and the upstream provenance.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import time
from dataclasses import asdict
from pathlib import Path

import httpx

from gridagent_data import paths as _paths
from gridagent_data.paths import ensure_dirs
from gridagent_data.provenance import PYPSA_USA, now_utc


_BRONZE_DIR = "pypsa_usa"


def _write_manifest(target: Path, *, origin: str, extra: dict) -> dict:
    payload = target.read_bytes() if target.stat().st_size < 5 * 1024 * 1024 * 1024 else None
    # Hash the file via streaming for large netCDFs.
    hasher = hashlib.sha256()
    with target.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            hasher.update(chunk)
    manifest = {
        "source": asdict(PYPSA_USA),
        "origin": origin,
        "sha256": hasher.hexdigest(),
        "bytes": target.stat().st_size,
        "retrieved_at": now_utc().isoformat(),
        "path": str(target.relative_to(_paths.BRONZE.parent)),
        **extra,
    }
    target.with_suffix(target.suffix + ".manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True)
    )
    del payload  # hashing completed via streaming; no need to retain bytes
    return manifest


def adopt_elec_nc(source_path: Path | str, *, label: str = "default") -> dict:
    """Copy ``elec.nc`` from anywhere into bronze and write the manifest."""
    source_path = Path(source_path).resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"elec.nc not found at {source_path}")

    ensure_dirs()
    target_dir = _paths.BRONZE / _BRONZE_DIR / label
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "elec.nc"

    # shutil.copy2 preserves mtime so downstream diff-based caches are honest.
    shutil.copy2(source_path, target)
    return _write_manifest(
        target,
        origin=f"file://{source_path}",
        extra={"label": label, "ingest_mode": "adopt"},
    )


def fetch_elec_nc(
    url: str,
    *,
    label: str = "default",
    client: httpx.Client | None = None,
) -> dict:
    """Download ``elec.nc`` from a mirror URL into bronze."""
    ensure_dirs()
    target_dir = _paths.BRONZE / _BRONZE_DIR / label
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "elec.nc"

    own_client = client is None
    client = client or httpx.Client(
        timeout=httpx.Timeout(60.0, read=1800.0), follow_redirects=True
    )

    delays = (0, 5, 15, 30)
    last_error: Exception | None = None
    try:
        for delay in delays:
            if delay:
                time.sleep(delay)
            try:
                with client.stream("GET", url) as response:
                    if response.status_code in (429, 500, 502, 503, 504):
                        response.read()
                        last_error = httpx.HTTPStatusError(
                            f"HTTP {response.status_code}",
                            request=response.request,
                            response=response,
                        )
                        continue
                    response.raise_for_status()
                    with target.open("wb") as fh:
                        for chunk in response.iter_bytes(chunk_size=1 << 20):
                            fh.write(chunk)
                    last_error = None
                    break
            except httpx.RequestError as exc:
                last_error = exc
        if last_error is not None:
            raise last_error
    finally:
        if own_client:
            client.close()

    return _write_manifest(
        target,
        origin=url,
        extra={"label": label, "ingest_mode": "fetch"},
    )
