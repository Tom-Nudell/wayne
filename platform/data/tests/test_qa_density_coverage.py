"""Tests for density + coverage QA checks (brief §7 steps 1 + 2)."""

from __future__ import annotations

import json
from pathlib import Path

from gridagent_data.qa.coverage import check_coverage
from gridagent_data.qa.density import check_density


def _write_features(path: Path, features: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}))


def _osm_feature(state_iso: str, **props: object) -> dict:
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [0.0, 0.0]},
        "properties": {
            "kind": "substation",
            "source_file": f"/abs/data_root/bronze/osm/us_{state_iso}/power.json",
            **props,
        },
    }


def _eia_plant(state_iso: str) -> dict:
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [0.0, 0.0]},
        "properties": {"kind": "plant", "state": state_iso.upper()},
    }


# ---- density ----------------------------------------------------------------


def test_density_skipped_on_empty_dir(tmp_path: Path) -> None:
    r = check_density(bundle_dir=tmp_path, baseline_dir=None)
    assert r.status == "skipped"


def test_density_pass_no_baseline(tmp_path: Path) -> None:
    _write_features(tmp_path / "plant.geojson", [_eia_plant("ca")])
    r = check_density(bundle_dir=tmp_path, baseline_dir=None)
    assert r.status == "pass"
    assert "no baseline" in r.summary


def test_density_pass_within_baseline(tmp_path: Path) -> None:
    base = tmp_path / "base"
    cur = tmp_path / "cur"
    _write_features(base / "plant.geojson", [_eia_plant("ca") for _ in range(100)])
    _write_features(cur / "plant.geojson", [_eia_plant("ca") for _ in range(105)])
    r = check_density(bundle_dir=cur, baseline_dir=base)
    assert r.status == "pass"


def test_density_warn_on_moderate_drift(tmp_path: Path) -> None:
    base = tmp_path / "base"
    cur = tmp_path / "cur"
    _write_features(base / "plant.geojson", [_eia_plant("ca") for _ in range(100)])
    _write_features(cur / "plant.geojson", [_eia_plant("ca") for _ in range(115)])  # +15%
    r = check_density(bundle_dir=cur, baseline_dir=base)
    assert r.status == "warn"


def test_density_fail_on_disappearance(tmp_path: Path) -> None:
    base = tmp_path / "base"
    cur = tmp_path / "cur"
    _write_features(base / "plant.geojson", [_eia_plant("ca") for _ in range(100)])
    _write_features(cur / "plant.geojson", [])  # layer empty
    r = check_density(bundle_dir=cur, baseline_dir=base)
    assert r.status == "fail"


def test_density_fail_on_30pct_growth(tmp_path: Path) -> None:
    base = tmp_path / "base"
    cur = tmp_path / "cur"
    _write_features(base / "plant.geojson", [_eia_plant("ca") for _ in range(100)])
    _write_features(cur / "plant.geojson", [_eia_plant("ca") for _ in range(140)])  # +40%
    r = check_density(bundle_dir=cur, baseline_dir=base)
    assert r.status == "fail"


# ---- coverage ---------------------------------------------------------------


def test_coverage_skipped_on_empty_dir(tmp_path: Path) -> None:
    r = check_coverage(bundle_dir=tmp_path)
    assert r.status == "skipped"


def test_coverage_pass_full_national(tmp_path: Path) -> None:
    states = [
        "al", "ak", "az", "ar", "ca", "co", "ct", "dc", "de", "fl",
        "ga", "hi", "id", "il", "in", "ia", "ks", "ky", "la", "me",
        "md", "ma", "mi", "mn", "ms", "mo", "mt", "ne", "nv", "nh",
        "nj", "nm", "ny", "nc", "nd", "oh", "ok", "or", "pa", "ri",
        "sc", "sd", "tn", "tx", "ut", "vt", "va", "wa", "wv", "wi", "wy",
    ]
    _write_features(
        tmp_path / "substation.geojson",
        [_osm_feature(s) for s in states],
    )
    r = check_coverage(bundle_dir=tmp_path)
    assert r.status == "pass"


def test_coverage_warn_on_moderate_gap(tmp_path: Path) -> None:
    # 41 states present, 10 missing → warn (>5, not >25)
    states = [
        "al", "ak", "az", "ar", "ca", "co", "ct", "dc", "de", "fl",
        "ga", "hi", "id", "il", "in", "ia", "ks", "ky", "la", "me",
        "md", "ma", "mi", "mn", "ms", "mo", "mt", "ne", "nv", "nh",
        "nj", "nm", "ny", "nc", "nd", "oh", "ok", "or", "pa", "ri", "sc",
    ]
    _write_features(
        tmp_path / "substation.geojson",
        [_osm_feature(s) for s in states],
    )
    r = check_coverage(bundle_dir=tmp_path)
    assert r.status == "warn"


def test_coverage_fail_on_severe_gap(tmp_path: Path) -> None:
    # only 3 states → 48 missing → fail
    _write_features(
        tmp_path / "substation.geojson",
        [_osm_feature("ca"), _osm_feature("tx"), _osm_feature("ny")],
    )
    r = check_coverage(bundle_dir=tmp_path)
    assert r.status == "fail"


def test_coverage_eia_plants_use_state_property(tmp_path: Path) -> None:
    """PUDL plants carry an explicit ``state`` field; OSM heuristic also kicks in."""
    plants = [_eia_plant(s) for s in ["CA", "TX", "NY", "FL", "WA", "AZ"]]
    _write_features(tmp_path / "plant.geojson", plants)
    r = check_coverage(bundle_dir=tmp_path)
    assert r.status == "fail"  # 6 states < 6 + 25 missing threshold means ample missing
    assert "plant: 6 features" in " ".join(r.details)
