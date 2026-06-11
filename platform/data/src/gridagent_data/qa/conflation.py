"""Conflation diff check (brief §7 step 5).

For layers assembled from multiple upstream sources (HIFLD vs OSM
transmission is the canonical case), the exporter writes a per-layer
``<kind>.conflation_report.json`` alongside the PMTiles. This check reads
those reports and:

* Reports how many features came from a single source vs. multiple sources.
* Warns when the multi-source fraction exceeds a per-layer threshold — that
  fraction is the "unresolved conflict" bucket where two sources each have a
  candidate and the pipeline merged them without an explicit dedup key.
* The warn threshold is intentionally generous (default 30%) for Phase 1;
  tighten per layer once we understand the real conflict rate.

Exit behaviour
--------------
``pass``   — all layers within threshold (or no conflation reports found).
``warn``   — at least one layer has a multi-source fraction above its threshold.
``fail``   — a previously approved conflation report has *changed* in a way
             that shrinks the single-source fraction by more than 10 pp without
             a new approval on file. (Catches silent regressions in the dedup
             logic.) Not yet wired in Phase 1 — we return ``warn`` in that case
             pending the approval workflow.
"""

from __future__ import annotations

import json
from pathlib import Path

from gridagent_data.qa.models import CheckResult

# Per-layer warn threshold: fraction of features that are multi-source.
# Layers not listed here get the default.
_MULTI_SOURCE_WARN: dict[str, float] = {
    "transmission_line": 0.40,  # HIFLD + OSM overlap is expected to be high
    "substation": 0.30,
    "plant": 0.10,
    "gas_pipeline": 0.30,
    "ev_station": 0.05,  # AFDC is a single source; overlap should be near zero
    "queue_project": 0.10,
}
_DEFAULT_MULTI_SOURCE_WARN = 0.30


def check_conflation(*, bundle_dir: Path) -> CheckResult:
    bundle_dir = Path(bundle_dir)
    reports = sorted(bundle_dir.glob("*.conflation_report.json"))

    if not reports:
        return CheckResult(
            name="conflation",
            status="skipped",
            summary="no conflation reports found in bundle dir (run export first)",
            details=[f"searched: {bundle_dir}"],
        )

    warns: list[str] = []
    detail_lines: list[str] = []

    for report_path in reports:
        kind = report_path.name.removesuffix(".conflation_report.json")
        try:
            report = json.loads(report_path.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            detail_lines.append(f"{kind}: could not read report ({exc})")
            continue

        total = report.get("total_features", 0)
        multi = report.get("multi_source", 0)
        single = report.get("single_source", 0)
        none_ = report.get("no_source", 0)

        if total == 0:
            detail_lines.append(f"{kind}: 0 features — skipping")
            continue

        multi_frac = multi / total
        threshold = _MULTI_SOURCE_WARN.get(kind, _DEFAULT_MULTI_SOURCE_WARN)

        top_combos = report.get("source_breakdown", [])[:3]
        combo_summary = "; ".join(
            f"{e['sources']} ({e['count']:,})" for e in top_combos
        )

        line = (
            f"{kind}: {total:,} total — "
            f"{single:,} single-source, {multi:,} multi-source "
            f"({multi_frac * 100:.1f}%), {none_:,} no-source"
        )
        if combo_summary:
            line += f"\n      top sources: {combo_summary}"
        detail_lines.append(line)

        if multi_frac > threshold:
            warns.append(
                f"{kind}: {multi_frac * 100:.1f}% multi-source "
                f"(threshold {threshold * 100:.0f}%)"
            )

    if warns:
        return CheckResult(
            name="conflation",
            status="warn",
            summary=f"{len(warns)} layer(s) above multi-source threshold — review conflation",
            details=detail_lines,
            artifact_paths=[str(p) for p in reports],
        )

    return CheckResult(
        name="conflation",
        status="pass",
        summary=f"all {len(reports)} layer(s) within multi-source threshold",
        details=detail_lines,
        artifact_paths=[str(p) for p in reports],
    )
