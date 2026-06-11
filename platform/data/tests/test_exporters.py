"""Tests for the atlas bundle exporters.

We build a miniature DuckDB warehouse with just enough schema to exercise
both exporters end-to-end: all nine gold tables that ``to_duckdb`` expects,
and a small ``gold_atlas__infrastructure_features`` mart covering the three
geometry shapes ``to_pmtiles`` handles (plant point, substation point,
transmission line). The goal is to pin the exporter contract — flat table
names, per-kind GeoJSON paths, WKT → GeoJSON conversion — without leaning
on a real dbt build.
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest

from gridagent_data.exporters import to_duckdb, to_pmtiles


# Schemas dbt materialises to in ``profiles.yml``. We mirror them here so
# the exporter's ``src."{schema}"."{table}"`` lookups resolve against the
# fixture warehouse exactly like they do against the real one.
_GOLD_SCHEMAS = ("main_gold_network", "main_gold_atlas", "main_gold_market")


def _build_warehouse(path: Path) -> None:
    """Create a tiny warehouse with one row per gold table.

    We only materialise the columns the exporters actually touch — WKT +
    properties for the atlas mart, flat ``*`` for everything else. Extra
    columns in the real warehouse are carried through by the exporter's
    ``SELECT *`` without us having to enumerate them here.
    """
    conn = duckdb.connect(str(path))
    try:
        for schema in _GOLD_SCHEMAS:
            conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')

        # Network marts — a single row is enough to confirm the exporter
        # can SELECT * and round-trip the data.
        conn.execute(
            'CREATE TABLE "main_gold_network"."gold_network__buses" '
            "AS SELECT 'RTS-101' AS bus_id, 138.0 AS base_kv"
        )
        conn.execute(
            'CREATE TABLE "main_gold_network"."gold_network__branches" '
            "AS SELECT 'RTS-A23' AS branch_id, 'RTS-101' AS from_bus_id, "
            "'RTS-102' AS to_bus_id"
        )
        conn.execute(
            'CREATE TABLE "main_gold_network"."gold_network__loads" '
            "AS SELECT 'RTS-101-load' AS load_id, 100.0 AS p_mw"
        )
        conn.execute(
            'CREATE TABLE "main_gold_network"."gold_network__generators" '
            "AS SELECT 'RTS-gen-1' AS generator_id, 200.0 AS p_max_mw"
        )

        # Market stubs (empty is fine — we just need the table to exist).
        for table, cols in [
            ("gold_market__lmp_hourly", "CAST(NULL AS TIMESTAMP) AS ts, CAST(NULL AS VARCHAR) AS node"),
            ("gold_market__load_hourly", "CAST(NULL AS TIMESTAMP) AS ts, CAST(NULL AS VARCHAR) AS ba"),
            ("gold_market__generation_by_ba_hourly", "CAST(NULL AS TIMESTAMP) AS ts, CAST(NULL AS VARCHAR) AS ba"),
            ("gold_market__queue_snapshot", "CAST(NULL AS VARCHAR) AS project_id"),
        ]:
            conn.execute(
                f'CREATE TABLE "main_gold_market"."{table}" AS '
                f"SELECT {cols} WHERE 1=0"
            )

        # Atlas mart — three rows, one per kind the PMTiles exporter cares
        # about. The ``properties`` column is a STRUCT in real dbt; we use
        # a JSON string here because DuckDB will round-trip it as-is and
        # ``_write_geojson`` handles the ``isinstance(properties, str)``
        # branch explicitly.
        conn.execute(
            """
            CREATE TABLE "main_gold_atlas"."gold_atlas__infrastructure_features" AS
            SELECT * FROM (VALUES
                (
                    'plant-1', 'Big Solar Farm', 'plant',
                    '{"fuel": "solar", "capacity_mw": 150}',
                    ['eia860'], ['public_domain'],
                    'POINT(-97.5 30.2)', false
                ),
                (
                    'sub-101', 'Downtown 138kV', 'substation',
                    '{"base_kv": 138}',
                    ['rts_gmlc'], ['bsd_3_clause'],
                    'POINT(-97.7 30.3)', true
                ),
                (
                    'branch-A23', 'Line 101-102', 'transmission_line',
                    '{"base_kv": 138, "length_km": 22.1}',
                    ['rts_gmlc'], ['bsd_3_clause'],
                    'LINESTRING(-97.7 30.3, -97.5 30.2)', true
                ),
                (
                    'plant-rollup-0', 'No Location Plant', 'plant',
                    '{"fuel": "gas"}',
                    ['eia860'], ['public_domain'],
                    NULL, false
                )
            ) AS t(feature_id, display_name, kind, properties, sources, licenses, geometry_wkt, synthetic)
            """
        )
    finally:
        conn.close()


@pytest.fixture
def warehouse(tmp_path: Path) -> Path:
    wh = tmp_path / "warehouse.duckdb"
    _build_warehouse(wh)
    return wh


# ---------------------------------------------------------------------------
# to_duckdb
# ---------------------------------------------------------------------------


def test_to_duckdb_export_materialises_flat_tables(warehouse: Path, tmp_path: Path) -> None:
    out = tmp_path / "bundle.duckdb"
    result = to_duckdb.export(warehouse, out)

    assert result == out
    assert out.is_file()

    conn = duckdb.connect(str(out), read_only=True)
    try:
        flat_names = {row[0] for row in conn.execute("SHOW TABLES").fetchall()}
    finally:
        conn.close()

    expected = set(to_duckdb._EXPORTS.values())
    assert expected.issubset(flat_names), f"missing {expected - flat_names}"

    # Sanity-check one flat table has the data we seeded.
    conn = duckdb.connect(str(out), read_only=True)
    try:
        bus_id, base_kv = conn.execute("SELECT bus_id, base_kv FROM buses").fetchone()
    finally:
        conn.close()
    assert bus_id == "RTS-101"
    assert base_kv == pytest.approx(138.0)


def test_to_duckdb_export_overwrites_existing(warehouse: Path, tmp_path: Path) -> None:
    out = tmp_path / "bundle.duckdb"
    out.write_bytes(b"stale")

    to_duckdb.export(warehouse, out)

    # If the exporter mishandled the pre-existing file it would either
    # fail to open or retain the junk bytes; opening read-only and listing
    # the flat tables proves we got a fresh database.
    conn = duckdb.connect(str(out), read_only=True)
    try:
        tables = {row[0] for row in conn.execute("SHOW TABLES").fetchall()}
    finally:
        conn.close()
    assert "buses" in tables


def test_to_duckdb_missing_warehouse_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        to_duckdb.export(tmp_path / "nope.duckdb", tmp_path / "bundle.duckdb")


def test_copy_to_atlas_public_places_bundle(warehouse: Path, tmp_path: Path) -> None:
    bundle = tmp_path / "bundle.duckdb"
    to_duckdb.export(warehouse, bundle)

    public = tmp_path / "public"
    landed = to_duckdb.copy_to_atlas_public(bundle, public)

    assert landed == public / "bundle.duckdb"
    assert landed.is_file()
    assert landed.stat().st_size == bundle.stat().st_size


# ---------------------------------------------------------------------------
# to_pmtiles
# ---------------------------------------------------------------------------


def test_to_pmtiles_writes_per_kind_geojson(warehouse: Path, tmp_path: Path) -> None:
    out = tmp_path / "tiles"
    results = to_pmtiles.export(warehouse, out)

    by_kind = {r.kind: r for r in results}
    # Every layer the exporter knows about should appear in the result set,
    # even if its feature count is zero — callers rely on the complete list
    # to decide what to ship.
    assert set(by_kind) == set(to_pmtiles.TILE_LAYERS)

    plant = by_kind["plant"]
    assert plant.feature_count == 1, "row with NULL geometry should have been skipped"
    assert plant.geojson_path == out / "plant.geojson"
    fc = json.loads(plant.geojson_path.read_text())
    assert fc["type"] == "FeatureCollection"
    assert fc["features"][0]["geometry"] == {
        "type": "Point",
        "coordinates": [-97.5, 30.2],
    }
    props = fc["features"][0]["properties"]
    assert props["feature_id"] == "plant-1"
    assert props["name"] == "Big Solar Farm"
    assert props["kind"] == "plant"
    assert props["fuel"] == "solar"
    assert props["sources"] == ["eia860"]

    line = by_kind["transmission_line"]
    assert line.feature_count == 1
    line_feature = json.loads(line.geojson_path.read_text())["features"][0]
    assert line_feature["geometry"] == {
        "type": "LineString",
        "coordinates": [[-97.7, 30.3], [-97.5, 30.2]],
    }


def test_to_pmtiles_skips_tippecanoe_when_missing(warehouse: Path, tmp_path: Path) -> None:
    out = tmp_path / "tiles"
    # Point ``tippecanoe_bin`` at something guaranteed-absent so ``shutil.which``
    # returns None; the exporter should still produce GeoJSON and simply
    # leave ``pmtiles_path=None`` on every result.
    results = to_pmtiles.export(warehouse, out, tippecanoe_bin="definitely-not-on-path-12345")

    assert all(r.pmtiles_path is None for r in results)
    assert all(r.geojson_path.is_file() for r in results)


def test_to_pmtiles_missing_warehouse_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        to_pmtiles.export(tmp_path / "nope.duckdb", tmp_path / "tiles")


def test_wkt_to_geojson_handles_unsupported_shape() -> None:
    # Polygon is not one of the shapes the atlas mart emits; the helper
    # should decline rather than guessing.
    assert to_pmtiles._wkt_to_geojson_geometry("POLYGON((0 0, 1 0, 1 1, 0 0))") is None
    assert to_pmtiles._wkt_to_geojson_geometry(None) is None
    assert to_pmtiles._wkt_to_geojson_geometry("") is None
