"""Tests for the batch 3 bronze loaders.

Each loader is exercised via ``httpx.MockTransport`` so CI is deterministic
and does not depend on upstream network endpoints. The goal is to verify
the on-disk shape — file path, bytes, manifest fields — because that is
the contract silver dbt models bind to.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

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


def _mock(payload: bytes, *, etag: str = '"abc"') -> httpx.MockTransport:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=payload,
            headers={"etag": etag, "content-length": str(len(payload))},
        )

    return httpx.MockTransport(handler)


# ---------------------------------------------------------------------------
# GridStatus
# ---------------------------------------------------------------------------


def test_gridstatus_fetch_day_writes_csv_and_manifest(isolated_data_root: Path) -> None:
    from gridagent_data.sources.gridstatus import GridStatusPartition, fetch_day

    payload = b"hour,lmp\n0,27.3\n1,29.9\n"
    client = httpx.Client(transport=_mock(payload))
    part = GridStatusPartition(dataset="lmp_hourly", iso="ercot", day=date(2026, 1, 1))

    manifest = fetch_day(part, client=client, api_key="deadbeef")

    target = isolated_data_root / "bronze" / "gridstatus" / "lmp_hourly" / "iso=ercot" / "date=2026-01-01.csv"
    assert target.exists()
    assert target.read_bytes() == payload

    assert manifest["dataset"] == "lmp_hourly"
    assert manifest["iso"] == "ercot"
    assert manifest["date"] == "2026-01-01"
    assert manifest["bytes"] == len(payload)
    assert manifest["source"]["name"] == "gridstatus"

    manifest_file = target.with_suffix(target.suffix + ".manifest.json")
    assert json.loads(manifest_file.read_text()) == manifest


# ---------------------------------------------------------------------------
# LBNL Queued Up
# ---------------------------------------------------------------------------


def test_lbnl_fetch_release_default_url(isolated_data_root: Path) -> None:
    from gridagent_data.sources.lbnl import DEFAULT_RELEASE, fetch_release

    payload = b"PK\x03\x04" + b"\x00" * 512  # XLSX magic header.
    client = httpx.Client(transport=_mock(payload))

    manifest = fetch_release(client=client)

    target = (
        isolated_data_root
        / "bronze"
        / "lbnl_queued_up"
        / f"release_{DEFAULT_RELEASE.year}"
        / DEFAULT_RELEASE.filename
    )
    assert target.exists()
    assert target.read_bytes() == payload
    assert manifest["bytes"] == len(payload)
    assert manifest["source"]["name"] == "lbnl_queued_up"
    assert manifest["release_year"] == DEFAULT_RELEASE.year


def test_lbnl_env_override(isolated_data_root: Path, monkeypatch) -> None:
    from gridagent_data.sources.lbnl import fetch_release

    monkeypatch.setenv(
        "GRIDAGENT_LBNL_URL",
        "https://example.test/queued_up_2025_data_file.xlsx",
    )
    client = httpx.Client(transport=_mock(b"PK\x03\x04"))
    manifest = fetch_release(client=client)
    assert manifest["filename"] == "queued_up_2025_data_file.xlsx"
    assert "example.test" in manifest["url"]


# ---------------------------------------------------------------------------
# HIFLD
# ---------------------------------------------------------------------------


def test_hifld_fetch_layer_writes_geojson(isolated_data_root: Path) -> None:
    from gridagent_data.sources.hifld import LAYERS, fetch_layer

    payload = json.dumps({"type": "FeatureCollection", "features": []}).encode()
    client = httpx.Client(transport=_mock(payload))
    layer = LAYERS[0]

    manifest = fetch_layer(layer, client=client)

    target = (
        isolated_data_root / "bronze" / "hifld" / layer.name / f"{layer.name}.geojson"
    )
    assert target.exists()
    assert json.loads(target.read_text()) == {"type": "FeatureCollection", "features": []}
    assert manifest["layer"] == layer.name
    assert manifest["source"]["name"] == "hifld"
    assert "sha256" in manifest


# ---------------------------------------------------------------------------
# OSM
# ---------------------------------------------------------------------------


def test_osm_fetch_region_summarises_elements(isolated_data_root: Path) -> None:
    from gridagent_data.sources.osm import REGIONS, fetch_region

    overpass_response = json.dumps(
        {
            "elements": [
                {"type": "node", "id": 1, "tags": {"power": "substation"}},
                {"type": "node", "id": 2, "tags": {"power": "substation"}},
                {"type": "way", "id": 3, "tags": {"power": "line"}},
            ]
        }
    ).encode()
    client = httpx.Client(transport=_mock(overpass_response))

    manifest = fetch_region(REGIONS[0], client=client, endpoint="https://example.test/overpass")

    target = isolated_data_root / "bronze" / "osm" / REGIONS[0].name / "power.json"
    assert target.exists()
    assert manifest["element_counts"] == {"node": 2, "way": 1}
    assert manifest["source"]["name"] == "osm"
    assert manifest["source"]["license"] == "ODbL-1.0"


def test_osm_bbox_area(isolated_data_root: Path) -> None:
    from gridagent_data.sources.osm import OverpassRegion, fetch_region

    client = httpx.Client(transport=_mock(b'{"elements": []}'))
    region = OverpassRegion(name="test_bbox", area="29,-97,30,-96")
    manifest = fetch_region(region, client=client, endpoint="https://example.test/overpass")
    assert manifest["area"] == "29,-97,30,-96"
    assert manifest["element_counts"] == {}


# ---------------------------------------------------------------------------
# PyPSA-USA
# ---------------------------------------------------------------------------


def test_pypsa_usa_adopt_elec_nc(isolated_data_root: Path, tmp_path: Path) -> None:
    from gridagent_data.sources.pypsa_usa import adopt_elec_nc

    fake_nc = tmp_path / "elec.nc"
    fake_nc.write_bytes(b"CDF\x01" + b"\x00" * 128)  # Classic netCDF magic.

    manifest = adopt_elec_nc(fake_nc, label="default")

    target = isolated_data_root / "bronze" / "pypsa_usa" / "default" / "elec.nc"
    assert target.exists()
    assert target.read_bytes() == fake_nc.read_bytes()
    assert manifest["ingest_mode"] == "adopt"
    assert manifest["source"]["name"] == "pypsa_usa"
    assert "sha256" in manifest


def test_pypsa_usa_fetch_elec_nc(isolated_data_root: Path) -> None:
    from gridagent_data.sources.pypsa_usa import fetch_elec_nc

    payload = b"CDF\x01" + b"\x00" * 256
    client = httpx.Client(transport=_mock(payload))
    manifest = fetch_elec_nc(
        "https://example.test/elec.nc", label="snapshot_2026a", client=client
    )
    target = isolated_data_root / "bronze" / "pypsa_usa" / "snapshot_2026a" / "elec.nc"
    assert target.exists()
    assert target.read_bytes() == payload
    assert manifest["ingest_mode"] == "fetch"
    assert manifest["bytes"] == len(payload)


def test_pypsa_usa_adopt_missing_path_raises(isolated_data_root: Path, tmp_path: Path) -> None:
    from gridagent_data.sources.pypsa_usa import adopt_elec_nc

    with pytest.raises(FileNotFoundError):
        adopt_elec_nc(tmp_path / "nope.nc")
