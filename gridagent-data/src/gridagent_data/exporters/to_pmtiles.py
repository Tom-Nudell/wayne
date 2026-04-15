"""Export ``gold_atlas__infrastructure_features`` to PMTiles.

Two-phase pipeline:

  1. Write per-kind GeoJSON from the dbt warehouse. DuckDB parses each
     row's WKT and emits valid GeoJSON features with ``properties`` drawn
     from the mart's JSON column. Rows with NULL geometry are skipped —
     they still live in the mart for tabular queries but have nothing to
     render on a map.
  2. Shell out to ``tippecanoe`` (one call per kind) to produce one
     PMTiles archive per layer. ``tippecanoe`` is not a Python package;
     the user installs it once via ``brew install tippecanoe`` or the
     upstream build. When ``tippecanoe`` is not on PATH we stop after
     phase 1 and return the GeoJSON paths, so callers can still drop
     intermediate files in ``gridagent-atlas/public/``.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import duckdb

# One PMTiles file per ``kind`` so the frontend can toggle layers without
# downloading geometry it won't render. Keys here must match ``kind`` values
# emitted by ``gold_atlas__infrastructure_features``.
TILE_LAYERS: dict[str, str] = {
    "plant": "plants.pmtiles",
    "substation": "substations.pmtiles",
    "transmission_line": "transmission_lines.pmtiles",
    "data_center": "data_centers.pmtiles",
    "gas_pipeline": "gas_pipelines.pmtiles",
    "distribution_feeder": "distribution_feeders.pmtiles",
}

# Per-kind tippecanoe invocation. Plants and substations are point layers
# that need per-feature dedup; transmission lines are linestrings that
# benefit from per-zoom simplification.
_TIPPECANOE_FLAGS: dict[str, list[str]] = {
    "plant": ["-zg", "--drop-densest-as-needed", "-l", "plants"],
    "substation": ["-zg", "--drop-densest-as-needed", "-l", "substations"],
    "transmission_line": ["-zg", "--simplify-only-low-zooms", "-l", "transmission_lines"],
    "data_center": ["-zg", "-l", "data_centers"],
    "gas_pipeline": ["-zg", "-l", "gas_pipelines"],
    "distribution_feeder": ["-z14", "-l", "distribution_feeders"],
}


@dataclass(frozen=True)
class TileExportResult:
    kind: str
    geojson_path: Path
    pmtiles_path: Path | None  # None when tippecanoe is unavailable.
    feature_count: int


def _write_geojson(
    conn: duckdb.DuckDBPyConnection,
    warehouse_schema: str,
    warehouse_table: str,
    kind: str,
    target: Path,
) -> int:
    """Write a GeoJSON FeatureCollection for one ``kind`` to ``target``.

    Returns the number of features emitted. Rows with NULL geometry are
    skipped — the mart is permitted to carry them (plant rollups before
    lat/lon is available) but the tile build has nothing to draw.
    """
    rows = conn.execute(
        f"""
        SELECT
            feature_id,
            display_name,
            properties,
            sources,
            licenses,
            geometry_wkt
        FROM src."{warehouse_schema}"."{warehouse_table}"
        WHERE kind = ?
          AND geometry_wkt IS NOT NULL
        """,
        [kind],
    ).fetchall()

    features = []
    for feature_id, display_name, properties, sources, licenses, wkt in rows:
        # DuckDB gives us WKT; convert to GeoJSON via the spatial extension
        # if the caller loaded it, else via a literal WKT→JSON shim. We keep
        # this in Python because the frontend already knows how to parse
        # GeoJSON and we want the tile build to work on hosts without the
        # DuckDB spatial extension installed.
        geometry = _wkt_to_geojson_geometry(wkt)
        if geometry is None:
            continue
        props = dict(properties) if isinstance(properties, dict) else (
            json.loads(properties) if isinstance(properties, str) else {}
        )
        props.update({
            "feature_id": feature_id,
            "name": display_name,
            "kind": kind,
            "sources": list(sources) if sources else [],
            "licenses": list(licenses) if licenses else [],
        })
        features.append({"type": "Feature", "geometry": geometry, "properties": props})

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps({"type": "FeatureCollection", "features": features})
    )
    return len(features)


def _wkt_to_geojson_geometry(wkt: str | None) -> dict | None:
    """Minimal WKT parser for the two shapes our mart emits.

    We only emit POINT and LINESTRING (see gold_atlas__infrastructure_features);
    a full WKT parser would be overkill here. Returns None for anything else so
    the caller can skip unrepresentable rows.
    """
    if not wkt:
        return None
    wkt = wkt.strip()
    if wkt.upper().startswith("POINT"):
        inner = wkt[wkt.index("(") + 1 : wkt.rindex(")")]
        lon, lat = inner.replace(",", " ").split()
        return {"type": "Point", "coordinates": [float(lon), float(lat)]}
    if wkt.upper().startswith("LINESTRING"):
        inner = wkt[wkt.index("(") + 1 : wkt.rindex(")")]
        coords = [
            [float(c) for c in pair.strip().split()]
            for pair in inner.split(",")
        ]
        return {"type": "LineString", "coordinates": coords}
    return None


def export(
    warehouse_path: Path,
    out_dir: Path,
    *,
    tippecanoe_bin: str = "tippecanoe",
) -> list[TileExportResult]:
    """Materialise one PMTiles archive per atlas ``kind``.

    If ``tippecanoe`` is not on PATH we emit GeoJSON only and return
    results with ``pmtiles_path=None`` so callers can ship the
    intermediates (still useful for dev preview without tiles).
    """
    warehouse_path = Path(warehouse_path)
    out_dir = Path(out_dir)
    if not warehouse_path.is_file():
        raise FileNotFoundError(f"Warehouse not found at {warehouse_path}")
    out_dir.mkdir(parents=True, exist_ok=True)

    have_tippecanoe = shutil.which(tippecanoe_bin) is not None

    results: list[TileExportResult] = []
    conn = duckdb.connect(":memory:")
    try:
        conn.execute(f"ATTACH '{warehouse_path}' AS src (READ_ONLY)")
        for kind, pmtiles_name in TILE_LAYERS.items():
            geojson_path = out_dir / f"{kind}.geojson"
            count = _write_geojson(
                conn,
                "main_gold_atlas",
                "gold_atlas__infrastructure_features",
                kind,
                geojson_path,
            )
            pmtiles_path = out_dir / pmtiles_name
            if count > 0 and have_tippecanoe:
                subprocess.run(
                    [
                        tippecanoe_bin,
                        "--force",
                        "-o",
                        str(pmtiles_path),
                        *_TIPPECANOE_FLAGS.get(kind, ["-zg"]),
                        str(geojson_path),
                    ],
                    check=True,
                )
            else:
                pmtiles_path = pmtiles_path if pmtiles_path.exists() else None
            results.append(
                TileExportResult(
                    kind=kind,
                    geojson_path=geojson_path,
                    pmtiles_path=pmtiles_path if (have_tippecanoe and count > 0) else None,
                    feature_count=count,
                )
            )
    finally:
        conn.close()

    return results
