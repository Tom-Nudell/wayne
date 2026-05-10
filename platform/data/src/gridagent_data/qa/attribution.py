"""Attribution-presence check (brief §7 step 4).

Verifies every license-required attribution string is present and
readable at the zoom levels its license demands. Drives the
``/attribution`` page generation and the per-zoom in-map attribution.

Today: skeleton. Real implementation reads each layer's
``license.json`` sidecar, looks up its required attribution and zoom
range, then renders the map at those zooms and OCRs (or DOM-checks)
that the string is in the rendered output.
"""

from __future__ import annotations

from pathlib import Path

from gridagent_data.qa.models import CheckResult


def check_attribution(*, bundle_dir: Path) -> CheckResult:
    return CheckResult(
        name="attribution",
        status="skipped",
        summary="attribution-presence check not yet implemented (Phase 1)",
        details=[
            f"target: license.json sidecars under {bundle_dir}",
            "rule: every license-required attribution is rendered at the zooms its license demands",
        ],
    )
