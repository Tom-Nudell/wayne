"""Coverage check (brief §7 step 2).

For layers that should be national (plants, transmission, etc.),
verifies every US state has a non-zero feature count. Flags empty
regions early — most "looks like crap" failures involve a layer
that silently dropped a state because of a CRS mistake or filter
bug upstream.

Today: skeleton. Real implementation queries the gold_atlas mart in
the bundle's DuckDB file, joins features against state polygons, and
returns warn for empty states (or fail if a layer marked
``coverage_required: national`` has any).
"""

from __future__ import annotations

from pathlib import Path

from gridagent_data.qa.models import CheckResult


def check_coverage(*, bundle_dir: Path) -> CheckResult:
    return CheckResult(
        name="coverage",
        status="skipped",
        summary="state-coverage check not yet implemented (Phase 1)",
        details=[
            f"target: bundle.duckdb under {bundle_dir}",
            "rule: every US state has a non-zero feature count for layers tagged national",
        ],
    )
