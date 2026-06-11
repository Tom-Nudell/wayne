"""Visual regression check (brief §7 step 3).

Renders N reference viewports against the new bundle using Playwright
(headless Chromium + MapLibre), then pixel-diffs each screenshot against
the approved baseline. Manual review is required on >2% delta per viewport.

Reference viewports
-------------------
national       [-98.5, 39.5]  z4   — full US overview
ercot          [-99.0, 31.0]  z6   — Texas grid
pjm            [-77.0, 39.5]  z6   — Mid-Atlantic/Midwest
caiso          [-119.5, 36.5] z6   — California
nyiso          [-74.0, 42.0]  z7   — New York
miso_south     [-90.5, 33.0]  z6   — MISO South
urban_chicago  [-87.63, 41.85] z11 — dense urban (transmission density)
rural_montana  [-109.5, 46.9] z8   — sparse rural (coverage check)

Human-approval baseline workflow
---------------------------------
Baselines must be explicitly approved; see ``gridagent_data.qa.baseline``.

* No approved baseline → screenshots are written to
  ``{bundle_dir}/pending_screenshots/`` and the check returns ``warn``
  with instructions.
* Approved baseline present → diff each screenshot; ``warn`` if any
  viewport exceeds 2%, ``pass`` otherwise.

Dependencies
------------
Requires the ``qa`` optional extra::

    uv pip install -e '.[qa]'
    playwright install chromium

If ``playwright`` is not importable the check returns ``skipped`` so
regular CI (which doesn't install qa extras) is not blocked.
"""

from __future__ import annotations

import threading
import time
import urllib.parse
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

from gridagent_data.qa.baseline import baseline_approved, screenshots_dir
from gridagent_data.qa.models import CheckResult

# Pixel-delta threshold per viewport. Viewports above this need review.
_WARN_THRESHOLD = 0.02  # 2 %

# Reference viewports: (name, [lng, lat], zoom, layer_names)
_VIEWPORTS: list[tuple[str, list[float], int, list[str]]] = [
    ("national",      [-98.5,  39.5],  4,  ["transmission_lines", "plants"]),
    ("ercot",         [-99.0,  31.0],  6,  ["transmission_lines", "plants", "substations"]),
    ("pjm",           [-77.0,  39.5],  6,  ["transmission_lines", "plants", "substations"]),
    ("caiso",         [-119.5, 36.5],  6,  ["transmission_lines", "plants", "substations"]),
    ("nyiso",         [-74.0,  42.0],  7,  ["transmission_lines", "plants", "substations"]),
    ("miso_south",    [-90.5,  33.0],  6,  ["transmission_lines", "plants"]),
    ("urban_chicago", [-87.63, 41.85], 11, ["transmission_lines", "substations"]),
    ("rural_montana", [-109.5, 46.9],  8,  ["transmission_lines", "plants"]),
]

_VIEWER_HTML = Path(__file__).parent.parent.parent.parent.parent / (
    "tests/qa/viewer/index.html"
)


# ---------------------------------------------------------------------------
# Local HTTP server helpers
# ---------------------------------------------------------------------------

class _SilentHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args: object) -> None:  # noqa: D401
        pass  # suppress per-request noise in test output


def _start_tile_server(directory: Path, port: int) -> HTTPServer:
    """Serve *directory* on *port* in a background thread."""
    server = HTTPServer(
        ("127.0.0.1", port),
        lambda *a: _SilentHandler(*a, directory=str(directory)),
    )
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server


def _start_viewer_server(port: int) -> HTTPServer:
    """Serve the viewer HTML directory on *port*."""
    return _start_tile_server(_VIEWER_HTML.parent, port)


# ---------------------------------------------------------------------------
# Screenshot capture
# ---------------------------------------------------------------------------

def capture_screenshots(
    bundle_dir: Path,
    out_dir: Path,
    *,
    tile_port: int = 8765,
    viewer_port: int = 8766,
) -> list[Path]:
    """Render each reference viewport and write PNGs to *out_dir*.

    Raises ``ImportError`` if playwright or Pillow are not installed.
    Returns a list of paths to the written PNG files.
    """
    from playwright.sync_api import sync_playwright  # noqa: PLC0415

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    tile_srv = _start_tile_server(bundle_dir, tile_port)
    viewer_srv = _start_viewer_server(viewer_port)
    time.sleep(0.3)  # let servers bind

    paths: list[Path] = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                args=["--no-sandbox", "--disable-setuid-sandbox"]
            )
            ctx = browser.new_context(
                viewport={"width": 1280, "height": 800},
                device_scale_factor=1,
            )
            page = ctx.new_page()

            for name, center, zoom, layers in _VIEWPORTS:
                qs = urllib.parse.urlencode(
                    {
                        "tile_base": f"http://127.0.0.1:{tile_port}",
                        "center": f"[{center[0]},{center[1]}]",
                        "zoom": zoom,
                        "layers": ",".join(layers),
                    }
                )
                url = f"http://127.0.0.1:{viewer_port}/index.html?{qs}"
                page.goto(url)
                # Wait for the map's 'idle' event (data-ready attr) or an error.
                page.wait_for_function(
                    "document.body.hasAttribute('data-ready') || "
                    "document.body.hasAttribute('data-error')",
                    timeout=30_000,
                )
                out_path = out_dir / f"{name}.png"
                page.screenshot(path=str(out_path), full_page=False)
                paths.append(out_path)

            ctx.close()
            browser.close()
    finally:
        tile_srv.shutdown()
        viewer_srv.shutdown()

    return paths


