"""Baseline management for the visual regression QA check.

Human-approval workflow
-----------------------
Baselines must be explicitly approved by a human before they are used for
comparison. There is no auto-promote path, including on the very first run.

Typical flow
~~~~~~~~~~~~
1. Run the QA gate (or ``gridagent-data qa screenshot``) against a new
   bundle. Because no approved baseline exists the visual check writes
   screenshots to ``{bundle_dir}/pending_screenshots/`` and returns
   ``warn``.

2. A human reviews the screenshots (open the directory in Finder / attach
   to CI artifacts) and decides whether they look correct.

3. If the screenshots are acceptable, run::

       gridagent-data qa approve-baseline \\
           --pending-dir <bundle_dir>/pending_screenshots \\
           --baseline-dir <data_root>/baselines \\
           --message "Initial US national baseline, 2026-05-08"

   This copies the screenshots into the baseline directory and writes
   ``approval.json``. Baselines live at ``data_root/baselines/`` which is
   gitignored — they are local to the machine that runs the pipeline.
   (R2 upload for team sharing is a Phase 2 concern.)

4. On the next QA gate run the visual check finds the approved baseline and
   diffs against it. Runs with >2% pixel delta per viewport require another
   round of human review.

Periodic re-baselining
~~~~~~~~~~~~~~~~~~~~~~
When the map intentionally changes (new layer, style update, data refresh
that adds significant geometry), re-run steps 1–3. The previous approval is
overwritten. ``approval.json`` retains an ``updated_at`` history for audit.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

APPROVAL_FILE = "approval.json"
SCREENSHOTS_DIR = "screenshots"


def baseline_approved(baseline_dir: Path) -> bool:
    """Return True if *baseline_dir* contains a valid approval record."""
    approval_path = Path(baseline_dir) / APPROVAL_FILE
    if not approval_path.exists():
        return False
    try:
        doc = json.loads(approval_path.read_text())
        return bool(doc.get("approved"))
    except (json.JSONDecodeError, OSError):
        return False


def screenshots_dir(baseline_dir: Path) -> Path:
    """Return the path where approved screenshots are stored."""
    return Path(baseline_dir) / SCREENSHOTS_DIR


def read_approval(baseline_dir: Path) -> dict | None:
    """Load the approval record from *baseline_dir*, or None if absent."""
    p = Path(baseline_dir) / APPROVAL_FILE
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def approve_baseline(
    *,
    pending_dir: Path,
    baseline_dir: Path,
    message: str = "",
) -> dict:
    """Promote *pending_dir* screenshots to the approved baseline.

    Copies all ``*.png`` files from *pending_dir* to
    ``{baseline_dir}/screenshots/``, then writes ``approval.json``.

    Returns the approval record dict.

    Raises ``FileNotFoundError`` if *pending_dir* has no PNG files.
    Raises ``ValueError`` if the screenshot set in *pending_dir* is empty.
    """
    pending_dir = Path(pending_dir)
    baseline_dir = Path(baseline_dir)

    pngs = sorted(pending_dir.glob("*.png"))
    if not pngs:
        raise FileNotFoundError(
            f"No PNG screenshots found in {pending_dir}. "
            "Run 'gridagent-data qa screenshot' first."
        )

    dest = screenshots_dir(baseline_dir)
    dest.mkdir(parents=True, exist_ok=True)

    # Remove previous screenshots to avoid stale viewport files
    for old in dest.glob("*.png"):
        old.unlink()

    for src in pngs:
        shutil.copy2(src, dest / src.name)

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # Preserve history of previous approvals for audit
    existing = read_approval(baseline_dir) or {}
    history: list[dict] = existing.get("history", [])
    if existing.get("approved_at"):
        history.append(
            {
                "approved_at": existing["approved_at"],
                "message": existing.get("message", ""),
                "viewport_count": existing.get("viewport_count", 0),
            }
        )

    approval = {
        "approved": True,
        "approved_at": now,
        "message": message,
        "viewport_count": len(pngs),
        "viewports": [p.stem for p in pngs],
        "history": history,
    }

    approval_path = baseline_dir / APPROVAL_FILE
    approval_path.write_text(json.dumps(approval, indent=2))

    return approval
