"""Tests for the GB/EU bronze loaders.

Same posture as the other loader tests: ``httpx.MockTransport`` everywhere,
assertions on the on-disk contract (paths, payload fidelity, manifest
fields) that downstream silver models bind to.
"""

from __future__ import annotations

import json
from datetime import date

import httpx
import pytest

from gridagent_data import paths as gridagent_paths

_DAY = date(2026, 7, 20)


@pytest.fixture
def isolated_data_root(tmp_path, monkeypatch):
    monkeypatch.setattr(gridagent_paths, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(gridagent_paths, "BRONZE", tmp_path / "bronze")
    monkeypatch.setattr(gridagent_paths, "SILVER", tmp_path / "silver")
    monkeypatch.setattr(gridagent_paths, "GOLD", tmp_path / "gold")
    monkeypatch.setattr(gridagent_paths, "BUNDLE", tmp_path / "bundle")
    return tmp_path


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


# ---------------------------------------------------------------------------
# Carbon Intensity
# ---------------------------------------------------------------------------


def test_carbon_intensity_day(isolated_data_root):
    from gridagent_data.sources.carbon_intensity import fetch_day

    body = {"data": [{"from": "2026-07-20T00:00Z", "to": "2026-07-20T00:30Z",
                      "intensity": {"forecast": 100, "actual": 90, "index": "low"}}] * 48}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/intensity/date/2026-07-20")
        return httpx.Response(200, json=body)

    m = fetch_day(_DAY, client=_client(handler))
    assert m["n_periods"] == 48
    assert m["source"]["license"] == "CC-BY-4.0"
    out = isolated_data_root / "bronze" / "carbon_intensity" / "intensity_2026-07-20.json"
    assert json.loads(out.read_text()) == body


# ---------------------------------------------------------------------------
# PV_Live
# ---------------------------------------------------------------------------


def test_pv_live_day(isolated_data_root):
    from gridagent_data.sources.pv_live import fetch_day

    body = {"meta": ["gsp_id", "datetime_gmt", "generation_mw"],
            "data": [[0, "2026-07-20T12:00:00Z", 5432.1]]}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/gsp/0")
        params = dict(request.url.params)
        assert params["start"].startswith("2026-07-20")
        assert params["end"].startswith("2026-07-21")
        return httpx.Response(200, json=body)

    m = fetch_day(_DAY, client=_client(handler))
    assert m["n_rows"] == 1
    assert m["columns"] == body["meta"]
    out = isolated_data_root / "bronze" / "pv_live" / "gsp_0" / "pv_2026-07-20.json"
    assert out.is_file()


# ---------------------------------------------------------------------------
# Elexon BMRS
# ---------------------------------------------------------------------------


def test_bmrs_day_partitions(isolated_data_root):
    from gridagent_data.sources.elexon_bmrs import DATASETS, fetch_day

    agpt = next(d for d in DATASETS if d.name == "generation_actual_per_type")
    body = {"data": [{"startTime": "2026-07-20T00:00:00Z", "settlementPeriod": 1,
                      "data": [{"psrType": "Wind Onshore", "quantity": 1234.0}]}]}

    def handler(request: httpx.Request) -> httpx.Response:
        assert "generation/actual/per-type" in request.url.path
        params = dict(request.url.params)
        assert params["from"] == "2026-07-20T00:00Z"
        assert params["format"] == "json"
        return httpx.Response(200, json=body)

    m = fetch_day(agpt, _DAY, client=_client(handler))
    assert m["n_rows"] == 1
    assert m["attribution"] == "Contains BSC data © Elexon Limited"
    out = (isolated_data_root / "bronze" / "elexon_bmrs" / "generation_actual_per_type"
           / "generation_actual_per_type_2026-07-20.json")
    assert json.loads(out.read_text()) == body


def test_bmrs_registry():
    from gridagent_data.sources.elexon_bmrs import DATASETS

    assert {d.name for d in DATASETS} == {"generation_actual_per_type", "demand_outturn"}


# ---------------------------------------------------------------------------
# NESO CKAN
# ---------------------------------------------------------------------------


def test_neso_resolves_and_downloads_csv(isolated_data_root):
    from gridagent_data.sources.neso import DATASETS, fetch_dataset

    dataset = DATASETS[0]
    package = {
        "result": {
            "name": dataset.slug,
            "resources": [
                {"id": "doc-1", "format": "DOC", "name": "Definition", "url": "https://x/def.doc"},
                {"id": "csv-old", "format": "CSV", "name": "Archive 2019", "url": "https://x/2019.csv"},
                {"id": "csv-cur", "format": "CSV",
                 "name": "Embedded Solar and Wind Forecast", "url": "https://x/current.csv"},
            ],
        }
    }
    csv_bytes = b"DATE_GMT,EMBEDDED_WIND_FORECAST\n2026-07-20,4321\n"

    def handler(request: httpx.Request) -> httpx.Response:
        if "package_show" in request.url.path:
            assert dict(request.url.params)["id"] == dataset.slug
            return httpx.Response(200, json=package)
        assert str(request.url) == "https://x/current.csv"
        return httpx.Response(200, content=csv_bytes)

    m = fetch_dataset(dataset, client=_client(handler))
    assert m["resource_id"] == "csv-cur"  # name match beats the older archive CSV
    out = isolated_data_root / "bronze" / "neso" / dataset.name / f"{dataset.name}.csv"
    assert out.read_bytes() == csv_bytes


def test_neso_no_csv_resources_raises(isolated_data_root):
    from gridagent_data.sources.neso import DATASETS, fetch_dataset

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"result": {"resources": [
            {"id": "d", "format": "DOC", "name": "x", "url": "https://x/d.doc"}]}})

    with pytest.raises(RuntimeError, match="no CSV resources"):
        fetch_dataset(DATASETS[0], client=_client(handler))


