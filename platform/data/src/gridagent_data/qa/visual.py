"""Visual regression check (brief §7 step 3).

Renders N reference viewports against the new bundle and pixel-diffs
against the baseline. Manual review required on >2% delta. Reference
viewports cover: national, ERCOT, PJM, CAISO, NYISO, MISO South,
dense urban, sparse rural — the same set that has bitten us before.

Today: skeleton. Real implementation runs MapLibre via headless
chrome (Puppeteer or Playwright), points at a local preview of the
bundle, captures PNG per viewport per zoom, runs ``pixelmatch`` (or
similar) against ``baseline_dir/screenshots/``, and writes diffs to
``artifact_paths``.
"""

from __future__ import annotations

from pathlib import Path

from gridagent_data.qa.models import CheckResult


def check_visual_regression(
    *, bundle_dir: Path, baseline_dir: Path | None
) -> CheckResult:
    return CheckResult(
        name="visual_regression",
        status="skipped",
        summary="visual regression not yet implemented (Phase 1)",
        details=[
            f"target: {bundle_dir}",
            "baseline: " + (str(baseline_dir) if baseline_dir else "(none)"),
            "viewports: national, ERCOT, PJM, CAISO, NYISO, MISO South, dense urban, sparse rural",
            "manual review required on >2% pixel delta",
        ],
    )
