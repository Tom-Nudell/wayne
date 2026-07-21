"""ENTSO-E Transparency Platform → bronze: European market data.

Token-gated: register (free) on transparency.entsoe.eu, then set
``ENTSOE_API_TOKEN``. Without the token the loader raises with that
instruction rather than fetching a 401. Responses are the platform's
native XML documents, stored verbatim per (zone, document, day) —
parsing belongs to silver.

v1 documents:

  * ``day_ahead_prices``   — documentType A44 (the EU LMP analogue).
  * ``actual_generation``  — documentType A75 / processType A16, actual
    generation per production type.

v1 zones: DE-LU, FR, NL bidding zones (GB market data lives on
BMRS/NESO post-Brexit; add zones by appending to ``ZONES``).

API guide: https://documenter.getpostman.com/view/7009892/2s93JtP3F6
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import httpx

from gridagent_data import paths as _paths
from gridagent_data.provenance import ENTSOE, now_utc

_API_URL = "https://web-api.tp.entsoe.eu/api"


@dataclass(frozen=True)
class EntsoeZone:
    name: str  # bronze path component
    eic: str   # EIC area code


@dataclass(frozen=True)
class EntsoeDocument:
    name: str
    document_type: str
    process_type: str | None = None


ZONES: tuple[EntsoeZone, ...] = (
    EntsoeZone("de_lu", "10Y1001A1001A82H"),
    EntsoeZone("fr", "10YFR-RTE------C"),
    EntsoeZone("nl", "10YNL----------L"),
)

DOCUMENTS: tuple[EntsoeDocument, ...] = (
    EntsoeDocument("day_ahead_prices", "A44"),
    EntsoeDocument("actual_generation", "A75", "A16"),
)


def _token() -> str:
    token = os.environ.get("ENTSOE_API_TOKEN", "").strip()
    if not token:
        raise RuntimeError(
            "ENTSOE_API_TOKEN is not set. Register (free) at "
            "https://transparency.entsoe.eu/ and export the token before "
            "ingesting ENTSO-E data."
        )
    return token


def fetch_day(
    zone: EntsoeZone,
    document: EntsoeDocument,
    day: date,
    *,
    client: httpx.Client | None = None,
    out_dir: Path | None = None,
) -> dict:
    """Fetch one (zone, document, day) XML into bronze."""
    token = _token()
    out_dir = (
        Path(out_dir)
        if out_dir
        else _paths.BRONZE / "entsoe" / zone.name / document.name
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    period_start = f"{day.strftime('%Y%m%d')}0000"
    period_end = f"{(day + timedelta(days=1)).strftime('%Y%m%d')}0000"
    params: dict[str, str] = {
        "securityToken": token,
        "documentType": document.document_type,
        "periodStart": period_start,
        "periodEnd": period_end,
    }
    if document.process_type:
        params["processType"] = document.process_type
    if document.document_type == "A44":
        params["in_Domain"] = zone.eic
        params["out_Domain"] = zone.eic
    else:
        params["in_Domain"] = zone.eic

    own_client = client is None
    client = client or httpx.Client(timeout=120)
    try:
        resp = client.get(_API_URL, params=params)
        resp.raise_for_status()
        payload = resp.text
    finally:
        if own_client:
            client.close()

    out_path = out_dir / f"{document.name}_{day.isoformat()}.xml"
    out_path.write_text(payload)

    manifest = {
        "zone": zone.name,
        "eic": zone.eic,
        "document": document.name,
        "document_type": document.document_type,
        "process_type": document.process_type,
        "day": day.isoformat(),
        "source": {
            "name": ENTSOE.name,
            "url": ENTSOE.url,
            "license": ENTSOE.license,
        },
        "bytes": out_path.stat().st_size,
        "retrieved_at": now_utc().isoformat(),
        "path": str(out_path),
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return manifest
