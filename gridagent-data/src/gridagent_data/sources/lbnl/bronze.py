"""Pull the LBNL ``Queued Up`` annual release into the bronze layer.

LBNL publishes the workbook to ``https://emp.lbl.gov/queues`` with a direct
download URL that changes per year. We pin a default URL (latest release at
the time the loader was written) and allow overriding by env var or CLI.

The bronze artefact is the XLSX bytes + a manifest capturing the URL,
etag, SHA-256, release-year label and retrieval timestamp.
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
from gridagent_data.provenance import LBNL_QUEUED_UP, now_utc


@dataclass(frozen=True)
class QueuedUpRelease:
    year: int
    url: str
    filename: str


# Default pointer — update when a new annual release lands. The URL is
# stable for a given release; LBNL does not redirect old links.
DEFAULT_RELEASE = QueuedUpRelease(
    year=2024,
    url="https://emp.lbl.gov/sites/default/files/2024-04/queued_up_2023_data_file.xlsx",
    filename="queued_up_2023_data_file.xlsx",
)


def fetch_release(
    release: QueuedUpRelease | None = None,
    *,
    client: httpx.Client | None = None,
) -> dict:
    """Download the LBNL Queued Up workbook to bronze.

    Returns the manifest dict. Re-running overwrites bytes and manifest.
    """
    release = release or DEFAULT_RELEASE
    url_override = os.environ.get("GRIDAGENT_LBNL_URL")
    if url_override:
        release = QueuedUpRelease(
            year=release.year,
            url=url_override,
            filename=url_override.rsplit("/", 1)[-1],
        )

    ensure_dirs()
    target_dir = _paths.BRONZE / "lbnl_queued_up" / f"release_{release.year}"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / release.filename

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
                response = client.get(release.url)
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
        "release_year": release.year,
        "source": asdict(LBNL_QUEUED_UP),
        "url": release.url,
        "filename": release.filename,
        "etag": etag,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "bytes": len(payload),
        "retrieved_at": now_utc().isoformat(),
        "path": str(target.relative_to(_paths.BRONZE.parent)),
    }
    (target_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return manifest
