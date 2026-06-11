"""License sidecar emission for PMTiles bundles.

Every PMTiles archive ships with a matching ``<layer>.license.json``.
The frontend reads it to render attribution at the zoom levels each
license demands; the build-time ``/attribution`` page generator
aggregates across all sidecars in a release.

Sidecar shape (per brief §5/§7):

  {
    "layer": "transmission_lines",
    "kind": "transmission_line",
    "feature_count": 229668,
    "generated_at": "2026-05-05T18:00:00Z",
    "licenses": [
      {
        "spdx": "ODbL-1.0",
        "name": "Open Database License v1.0",
        "url": "https://opendatacommons.org/licenses/odbl/1-0/",
        "citation": "© OpenStreetMap contributors",
        "attribution_required": true,
        "feature_count": 229668
      }
    ]
  }

The QA gate's license-sidecar check (``platform/data/.../qa/licenses.py``)
verifies a sidecar exists alongside every PMTiles. This module is the
producer; that module is the consumer.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

import duckdb


@dataclass(frozen=True)
class LicenseEntry:
    spdx: str
    name: str
    url: str
    citation: str
    attribution_required: bool


# Static registry — ground truth for every license string the data
# pipeline can emit. Add a new entry here when ingesting a new source.
LICENSE_REGISTRY: Mapping[str, LicenseEntry] = {
    "ODbL-1.0": LicenseEntry(
        spdx="ODbL-1.0",
        name="Open Database License v1.0",
        url="https://opendatacommons.org/licenses/odbl/1-0/",
        citation="© OpenStreetMap contributors",
        attribution_required=True,
    ),
    "CC-BY-4.0": LicenseEntry(
        spdx="CC-BY-4.0",
        name="Creative Commons Attribution 4.0",
        url="https://creativecommons.org/licenses/by/4.0/",
        # Filled per-row at attribution time; the citation here is the
        # generic placeholder for layers where source attribution is
        # not row-specific.
        citation="See per-source attribution",
        attribution_required=True,
    ),
    "CC-BY-SA-4.0": LicenseEntry(
        spdx="CC-BY-SA-4.0",
        name="Creative Commons Attribution-ShareAlike 4.0",
        url="https://creativecommons.org/licenses/by-sa/4.0/",
        citation="See per-source attribution",
        attribution_required=True,
    ),
    "BSD-3-Clause": LicenseEntry(
        spdx="BSD-3-Clause",
        name="BSD 3-Clause License",
        url="https://opensource.org/license/bsd-3-clause",
        citation="See per-source attribution",
        attribution_required=True,
    ),
    "Public Domain": LicenseEntry(
        spdx="Public-Domain",
        name="Public Domain (US Government work)",
        url="https://www.usa.gov/government-works",
        citation="US Government data",
        attribution_required=False,
    ),
}


def _normalise_spdx(raw: str) -> str:
    """Map common variants to a canonical SPDX-style key."""
    s = raw.strip()
    if not s:
        return "Unknown"
    sl = s.lower()
    if sl in ("public domain", "public-domain", "us-pd", "us public domain"):
        return "Public Domain"
    return s  # already SPDX-ish


def _resolve_license(spdx: str) -> LicenseEntry:
    canonical = _normalise_spdx(spdx)
    if canonical in LICENSE_REGISTRY:
        return LICENSE_REGISTRY[canonical]
    return LicenseEntry(
        spdx=canonical,
        name=canonical,
        url="",
        citation=f"License: {canonical} (no registered metadata)",
        attribution_required=True,
    )


def collect_layer_licenses(
    conn: duckdb.DuckDBPyConnection,
    *,
    warehouse_schema: str,
    warehouse_table: str,
    kind: str,
) -> list[dict]:
    """Aggregate licenses + per-license feature counts for one layer.

    Reads the ``licenses`` array column from ``gold_atlas`` rows of
    the given kind. Flattens the array, groups by SPDX string, joins
    against ``LICENSE_REGISTRY`` for human-readable metadata.
    """
    rows = conn.execute(
        f"""
        WITH per_feature AS (
            SELECT
                COALESCE(unnest(licenses), 'Unknown') AS spdx
            FROM src."{warehouse_schema}"."{warehouse_table}"
            WHERE kind = ?
              AND geometry_wkt IS NOT NULL
        )
        SELECT spdx, count(*) AS n
        FROM per_feature
        GROUP BY spdx
        ORDER BY n DESC
        """,
        [kind],
    ).fetchall()

    out: list[dict] = []
    for spdx, n in rows:
        entry = _resolve_license(str(spdx))
        out.append(
            {
                "spdx": entry.spdx,
                "name": entry.name,
                "url": entry.url,
                "citation": entry.citation,
                "attribution_required": entry.attribution_required,
                "feature_count": int(n),
            }
        )
    return out


def write_sidecar(
    conn: duckdb.DuckDBPyConnection,
    *,
    warehouse_schema: str,
    warehouse_table: str,
    kind: str,
    layer_name: str,
    feature_count: int,
    sidecar_path: Path,
) -> None:
    """Write ``<layer>.license.json`` next to the PMTiles archive.

    ``layer_name`` is the plural form (e.g. ``transmission_lines``)
    matching the PMTiles filename, while ``kind`` is the singular
    discriminator from the mart (e.g. ``transmission_line``).
    """
    licenses = collect_layer_licenses(
        conn,
        warehouse_schema=warehouse_schema,
        warehouse_table=warehouse_table,
        kind=kind,
    )
    sidecar = {
        "layer": layer_name,
        "kind": kind,
        "feature_count": feature_count,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "licenses": licenses,
    }
    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    sidecar_path.write_text(json.dumps(sidecar, indent=2))
