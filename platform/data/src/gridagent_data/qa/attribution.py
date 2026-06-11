"""Attribution-presence check (brief §7 step 4).

Verifies that every license sidecar for layers with ``attribution_required``
carries a non-empty ``citation`` string.

This is a data-integrity check against the sidecar files, not a visual
render check. The visual confirmation that attribution is rendered at the
right zoom levels is covered by the visual regression (brief §7 step 3):
the baseline screenshots are taken at the zoom levels each license demands,
so any change that drops attribution from the rendered map will show as a
pixel diff.

Exit behaviour
--------------
``pass``   — all ``attribution_required`` layers have non-empty citations.
``warn``   — a layer has ``attribution_required: true`` but an empty citation
             (acceptable during active development; block before launch).
``fail``   — a layer's sidecar is malformed or cannot be read.
``skipped`` — no license sidecars found in the bundle dir.
"""

from __future__ import annotations

import json
from pathlib import Path

from gridagent_data.qa.models import CheckResult


def check_attribution(*, bundle_dir: Path) -> CheckResult:
    bundle_dir = Path(bundle_dir)
    sidecars = sorted(bundle_dir.glob("*.license.json"))

    if not sidecars:
        return CheckResult(
            name="attribution",
            status="skipped",
            summary="no license sidecars found in bundle dir (run export first)",
            details=[f"searched: {bundle_dir}"],
        )

    fails: list[str] = []
    warns: list[str] = []
    detail_lines: list[str] = []

    for sidecar_path in sidecars:
        layer = sidecar_path.name.removesuffix(".license.json")
        try:
            doc = json.loads(sidecar_path.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            fails.append(layer)
            detail_lines.append(f"{layer}: could not read sidecar ({exc})")
            continue

        licenses: list[dict] = doc.get("licenses", [])
        if not licenses:
            detail_lines.append(f"{layer}: no license entries")
            continue

        for lic in licenses:
            if not lic.get("attribution_required", False):
                continue
            citation = (lic.get("citation") or "").strip()
            spdx = lic.get("spdx", "?")
            if not citation or citation.startswith("License:"):
                # "License: ..." is the fallback placeholder from LICENSE_REGISTRY
                warns.append(f"{layer} ({spdx})")
                detail_lines.append(
                    f"{layer} [{spdx}]: attribution_required but citation is empty/placeholder"
                )
            else:
                detail_lines.append(f"{layer} [{spdx}]: \"{citation}\"")

    if fails:
        return CheckResult(
            name="attribution",
            status="fail",
            summary=f"{len(fails)} sidecar(s) unreadable",
            details=detail_lines,
        )
    if warns:
        return CheckResult(
            name="attribution",
            status="warn",
            summary=f"{len(warns)} layer(s) missing attribution citation",
            details=detail_lines,
        )
    return CheckResult(
        name="attribution",
        status="pass",
        summary=f"all {len(sidecars)} layer(s) have valid attribution",
        details=detail_lines,
    )
