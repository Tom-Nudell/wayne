"""Tests for the license sidecar emitter (brief §5/§7)."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb

from gridagent_data.exporters.licenses import (
    LICENSE_REGISTRY,
    collect_layer_licenses,
    write_sidecar,
)


def _seed_warehouse(path: Path) -> None:
    """Build a tiny warehouse with the gold_atlas shape this code expects."""
    con = duckdb.connect(str(path))
    con.execute("CREATE SCHEMA IF NOT EXISTS main_gold_atlas")
    con.execute(
        """
        CREATE TABLE main_gold_atlas.gold_atlas__infrastructure_features (
            kind VARCHAR,
            geometry_wkt VARCHAR,
            licenses VARCHAR[]
        )
        """
    )
    con.execute(
        """
        INSERT INTO main_gold_atlas.gold_atlas__infrastructure_features
        VALUES
          ('substation', 'POINT(1 1)', ['ODbL-1.0']),
          ('substation', 'POINT(2 2)', ['ODbL-1.0']),
          ('substation', NULL,          ['ODbL-1.0']),
          ('plant',      'POINT(3 3)', ['CC-BY-4.0']),
          ('plant',      'POINT(4 4)', ['ODbL-1.0']),
          ('plant',      'POINT(5 5)', ['CC-BY-4.0']),
          ('plant',      'POINT(6 6)', ['Public Domain'])
        """
    )
    con.close()


def test_collect_layer_licenses_aggregates_correctly(tmp_path: Path) -> None:
    db = tmp_path / "wh.duckdb"
    _seed_warehouse(db)

    con = duckdb.connect(":memory:")
    con.execute(f"ATTACH '{db}' AS src (READ_ONLY)")

    subs = collect_layer_licenses(
        con,
        warehouse_schema="main_gold_atlas",
        warehouse_table="gold_atlas__infrastructure_features",
        kind="substation",
    )
    # Two substations have geometry; the third is NULL geometry → excluded.
    assert subs == [
        {
            "spdx": "ODbL-1.0",
            "name": LICENSE_REGISTRY["ODbL-1.0"].name,
            "url": LICENSE_REGISTRY["ODbL-1.0"].url,
            "citation": LICENSE_REGISTRY["ODbL-1.0"].citation,
            "attribution_required": True,
            "feature_count": 2,
        }
    ]

    plants = collect_layer_licenses(
        con,
        warehouse_schema="main_gold_atlas",
        warehouse_table="gold_atlas__infrastructure_features",
        kind="plant",
    )
    # 4 plants have geometry, three distinct licenses; ordered by count desc.
    assert {entry["spdx"] for entry in plants} == {
        "CC-BY-4.0",
        "ODbL-1.0",
        "Public-Domain",
    }
    counts = {entry["spdx"]: entry["feature_count"] for entry in plants}
    assert counts == {"CC-BY-4.0": 2, "ODbL-1.0": 1, "Public-Domain": 1}


def test_write_sidecar_writes_valid_json(tmp_path: Path) -> None:
    db = tmp_path / "wh.duckdb"
    _seed_warehouse(db)

    con = duckdb.connect(":memory:")
    con.execute(f"ATTACH '{db}' AS src (READ_ONLY)")

    sidecar = tmp_path / "out" / "substations.license.json"
    write_sidecar(
        con,
        warehouse_schema="main_gold_atlas",
        warehouse_table="gold_atlas__infrastructure_features",
        kind="substation",
        layer_name="substations",
        feature_count=2,
        sidecar_path=sidecar,
    )

    doc = json.loads(sidecar.read_text())
    assert doc["layer"] == "substations"
    assert doc["kind"] == "substation"
    assert doc["feature_count"] == 2
    assert "generated_at" in doc
    assert len(doc["licenses"]) == 1
    odbl = doc["licenses"][0]
    assert odbl["spdx"] == "ODbL-1.0"
    assert odbl["attribution_required"] is True
    assert "OpenStreetMap" in odbl["citation"]


def test_unknown_license_falls_through(tmp_path: Path) -> None:
    db = tmp_path / "wh.duckdb"
    con = duckdb.connect(str(db))
    con.execute("CREATE SCHEMA IF NOT EXISTS main_gold_atlas")
    con.execute(
        """
        CREATE TABLE main_gold_atlas.gold_atlas__infrastructure_features (
            kind VARCHAR, geometry_wkt VARCHAR, licenses VARCHAR[]
        )
        """
    )
    con.execute(
        "INSERT INTO main_gold_atlas.gold_atlas__infrastructure_features "
        "VALUES ('plant', 'POINT(0 0)', ['MADE-UP-LICENSE'])"
    )
    con.close()

    rcon = duckdb.connect(":memory:")
    rcon.execute(f"ATTACH '{db}' AS src (READ_ONLY)")
    out = collect_layer_licenses(
        rcon,
        warehouse_schema="main_gold_atlas",
        warehouse_table="gold_atlas__infrastructure_features",
        kind="plant",
    )
    assert len(out) == 1
    assert out[0]["spdx"] == "MADE-UP-LICENSE"
    assert "no registered metadata" in out[0]["citation"]
    assert out[0]["attribution_required"] is True