# ---------------------------------------------------------------------------
# ENTSO-E
# ---------------------------------------------------------------------------


def test_entsoe_requires_token(isolated_data_root, monkeypatch):
    from gridagent_data.sources.entsoe import DOCUMENTS, ZONES, fetch_day

    monkeypatch.delenv("ENTSOE_API_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="ENTSOE_API_TOKEN"):
        fetch_day(ZONES[0], DOCUMENTS[0], _DAY)


def test_entsoe_day_ahead_prices_request_shape(isolated_data_root, monkeypatch):
    from gridagent_data.sources.entsoe import DOCUMENTS, ZONES, fetch_day

    monkeypatch.setenv("ENTSOE_API_TOKEN", "test-token")
    xml = "<Publication_MarketDocument>...</Publication_MarketDocument>"

    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        assert params["securityToken"] == "test-token"
        assert params["documentType"] == "A44"
        assert params["in_Domain"] == params["out_Domain"] == ZONES[0].eic
        assert params["periodStart"] == "202607200000"
        assert params["periodEnd"] == "202607210000"
        return httpx.Response(200, text=xml)

    prices = next(d for d in DOCUMENTS if d.name == "day_ahead_prices")
    m = fetch_day(ZONES[0], prices, _DAY, client=_client(handler))
    out = (isolated_data_root / "bronze" / "entsoe" / ZONES[0].name
           / "day_ahead_prices" / "day_ahead_prices_2026-07-20.xml")
    assert out.read_text() == xml
    assert m["document_type"] == "A44"


def test_entsoe_generation_uses_process_type(isolated_data_root, monkeypatch):
    from gridagent_data.sources.entsoe import DOCUMENTS, ZONES, fetch_day

    monkeypatch.setenv("ENTSOE_API_TOKEN", "test-token")

    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        assert params["documentType"] == "A75"
        assert params["processType"] == "A16"
        assert "out_Domain" not in params
        return httpx.Response(200, text="<GL_MarketDocument/>")

    gen = next(d for d in DOCUMENTS if d.name == "actual_generation")
    fetch_day(ZONES[1], gen, _DAY, client=_client(handler))


# ---------------------------------------------------------------------------
# ECB FX
# ---------------------------------------------------------------------------


_ECB_XML = """<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01"
                 xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
  <Cube>
    <Cube time='2026-07-20'>
      <Cube currency='USD' rate='1.1426'/>
      <Cube currency='GBP' rate='0.8583'/>
    </Cube>
  </Cube>
</gesmes:Envelope>"""


def test_ecb_fx_daily(isolated_data_root):
    from gridagent_data.sources.ecb_fx import fetch_daily_rates

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=_ECB_XML)

    m = fetch_daily_rates(client=_client(handler))
    assert m["rate_date"] == "2026-07-20"
    assert m["n_currencies"] == 2
    out = isolated_data_root / "bronze" / "ecb_fx" / "eurofxref_2026-07-20.xml"
    assert out.is_file()
