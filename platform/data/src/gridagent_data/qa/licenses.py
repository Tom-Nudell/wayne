"""License-sidecar check (brief §7 step 6).

Walks the bundle's PMTiles archives and verifies each has a matching
``license.json`` sidecar. This is the simplest of the six checks and
the most load-bearing — without sidecars, attribution rendering and
the ``/attribution`` page generator both break.

Convention: ``layer_name.pmtiles`` -> ``layer_name.license.json``.

This check is real today (not a skeleton) — it walks the directory
and reports missing sidecars. Returns ``skipped`` only when no
PMTiles archives are present at all. Returns ``fail`` when archives
exist without sidecars; this is the case during Phase 0 since the
exporter does not yet emit sidecars (Phase 1 work in
``platform/data/.../exporters/to_pmtiles.py``).
"""

from __future__ import annotations

from pathlib import Path

from gridagent_data.qa.models import CheckResult


def check_license_sidecars(*, bundle_dir: Path) -> CheckResult:
    if not bundle_dir.exists():
        return CheckResult(
            name="license_sidecars",
            status="skipped",
            summary=f"bundle dir does not exist: {bundle_dir}",
        )

    pmtiles = sorted(bundle_dir.rglob("*.pmtiles"))
    if not pmtiles:
        return CheckResult(
            name="license_sidecars",
            status="skipped",
            summary="no PMTiles archives found in bundle dir",
            details=[f"searched: {bundle_dir}"],
        )

    missing: list[str] = []
    for archive in pmtiles:
        sidecar = archive.with_suffix(".license.json")
        if not sidecar.exists():
            missing.append(str(archive.relative_to(bundle_dir)))

    if missing:
        return CheckResult(
            name="license_sidecars",
            status="fail",
            summary=f"{len(missing)}/{len(pmtiles)} PMTiles archives missing license.json sidecar",
            details=missing,
        )

    return CheckResult(
        name="license_sidecars",
        status="pass",
        summary=f"all {len(pmtiles)} PMTiles archives have a license.json sidecar",
    )
