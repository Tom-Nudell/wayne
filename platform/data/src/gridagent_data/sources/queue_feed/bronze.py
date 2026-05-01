"""Generic remote CSV feed for interconnection queue projects.

Set ``GRIDAGENT_QUEUE_CSV_URL`` to a provider URL that returns a CSV with
columns expected by the silver model. This avoids manual workbook handling and
lets daily refresh pull queue data automatically.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import re
import csv
from pathlib import Path

import httpx

from gridagent_data import paths as _paths
from gridagent_data.paths import ensure_dirs
from gridagent_data.provenance import now_utc


CSV_HEADERS = [
    "project_id",
    "snapshot_date",
    "iso_region",
    "queue_status",
    "fuel_type",
    "capacity_mw",
    "queue_date",
    "proposed_completion_date",
    "point_of_interconnection",
    "poi_latitude",
    "poi_longitude",
    "source",
    "license",
]


STATE_CENTROIDS = {
    "AL": (32.806671, -86.791130), "AK": (61.370716, -152.404419),
    "AZ": (33.729759, -111.431221), "AR": (34.969704, -92.373123),
    "CA": (36.116203, -119.681564), "CO": (39.059811, -105.311104),
    "CT": (41.597782, -72.755371), "DE": (39.318523, -75.507141),
    "FL": (27.766279, -81.686783), "GA": (33.040619, -83.643074),
    "HI": (21.094318, -157.498337), "ID": (44.240459, -114.478828),
    "IL": (40.349457, -88.986137), "IN": (39.849426, -86.258278),
    "IA": (42.011539, -93.210526), "KS": (38.526600, -96.726486),
    "KY": (37.668140, -84.670067), "LA": (31.169546, -91.867805),
    "ME": (44.693947, -69.381927), "MD": (39.063946, -76.802101),
    "MA": (42.230171, -71.530106), "MI": (43.326618, -84.536095),
    "MN": (45.694454, -93.900192), "MS": (32.741646, -89.678696),
    "MO": (38.456085, -92.288368), "MT": (46.921925, -110.454353),
    "NE": (41.125370, -98.268082), "NV": (38.313515, -117.055374),
    "NH": (43.452492, -71.563896), "NJ": (40.298904, -74.521011),
    "NM": (34.840515, -106.248482), "NY": (42.165726, -74.948051),
    "NC": (35.630066, -79.806419), "ND": (47.528912, -99.784012),
    "OH": (40.388783, -82.764915), "OK": (35.565342, -96.928917),
    "OR": (44.572021, -122.070938), "PA": (40.590752, -77.209755),
    "RI": (41.680893, -71.511780), "SC": (33.856892, -80.945007),
    "SD": (44.299782, -99.438828), "TN": (35.747845, -86.692345),
    "TX": (31.054487, -97.563461), "UT": (40.150032, -111.862434),
    "VT": (44.045876, -72.710686), "VA": (37.769337, -78.169968),
    "WA": (47.400902, -121.490494), "WV": (38.491226, -80.954453),
    "WI": (44.268543, -89.616508), "WY": (42.755966, -107.302490),
    "DC": (38.905985, -77.033418),
}


def _target_path() -> Path:
    return _paths.BRONZE / "queue_feed" / "latest.csv"


def ensure_empty_feed() -> Path:
    """Create a header-only CSV so dbt models always have a readable source."""
    ensure_dirs()
    target = _target_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.write_text(",".join(CSV_HEADERS) + "\n")
    return target


def fetch_csv_feed(url: str | None = None, *, timeout_s: int = 120) -> dict:
    """Download queue CSV feed and write manifest."""
    ensure_dirs()
    target = _target_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    feed_url = url or os.environ.get("GRIDAGENT_QUEUE_CSV_URL", "").strip()
    if not feed_url:
        ensure_empty_feed()
        return {
            "url": "",
            "path": str(target.relative_to(_paths.BRONZE.parent)),
            "bytes": target.stat().st_size,
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "retrieved_at": now_utc().isoformat(),
            "note": "No GRIDAGENT_QUEUE_CSV_URL set; kept header-only feed.",
        }

    resp = httpx.get(feed_url, timeout=timeout_s, follow_redirects=True)
    resp.raise_for_status()
    payload = resp.content
    target.write_bytes(payload)

    manifest = {
        "url": feed_url,
        "path": str(target.relative_to(_paths.BRONZE.parent)),
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "retrieved_at": now_utc().isoformat(),
    }
    (target.parent / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return manifest


def _jittered_lat_lon(state: str, project_id: str) -> tuple[float, float]:
    lat0, lon0 = STATE_CENTROIDS.get(state, (39.5, -98.35))
    seed = int(hashlib.sha256(project_id.encode()).hexdigest()[:8], 16)
    rng = random.Random(seed)
    # Small deterministic jitter so projects are visible as a cloud per state.
    return lat0 + rng.uniform(-0.9, 0.9), lon0 + rng.uniform(-1.2, 1.2)


def fetch_interconnection_fyi_public(*, timeout_s: int = 60) -> dict:
    """Build a queue CSV from interconnection.fyi public state pages.

    Source pages embed project lists in Next.js payload. Coordinates are not
    published, so we assign deterministic jitter around state centroids.
    """
    ensure_dirs()
    target = _target_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    client = httpx.Client(timeout=timeout_s, follow_redirects=True)
    rows: list[list[str]] = []
    total_projects = 0
    for state in sorted(STATE_CENTROIDS):
        url = f"https://interconnection.fyi/projects/state/{state}"
        try:
            resp = client.get(url)
            if resp.status_code == 404:
                continue
            resp.raise_for_status()
            m = re.search(
                r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
                resp.text,
                flags=re.S,
            )
            if not m:
                continue
            data = json.loads(m.group(1))
            projects = data.get("props", {}).get("pageProps", {}).get("projects", [])
            today = now_utc().date().isoformat()
            for p in projects:
                pid = str(p.get("_uniqueId") or f"{state}-{p.get('Queue ID', '')}-{p.get('Project Name', '')}")
                lat, lon = _jittered_lat_lon(state, pid)
                rows.append(
                    [
                        pid,
                        today,
                        str(p.get("Power Market") or state),
                        str(p.get("Status") or ""),
                        "",
                        "",
                        str(p.get("Queue Date") or "")[:10],
                        "",
                        str(p.get("County") or p.get("Project Name") or ""),
                        f"{lat:.6f}",
                        f"{lon:.6f}",
                        "interconnection_fyi_public",
                        "Unknown",
                    ]
                )
            total_projects += len(projects)
        except Exception:
            continue
    client.close()

    with target.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_HEADERS)
        if rows:
            writer.writerows(rows)
    payload = target.read_bytes()
    manifest = {
        "provider": "interconnection_fyi_public",
        "path": str(target.relative_to(_paths.BRONZE.parent)),
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "projects": total_projects,
        "retrieved_at": now_utc().isoformat(),
    }
    (target.parent / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return manifest
