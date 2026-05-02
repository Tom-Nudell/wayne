"""Density statistics check (brief §7 step 1).

Reads the bundle's PMTiles archives and emits feature-count-per-layer
per zoom-bracket. Compares to the baseline bundle and alerts on >25%
drift in either direction.

Today: skeleton. Real implementation walks PMTiles directories using
``pmtiles`` (Python port) or by shelling to ``pmtiles show``, counts
features in each tile, buckets by zoom, writes a CSV next to the
report, and compares row counts against ``baseline_dir`` if provided.
"""

from __future__ import annotations

from pathlib import Path

from gridagent_data.qa.models import CheckResult


def check_density(*, bundle_dir: Path, baseline_dir: Path | None) -> CheckResult:
    return CheckResult(
        name="density",
        status="skipped",
        summary="density-stats check not yet implemented (Phase 1)",
        details=[
            f"target: PMTiles archives under {bundle_dir}",
            "baseline: " + (str(baseline_dir) if baseline_dir else "(none)"),
            "alert threshold: >25% drift in feature count per layer per zoom bracket",
        ],
    )
