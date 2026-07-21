"""ECB euro foreign exchange reference rates → bronze.

The daily reference-rate XML (free with attribution). Needed the moment
GB/EU market data (GBP/EUR-denominated prices) sits next to USD LMPs.
Stored verbatim; the manifest carries the parsed rate count + date so
silver can sanity-check without re-parsing the envelope.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx

from gridagent_data import paths as _paths
from gridagent_data.provenance import ECB_FX, now_utc

_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
_NS = "{http://www.ecb.int/vocabulary/2002-08-01/eurofxref}"


def fetch_daily_rates(
    *,
    client: httpx.Client | None = None,
    out_dir: Path | None = None,
) -> dict:
    """Fetch the current ECB daily reference rates into bronze."""
    out_dir = Path(out_dir) if out_dir else _paths.BRONZE / "ecb_fx"
    out_dir.mkdir(parents=True, exist_ok=True)

    own_client = client is None
    client = client or httpx.Client(timeout=60, follow_redirects=True)
    try:
        resp = client.get(_URL)
        resp.raise_for_status()
        payload = resp.text
    finally:
        if own_client:
            client.close()

    # Parse just enough for the manifest: the rate date + currency count.
    root = ET.fromstring(payload)
    day_cube = root.find(f"{_NS}Cube/{_NS}Cube")
    rate_date = day_cube.get("time") if day_cube is not None else None
    n_rates = len(day_cube.findall(f"{_NS}Cube")) if day_cube is not None else 0

    out_path = out_dir / f"eurofxref_{rate_date or 'unknown'}.xml"
    out_path.write_text(payload)

    manifest = {
        "rate_date": rate_date,
        "n_currencies": n_rates,
        "source": {
            "name": ECB_FX.name,
            "url": ECB_FX.url,
            "license": ECB_FX.license,
        },
        "bytes": out_path.stat().st_size,
        "retrieved_at": now_utc().isoformat(),
        "path": str(out_path),
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return manifest
