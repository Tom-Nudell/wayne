"""NESO Open Data portal (CKAN) → bronze: GB system data.

NESO (the GB system operator, ex National Grid ESO) publishes on a CKAN
portal under the NESO Open Licence (attribution required). Datasets are
addressed by slug; each carries several resources (current CSV + yearly
archives). The loader resolves the dataset via ``package_show``, picks
the first CSV resource whose name contains ``resource_match`` (falling
back to the first CSV), and stores it verbatim.

v1 datasets:

  * ``embedded-wind-and-solar-forecasts`` — the behind-the-meter wind/PV
    forecast NESO layers into national demand (GB's invisible-generation
    correction; pairs with PV_Live actuals).

API: https://api.neso.energy/api/3/action/…
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import httpx

from gridagent_data import paths as _paths
from gridagent_data.provenance import NESO_OPEN_DATA, now_utc

_API_BASE = "https://api.neso.energy/api/3/action"


@dataclass(frozen=True)
class NesoDataset:
    name: str            # bronze subdirectory
    slug: str            # CKAN package name
    resource_match: str  # substring to select the wanted CSV resource
    description: str


DATASETS: tuple[NesoDataset, ...] = (
    NesoDataset(
        name="embedded_forecast",
        slug="embedded-wind-and-solar-forecasts",
        resource_match="Embedded Solar and Wind Forecast",
        description="Behind-the-meter wind + solar generation forecast (half-hourly).",
    ),
)


def _pick_resource(resources: list[dict], match: str) -> dict | None:
    csvs = [r for r in resources if str(r.get("format", "")).upper() == "CSV"]
    for r in csvs:
        if match.lower() in str(r.get("name", "")).lower():
            return r
    return csvs[0] if csvs else None


def fetch_dataset(
    dataset: NesoDataset,
    *,
    client: httpx.Client | None = None,
    out_dir: Path | None = None,
) -> dict:
    """Resolve a NESO CKAN dataset and pull its matched CSV into bronze."""
    out_dir = Path(out_dir) if out_dir else _paths.BRONZE / "neso" / dataset.name
    out_dir.mkdir(parents=True, exist_ok=True)

    own_client = client is None
    client = client or httpx.Client(timeout=120, follow_redirects=True)
    try:
        resp = client.get(f"{_API_BASE}/package_show", params={"id": dataset.slug})
        resp.raise_for_status()
        package = resp.json()["result"]
        resource = _pick_resource(package.get("resources", []), dataset.resource_match)
        if resource is None:
            raise RuntimeError(
                f"NESO dataset {dataset.slug!r} has no CSV resources to pull"
            )
        data_resp = client.get(resource["url"])
        data_resp.raise_for_status()
        payload = data_resp.content
    finally:
        if own_client:
            client.close()

    out_path = out_dir / f"{dataset.name}.csv"
    out_path.write_bytes(payload)

    manifest = {
        "dataset": dataset.name,
        "slug": dataset.slug,
        "description": dataset.description,
        "resource_id": resource.get("id"),
        "resource_name": resource.get("name"),
        "resource_url": resource.get("url"),
        "source": {
            "name": NESO_OPEN_DATA.name,
            "url": NESO_OPEN_DATA.url,
            "license": NESO_OPEN_DATA.license,
        },
        "bytes": out_path.stat().st_size,
        "retrieved_at": now_utc().isoformat(),
        "path": str(out_path),
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return manifest
