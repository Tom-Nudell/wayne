"""Conflation diff check (brief §7 step 5).

For layers built from multiple sources (HIFLD vs OSM transmission is
the canonical example), emits a human-readable report of conflicts,
merges, and drops. Requires manual sign-off when unresolved-conflict
row count crosses a threshold.

Today: skeleton. Real implementation reads conflation outputs from
``platform/data``'s build (a per-layer ``conflation_report.json``
emitted by the dbt models or a sibling Python step), summarizes, and
returns ``warn`` over threshold + ``fail`` only if a previously
human-reviewed merge has changed without an updated approval.
"""

from __future__ import annotations

from pathlib import Path

from gridagent_data.qa.models import CheckResult


def check_conflation(*, bundle_dir: Path) -> CheckResult:
    return CheckResult(
        name="conflation",
        status="skipped",
        summary="conflation-diff check not yet implemented (Phase 1)",
        details=[
            f"target: conflation_report.json artifacts under {bundle_dir}",
            "warn threshold: TBD per layer (set in Phase 1 alongside the conflation rules)",
        ],
    )
