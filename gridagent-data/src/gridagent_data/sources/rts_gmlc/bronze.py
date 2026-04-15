"""Pull RTS-GMLC source CSVs into the bronze layer.

The repo publishes hand-edited CSVs at a stable raw-content URL. We pin a
specific commit so snapshot rebuilds are deterministic.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

import httpx

from gridagent_data.paths import BRONZE, ensure_dirs
from gridagent_data.provenance import Source, now_utc

RTS_GMLC = Source(
    name="rts_gmlc",
    url="https://github.com/GridMod/RTS-GMLC",
    license="BSD-3-Clause",
    notes="73-bus three-area test system. Used for first-cut study validation.",
)


@dataclass(frozen=True)
class RtsFile:
    relpath: str
    description: str


# Pin a commit so reruns are reproducible. (Master is fine too; pin for production.)
_COMMIT = "master"
_BASE_URL = f"https://raw.githubusercontent.com/GridMod/RTS-GMLC/{_COMMIT}/RTS_Data/SourceData"

FILES: tuple[RtsFile, ...] = (
    RtsFile(relpath="bus.csv", description="Bus list with lat/lon, base kV, area/zone."),
    RtsFile(relpath="branch.csv", description="Branch list with R/X/B in pu and ratings."),
    RtsFile(relpath="gen.csv", description="Generator list with Pmax/Pmin and fuel."),
)


def fetch_all(*, client: httpx.Client | None = None) -> list[dict]:
    """Download every RTS-GMLC source CSV into bronze. Returns manifests."""
    ensure_dirs()
    target_dir = BRONZE / "rts_gmlc"
    target_dir.mkdir(parents=True, exist_ok=True)

    own_client = client is None
    client = client or httpx.Client(timeout=30.0, follow_redirects=True)
    manifests: list[dict] = []
    try:
        for file in FILES:
            url = f"{_BASE_URL}/{file.relpath}"
            response = client.get(url)
            response.raise_for_status()
            target = target_dir / file.relpath
            target.write_bytes(response.content)
            manifests.append(
                {
                    "file": file.relpath,
                    "description": file.description,
                    "source": asdict(RTS_GMLC),
                    "url": url,
                    "bytes": len(response.content),
                    "retrieved_at": now_utc().isoformat(),
                    "path": str(target.relative_to(BRONZE.parent)),
                }
            )
    finally:
        if own_client:
            client.close()

    (target_dir / "manifest.json").write_text(json.dumps(manifests, indent=2, sort_keys=True))
    return manifests