# ---------------------------------------------------------------------------
# Pixel diff
# ---------------------------------------------------------------------------

def _pixel_delta(path_a: Path, path_b: Path) -> float:
    """Return the fraction of pixels that differ between two PNGs.

    Uses a tolerance of 5/255 per channel to ignore JPEG-style noise.
    """
    from PIL import Image, ImageChops  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415

    img_a = Image.open(path_a).convert("RGB")
    img_b = Image.open(path_b).convert("RGB")

    if img_a.size != img_b.size:
        # Size mismatch is itself a regression signal; treat all pixels as changed.
        return 1.0

    diff = ImageChops.difference(img_a, img_b)
    arr = np.asarray(diff, dtype=np.uint8)
    total = arr.shape[0] * arr.shape[1]
    changed = int(np.sum(np.any(arr > 5, axis=2)))
    return changed / total if total > 0 else 0.0


# ---------------------------------------------------------------------------
# Main check
# ---------------------------------------------------------------------------

def check_visual_regression(
    *, bundle_dir: Path, baseline_dir: Path | None
) -> CheckResult:
    bundle_dir = Path(bundle_dir)

    # Fast-path: no PMTiles in the bundle means nothing to render.
    if not any(bundle_dir.glob("*.pmtiles")):
        return CheckResult(
            name="visual_regression",
            status="skipped",
            summary="no PMTiles found in bundle dir — skipping visual check",
            details=[f"searched: {bundle_dir}"],
        )

    # Guard: playwright must be importable.
    try:
        import playwright  # noqa: F401, PLC0415
        import PIL  # noqa: F401, PLC0415
        import numpy  # noqa: F401, PLC0415
    except ImportError as exc:
        return CheckResult(
            name="visual_regression",
            status="skipped",
            summary=f"qa dependencies not installed ({exc}); run: uv pip install -e '.[qa]' && playwright install chromium",
        )

    # If no approved baseline: capture screenshots for human review.
    effective_baseline = Path(baseline_dir) if baseline_dir else None
    if effective_baseline is None or not baseline_approved(effective_baseline):
        pending_dir = bundle_dir / "pending_screenshots"
        try:
            paths = capture_screenshots(bundle_dir, pending_dir)
        except Exception as exc:  # noqa: BLE001
            return CheckResult(
                name="visual_regression",
                status="warn",
                summary=f"screenshot capture failed: {exc}",
                details=[
                    "Fix the error above, then run:",
                    "  gridagent-data qa screenshot --bundle-dir <dir>",
                    "  gridagent-data qa approve-baseline --pending-dir <dir>/pending_screenshots",
                ],
            )
        return CheckResult(
            name="visual_regression",
            status="warn",
            summary=(
                f"{len(paths)} viewport screenshot(s) captured — "
                "human review required before baseline is approved"
            ),
            details=[
                f"Screenshots written to: {pending_dir}",
                "Review each PNG, then run:",
                f"  gridagent-data qa approve-baseline "
                f"    --pending-dir {pending_dir} "
                f"    --message 'describe the change'",
            ],
            artifact_paths=[str(p) for p in paths],
        )

    # Approved baseline present — take fresh screenshots and diff.
    fresh_dir = bundle_dir / "qa_screenshots"
    try:
        fresh_paths = capture_screenshots(bundle_dir, fresh_dir)
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            name="visual_regression",
            status="fail",
            summary=f"screenshot capture failed: {exc}",
        )

    baseline_screens = screenshots_dir(effective_baseline)
    delta_lines: list[str] = []
    review_needed: list[str] = []
    artifact_paths: list[str] = []

    for fresh_path in fresh_paths:
        name = fresh_path.stem
        baseline_path = baseline_screens / f"{name}.png"
        artifact_paths.append(str(fresh_path))

        if not baseline_path.exists():
            delta_lines.append(f"{name}: no baseline screenshot — treating as new viewport")
            review_needed.append(name)
            continue

        try:
            delta = _pixel_delta(baseline_path, fresh_path)
        except Exception as exc:  # noqa: BLE001
            delta_lines.append(f"{name}: diff failed ({exc})")
            review_needed.append(name)
            continue

        sign = " ✓" if delta <= _WARN_THRESHOLD else " !"
        delta_lines.append(f"{name}: {delta * 100:.2f}% pixel delta{sign}")
        if delta > _WARN_THRESHOLD:
            review_needed.append(name)

    if review_needed:
        return CheckResult(
            name="visual_regression",
            status="warn",
            summary=(
                f"{len(review_needed)}/{len(fresh_paths)} viewport(s) "
                f"exceed {_WARN_THRESHOLD * 100:.0f}% delta — manual review required"
            ),
            details=delta_lines + [
                "",
                "If the changes are intentional, approve a new baseline:",
                f"  gridagent-data qa approve-baseline "
                f"    --pending-dir {fresh_dir} "
                f"    --baseline-dir {effective_baseline} "
                f"    --message 'describe the change'",
            ],
            artifact_paths=artifact_paths,
        )

    return CheckResult(
        name="visual_regression",
        status="pass",
        summary=(
            f"all {len(fresh_paths)} viewport(s) within "
            f"{_WARN_THRESHOLD * 100:.0f}% pixel delta"
        ),
        details=delta_lines,
        artifact_paths=artifact_paths,
    )
