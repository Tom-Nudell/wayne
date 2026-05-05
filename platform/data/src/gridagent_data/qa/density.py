"""Density statistics check (brief §7 step 1).

Counts features per layer in the bundle's GeoJSON intermediates and
compares against the baseline. Alerts on >25% drift in either
direction. Per-zoom bracketing is deferred until the PMTiles SDK
parsing lands; total-count drift catches the "a layer silently
emptied or doubled" failure mode that motivates this check.

The exporter writes one ``<layer>.geojson`` per kind in the bundle
dir (alongside ``<layer>.pmtiles``). We count from the GeoJSON
because (a) the file is already on disk and (b) feature counting
without parsing every nested geometry is cheap.
"""

from __future__ import annotations

import json
from pathlib import Path

from gridagent_data.qa.models import CheckResult

# Per-layer drift thresholds. Keep symmetric (>25% growth or shrinkage
# triggers the gate) until we tune per-layer based on real history.
_DRIFT_FAIL = 0.25
_DRIFT_WARN = 0.10


def _count_features(geojson_path: Path) -> int:
    """Return the feature count for a GeoJSON FeatureCollection.

    Loads the file fully — fine up to a few hundred MB. For larger
    files swap in ijson streaming.
    """
    if not geojson_path.exists() or geojson_path.stat().st_size < 50:
        return 0
    with geojson_path.open() as fh:
        doc = json.load(fh)
    if isinstance(doc, dict) and isinstance(doc.get("features"), list):
        return len(doc["features"])
    return 0


def _layer_counts(bundle_dir: Path) -> dict[str, int]:
    return {
        p.stem: _count_features(p)
        for p in sorted(bundle_dir.rglob("*.geojson"))
    }


def check_density(*, bundle_dir: Path, baseline_dir: Path | None) -> CheckResult:
    if not bundle_dir.exists():
        return CheckResult(
            name="density",
            status="skipped",
            summary=f"bundle dir does not exist: {bundle_dir}",
        )

    current = _layer_counts(bundle_dir)
    if not current:
        return CheckResult(
            name="density",
            status="skipped",
            summary="no GeoJSON intermediates found in bundle dir",
            details=[f"searched: {bundle_dir}"],
        )

    if baseline_dir is None or not baseline_dir.exists():
        # No baseline → just report counts as a snapshot for the next run.
        details = [f"{name}: {n:,} features" for name, n in current.items()]
        return CheckResult(
            name="density",
            status="pass",
            summary=f"counted {len(current)} layers (no baseline for drift comparison)",
            details=details,
        )

    baseline = _layer_counts(baseline_dir)

    drift_lines: list[str] = []
    fails: list[str] = []
    warns: list[str] = []

    all_layers = sorted(set(current) | set(baseline))
    for name in all_layers:
        cur = current.get(name, 0)
        base = baseline.get(name, 0)
        if base == 0 and cur == 0:
            continue
        if base == 0:
            drift_lines.append(f"{name}: {cur:,} (NEW; was 0 in baseline)")
            warns.append(name)
            continue
        if cur == 0:
            drift_lines.append(f"{name}: 0 features (was {base:,}; layer disappeared)")
            fails.append(name)
            continue
        ratio = cur / base
        delta = (cur - base) / base
        sign = "+" if delta >= 0 else ""
        line = f"{name}: {cur:,} (baseline {base:,}, {sign}{delta * 100:.1f}%)"
        drift_lines.append(line)
        if abs(delta) >= _DRIFT_FAIL:
            fails.append(f"{name}: {ratio:.2f}x")
        elif abs(delta) >= _DRIFT_WARN:
            warns.append(f"{name}: {ratio:.2f}x")

    if fails:
        return CheckResult(
            name="density",
            status="fail",
            summary=f"{len(fails)} layer(s) drifted >{int(_DRIFT_FAIL * 100)}% from baseline",
            details=drift_lines,
        )
    if warns:
        return CheckResult(
            name="density",
            status="warn",
            summary=f"{len(warns)} layer(s) drifted >{int(_DRIFT_WARN * 100)}% from baseline",
            details=drift_lines,
        )
    return CheckResult(
        name="density",
        status="pass",
        summary=f"all {len(all_layers)} layers within ±{int(_DRIFT_WARN * 100)}% of baseline",
        details=drift_lines,
    )
