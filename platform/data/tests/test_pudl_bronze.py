"""Tests for ``gridagent_data.sources.pudl.bronze``.

We mock the HTTP layer so CI doesn't depend on Catalyst Cooperative's S3.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from gridagent_data import paths as gridagent_paths
from gridagent_data.sources.pudl import TABLES, fetch_table


@pytest.fixture
def isolated_data_root(tmp_path, monkeypatch):
    monkeypatch.setattr(gridagent_paths, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(gridagent_paths, "BRONZE", tmp_path / "bronze")
    monkeypatch.setattr(gridagent_paths, "SILVER", tmp_path / "silver")
    monkeypatch.setattr(gridagent_paths, "GOLD", tmp_path / "gold")
    monkeypatch.setattr(gridagent_paths, "BUNDLE", tmp_path / "bundle")
    return tmp_path


def _mock_transport(payload: bytes, etag: str = '"abc"') -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=payload,
            headers={"etag": etag, "content-length": str(len(payload))},
        )

    return httpx.MockTransport(handler)


def test_fetch_table_writes_parquet_and_manifest(isolated_data_root: Path) -> None:
    table = TABLES[0]
    payload = b"PAR1" + b"\x00" * 32  # Just enough to look parquet-shaped on disk.
    client = httpx.Client(transport=_mock_transport(payload))

    manifest = fetch_table(table, client=client)

    parquet = isolated_data_root / "bronze" / "pudl" / table.name / f"{table.name}.parquet"
    assert parquet.exists()
    assert parquet.read_bytes() == payload

    manifest_on_disk = json.loads(
        (isolated_data_root / "bronze" / "pudl" / table.name / "manifest.json").read_text()
    )
    assert manifest_on_disk == manifest
    assert manifest["table"] == table.name
    assert manifest["bytes"] == len(payload)
    assert manifest["source"]["name"] == "pudl"
    assert manifest["source"]["license"] == "CC-BY-4.0"
