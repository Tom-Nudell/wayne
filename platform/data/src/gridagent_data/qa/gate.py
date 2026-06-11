"""Orchestrator for the visual QA gate.

Run from the repo root:

    python -m gridagent_data.qa.gate \\
        --bundle-dir data_root/bundle/snapshot_latest

Or with a previous bundle for drift comparison:

    python -m gridagent_data.qa.gate \\
        --bundle-dir data_root/bundle/snapshot_2026-04-30 \\
        --baseline-dir data_root/bundle/snapshot_2026-04-01

Exit codes:
    0 — pass or all skipped (gate is non-blocking)
    2 — at least one check failed (CI should block tile promotion)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable

from gridagent_data.qa.attribution import check_attribution
from gridagent_data.qa.conflation import check_conflation
from gridagent_data.qa.coverage import check_coverage
from gridagent_data.qa.density import check_density
from gridagent_data.qa.licenses import check_license_sidecars
from gridagent_data.qa.models import CheckResult, CheckStatus, GateReport
from gridagent_data.qa.visual import check_visual_regression


def run_gate(
    *,
    bundle_dir: Path,
    baseline_dir: Path | None = None,
    skip: frozenset[str] = frozenset(),
) -> GateReport:
    """Run all six checks against ``bundle_dir`` and return the aggregate report.

    ``skip`` names checks to record as skipped instead of running — for
    fixture bundles (CI code gate) where data-scale checks like national
    coverage are meaningless. Skips are visible in the report, never silent.
    """
    checks: list[tuple[str, Callable[[], CheckResult]]] = [
        ("density", lambda: check_density(bundle_dir=bundle_dir, baseline_dir=baseline_dir)),
        ("coverage", lambda: check_coverage(bundle_dir=bundle_dir)),
        (
            "visual_regression",
            lambda: check_visual_regression(bundle_dir=bundle_dir, baseline_dir=baseline_dir),
        ),
        ("attribution", lambda: check_attribution(bundle_dir=bundle_dir)),
        ("conflation", lambda: check_conflation(bundle_dir=bundle_dir)),
        ("license_sidecars", lambda: check_license_sidecars(bundle_dir=bundle_dir)),
    ]
    results: list[CheckResult] = [
        CheckResult(name=name, status="skipped", summary="skipped via --skip")
        if name in skip
        else fn()
        for name, fn in checks
    ]
    return GateReport(overall=_aggregate(results), results=results)


# pass < skipped < warn < fail. Higher = worse.
_PRIORITY: dict[CheckStatus, int] = {"pass": 0, "skipped": 1, "warn": 2, "fail": 3}


def _aggregate(results: list[CheckResult]) -> CheckStatus:
    if not results:
        return "skipped"
    return max(results, key=lambda r: _PRIORITY[r.status]).status


def _print_summary(report: GateReport) -> None:
    icons = {"pass": "✓", "warn": "!", "fail": "✗", "skipped": "·"}
    print(f"QA gate: {report.overall.upper()}")
    for r in report.results:
        print(f"  [{icons[r.status]}] {r.name}: {r.summary}")
        for d in r.details[:3]:
            print(f"      {d}")
        if len(r.details) > 3:
            print(f"      ... and {len(r.details) - 3} more")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gridagent-qa-gate")
    parser.add_argument(
        "--bundle-dir",
        type=Path,
        required=True,
        help="Bundle output dir to inspect (e.g. data_root/bundle/snapshot_latest)",
    )
    parser.add_argument(
        "--baseline-dir",
        type=Path,
        default=None,
        help="Previous bundle for drift comparison (density + visual checks)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON to stdout instead of the human summary",
    )
    parser.add_argument(
        "--skip",
        action="append",
        default=[],
        choices=[
            "density",
            "coverage",
            "visual_regression",
            "attribution",
            "conflation",
            "license_sidecars",
        ],
        help=(
            "Record this check as skipped instead of running it (repeatable). "
            "For fixture bundles only — never skip checks on a real data build."
        ),
    )
    args = parser.parse_args(argv)

    report = run_gate(
        bundle_dir=args.bundle_dir,
        baseline_dir=args.baseline_dir,
        skip=frozenset(args.skip),
    )

    if args.json:
        sys.stdout.write(report.model_dump_json(indent=2))
        sys.stdout.write("\n")
    else:
        _print_summary(report)

    return 0 if report.overall in {"pass", "skipped"} else 2


if __name__ == "__main__":
    sys.exit(main())
