"""Smoke tests for the visual QA gate skeleton."""

from __future__ import annotations

from pathlib import Path

from gridagent_data.qa import run_gate
from gridagent_data.qa.licenses import check_license_sidecars


def test_gate_runs_on_empty_bundle_dir(tmp_path: Path) -> None:
    """An empty bundle dir produces six CheckResults, all skipped or pass."""
    report = run_gate(bundle_dir=tmp_path, baseline_dir=None)
    assert len(report.results) == 6
    assert report.overall in {"skipped", "pass"}
    names = {r.name for r in report.results}
    assert names == {
        "density",
        "coverage",
        "visual_regression",
        "attribution",
        "conflation",
        "license_sidecars",
    }


def test_license_sidecar_check_passes_when_all_present(tmp_path: Path) -> None:
    archive = tmp_path / "plants.pmtiles"
    archive.write_bytes(b"\x00")
    sidecar = tmp_path / "plants.license.json"
    sidecar.write_text("{}")
    result = check_license_sidecars(bundle_dir=tmp_path)
    assert result.status == "pass"
    assert "1" in result.summary


def test_license_sidecar_check_fails_when_missing(tmp_path: Path) -> None:
    (tmp_path / "plants.pmtiles").write_bytes(b"\x00")
    (tmp_path / "lines.pmtiles").write_bytes(b"\x00")
    result = check_license_sidecars(bundle_dir=tmp_path)
    assert result.status == "fail"
    assert len(result.details) == 2


def test_license_sidecar_check_skipped_on_empty_dir(tmp_path: Path) -> None:
    result = check_license_sidecars(bundle_dir=tmp_path)
    assert result.status == "skipped"


def test_license_sidecar_check_skipped_on_missing_dir(tmp_path: Path) -> None:
    result = check_license_sidecars(bundle_dir=tmp_path / "nope")
    assert result.status == "skipped"
