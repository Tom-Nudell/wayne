"""Coverage check (brief §7 step 2).

For layers that should be national (plants, transmission, substations,
gas pipelines), verify every US state has at least one feature. Flags
empty regions early — most "looks like crap" failures involve a layer
silently dropping a state because of a CRS mistake or filter bug
upstream.

State attribution heuristic (no spatial join needed):
  * EIA plants carry an explicit ``state`` property from
    silver_pudl__eia_entity_plants.
  * OSM features carry ``source_file`` pointing at
    ``bronze/osm/us_<iso>/power.json``; we extract the ISO from the
    path.
  * Anything else falls into ``unknown``.

A future revision can add a real point-in-polygon test against
TIGER state boundaries, but the heuristic is sufficient to catch the
"layer dropped half the country" failure modes that motivate this
check today.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from gridagent_data.qa.models import CheckResult

# 50 states + DC. Lowercase ISO 3166-2 (without the "US-" prefix).
_US_STATES: frozenset[str] = frozenset(
    [
        "al", "ak", "az", "ar", "ca", "co", "ct", "dc", "de", "fl",
        "ga", "hi", "id", "il", "in", "ia", "ks", "ky", "la", "me",
        "md", "ma", "mi", "mn", "ms", "mo", "mt", "ne", "nv", "nh",
        "nj", "nm", "ny", "nc", "nd", "oh", "ok", "or", "pa", "ri",
        "sc", "sd", "tn", "tx", "ut", "vt", "va", "wa", "wv", "wi", "wy",
    ]
)

# Layers expected to have national coverage. New "national" layers go here.
_NATIONAL_LAYERS: frozenset[str] = frozenset(
    {"plant", "substation", "transmission_line", "gas_pipeline"}
)

# Lower-cased state name → ISO. Built from a small static map; PUDL
# stores either the abbreviation or the full name depending on era.
_STATE_NAME_TO_ISO: dict[str, str] = {
    "alabama": "al", "alaska": "ak", "arizona": "az", "arkansas": "ar",
    "california": "ca", "colorado": "co", "connecticut": "ct", "delaware": "de",
    "district of columbia": "dc", "florida": "fl", "georgia": "ga",
    "hawaii": "hi", "idaho": "id", "illinois": "il", "indiana": "in",
    "iowa": "ia", "kansas": "ks", "kentucky": "ky", "louisiana": "la",
    "maine": "me", "maryland": "md", "massachusetts": "ma", "michigan": "mi",
    "minnesota": "mn", "mississippi": "ms", "missouri": "mo", "montana": "mt",
    "nebraska": "ne", "nevada": "nv", "new hampshire": "nh", "new jersey": "nj",
    "new mexico": "nm", "new york": "ny", "north carolina": "nc",
    "north dakota": "nd", "ohio": "oh", "oklahoma": "ok", "oregon": "or",
    "pennsylvania": "pa", "rhode island": "ri", "south carolina": "sc",
    "south dakota": "sd", "tennessee": "tn", "texas": "tx", "utah": "ut",
    "vermont": "vt", "virginia": "va", "washington": "wa", "west virginia": "wv",
    "wisconsin": "wi", "wyoming": "wy",
}


_OSM_REGION_RE = re.compile(r"/us_([a-z]{2})/")


def _state_for_feature(props: dict[str, Any]) -> str | None:
    """Best-effort: which US state does this feature belong to?"""
    raw = props.get("state")
    if isinstance(raw, str):
        s = raw.strip().lower()
        if len(s) == 2 and s in _US_STATES:
            return s
        if s in _STATE_NAME_TO_ISO:
            return _STATE_NAME_TO_ISO[s]
    src = props.get("source_file")
    if isinstance(src, str):
        match = _OSM_REGION_RE.search(src)
        if match:
            iso = match.group(1).lower()
            if iso in _US_STATES:
                return iso
    return None


def _states_in_layer(geojson_path: Path) -> tuple[str, set[str], int]:
    """Return (layer_name, states_with_features, total_features)."""
    if not geojson_path.exists() or geojson_path.stat().st_size < 50:
        return geojson_path.stem, set(), 0
    with geojson_path.open() as fh:
        doc = json.load(fh)
    states: set[str] = set()
    features = doc.get("features") if isinstance(doc, dict) else []
    if not isinstance(features, list):
        return geojson_path.stem, set(), 0
    for f in features:
        props = f.get("properties") if isinstance(f, dict) else None
        if not isinstance(props, dict):
            continue
        s = _state_for_feature(props)
        if s is not None:
            states.add(s)
    return geojson_path.stem, states, len(features)


def check_coverage(*, bundle_dir: Path) -> CheckResult:
    if not bundle_dir.exists():
        return CheckResult(
            name="coverage",
            status="skipped",
            summary=f"bundle dir does not exist: {bundle_dir}",
        )

    geojsons = sorted(bundle_dir.rglob("*.geojson"))
    if not geojsons:
        return CheckResult(
            name="coverage",
            status="skipped",
            summary="no GeoJSON intermediates found in bundle dir",
            details=[f"searched: {bundle_dir}"],
        )

    details: list[str] = []
    fails: list[str] = []
    warns: list[str] = []

    for path in geojsons:
        name, states, total = _states_in_layer(path)
        if name not in _NATIONAL_LAYERS:
            continue
        if total == 0:
            details.append(f"{name}: empty (no features at all)")
            continue
        missing = sorted(_US_STATES - states)
        coverage_pct = (len(states) / len(_US_STATES)) * 100
        line = (
            f"{name}: {total:,} features in "
            f"{len(states)}/{len(_US_STATES)} states ({coverage_pct:.0f}%)"
        )
        if missing:
            line += f" — missing: {', '.join(missing)}"
        details.append(line)
        if len(missing) > 25:
            fails.append(f"{name} ({len(missing)} missing)")
        elif len(missing) > 5:
            warns.append(f"{name} ({len(missing)} missing)")

    if fails:
        return CheckResult(
            name="coverage",
            status="fail",
            summary=f"{len(fails)} national layer(s) missing >25 states",
            details=details,
        )
    if warns:
        return CheckResult(
            name="coverage",
            status="warn",
            summary=f"{len(warns)} national layer(s) missing >5 states",
            details=details,
        )
    return CheckResult(
        name="coverage",
        status="pass",
        summary=f"all national layers cover at least 46/{len(_US_STATES)} states",
        details=details,
    )
