"""Tests for the open-data gap loaders: USGS (USWTDB/USPVDB) and Open-Meteo.

Same posture as the batch-3 loader tests: every loader runs against an
``httpx.MockTransport`` so CI is deterministic; assertions bind to the
on-disk contract (paths, GeoJSON shape, manifest fields) that silver
models consume.
"""

from __future__ import annotations

import json

import httpx
import pytest

from gridagent_data import paths as gridagent_paths


@pytest.fixture
def isolated_data_root(tmp_path, monkeypatch):
    monkeypatch.setattr(gridagent_paths, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(gridagent_paths, "BRONZE", tmp_path / "bronze")
    monkeypatch.setattr(gridagent_paths, "SILVER", tmp_path / "silver")
    monkeypatch.setattr(gridagent_paths, "GOLD", tmp_path / "gold")
    monkeypatch.setattr(gridagent_paths, "BUNDLE", tmp_path / "bundle")
    return tmp_path


# ---------------------------------------------------------------------------
# USGS
# ---------------------------------------------------------------------------


_TURBINE_ROWS = [
    {"case_id": 1, "p_name": "Alpha", "t_cap": 4200, "xlong": -99.8, "ylat": 36.4, "eia_id": 65511},
    {"case_id": 2, "p_name": "Alpha", "t_cap": 4200, "xlong": -99.7, "ylat": 36.5, "eia_id": 65511},
    {"case_id": 3, "p_name": "NoCoords", "t_cap": 1500, "xlong": None, "ylat": None, "eia_id": 1},
]


def _usgs_transport(rows):
    """Serve *rows* on the first page and an empty page afterwards."""

    def handler(request: httpx.Request) -> httpx.Response:
        offset = int(dict(request.url.params).get("offset", "0"))
        return httpx.Response(200, json=rows if offset == 0 else [])

    return httpx.MockTransport(handler)


def test_usgs_fetch_writes_geojson_and_manifest(isolated_data_root):
    from gridagent_data.sources.usgs import DATASETS, fetch_dataset

    turbines = next(d for d in DATASETS if d.name == "uswtdb_turbines")
    client = httpx.Client(transport=_usgs_transport(_TURBINE_ROWS))
    manifest = fetch_dataset(turbines, client=client)

    out = isolated_data_root / "bronze" / "usgs" / "uswtdb_turbines" / "uswtdb_turbines.geojson"
    assert out.is_file()
    fc = json.loads(out.read_text())
    assert fc["type"] == "FeatureCollection"
    # Row without coordinates is dropped and counted, not silently lost.
    assert len(fc["features"]) == 2
    assert manifest["feature_count"] == 2
    assert manifest["dropped_no_coords"] == 1
    assert manifest["source"]["license"] == "US-PD"

    # Attributes survive verbatim in properties (eia_id joins to EIA-860).
    props = fc["features"][0]["properties"]
    assert props["eia_id"] == 65511

    sidecar = json.loads((out.parent / "manifest.json").read_text())
    assert sidecar["dataset"] == "uswtdb_turbines"
    assert sidecar["feature_count"] == 2


def test_usgs_pagination_stops_on_short_page(isolated_data_root):
    from gridagent_data.sources.usgs import DATASETS, fetch_dataset
    from gridagent_data.sources.usgs.bronze import _PAGE_SIZE

    # Full first page → loader must request a second page; empty second
    # page ends the loop.
    full_page = [
        {"case_id": i, "xlong": -100.0 + i * 1e-4, "ylat": 35.0, "eia_id": i}
        for i in range(_PAGE_SIZE)
    ]
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        offset = int(dict(request.url.params).get("offset", "0"))
        calls.append(offset)
        return httpx.Response(200, json=full_page if offset == 0 else [])

    pv = next(d for d in DATASETS if d.name == "uspvdb_projects")
    client = httpx.Client(transport=httpx.MockTransport(handler))
    manifest = fetch_dataset(pv, client=client)

    assert calls == [0, _PAGE_SIZE]
    assert manifest["feature_count"] == _PAGE_SIZE


def test_usgs_datasets_registry_covers_wind_and_solar():
    from gridagent_data.sources.usgs import DATASETS

    names = {d.name for d in DATASETS}
    assert names == {"uswtdb_turbines", "uspvdb_projects"}


# ---------------------------------------------------------------------------
# Open-Meteo
# ---------------------------------------------------------------------------


_OM_BODY = {
    "latitude": 32.7,
    "longitude": -96.8,
    "hourly_units": {"temperature_2m": "°C"},
    "hourly": {
        "time": ["2026-07-21T00:00", "2026-07-21T01:00"],
        "temperature_2m": [31.2, 30.1],
        "wind_speed_100m": [22.0, 24.5],
        "wind_speed_10m": [12.0, 13.5],
        "shortwave_radiation": [0.0, 0.0],
        "cloud_cover": [10, 12],
    },
}


def test_open_meteo_fetch_writes_json_and_manifest(isolated_data_root):
    from gridagent_data.sources.open_meteo import FORECAST_POINTS, fetch_forecast

    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(dict(request.url.params))
        return httpx.Response(200, json=_OM_BODY)

    point = FORECAST_POINTS[0]
    client = httpx.Client(transport=httpx.MockTransport(handler))
    manifest = fetch_forecast(point, client=client)

    # Request carries every registered hourly variable and UTC timezone.
    assert captured["timezone"] == "UTC"
    assert "wind_speed_100m" in captured["hourly"]
    assert "shortwave_radiation" in captured["hourly"]

    out_dir = isolated_data_root / "bronze" / "open_meteo" / point.name
    files = list(out_dir.glob("forecast_*.json"))
    assert len(files) == 1
    assert json.loads(files[0].read_text()) == _OM_BODY

    assert manifest["n_hours"] == 2
    assert manifest["iso"] == point.iso
    assert manifest["source"]["license"] == "CC-BY-4.0"


def test_open_meteo_point_registry_covers_all_isos():
    from gridagent_data.sources.open_meteo import FORECAST_POINTS

    isos = {p.iso for p in FORECAST_POINTS}
    assert isos == {"CAISO", "ERCOT", "MISO", "NYISO", "PJM", "ISO-NE", "SPP"}


# ---------------------------------------------------------------------------
# EIA-930 via PUDL
# ---------------------------------------------------------------------------


def test_pudl_tables_include_eia930_generation():
    from gridagent_data.sources.pudl.bronze import TABLES

    names = {t.name for t in TABLES}
    assert "core_eia930__hourly_net_generation_by_energy_source" in names
