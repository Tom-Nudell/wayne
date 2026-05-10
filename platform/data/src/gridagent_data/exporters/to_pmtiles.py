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
     intermediate files in ``platform/atlas/public/``.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import duckdb

from gridagent_data.exporters.licenses import write_sidecar

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
    "queue_project": "queue_projects.pmtiles",
    "ev_station": "ev_stations.pmtiles",
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
    "queue_project": ["-zg", "--drop-densest-as-needed", "-l", "queue_projects"],
    "ev_station": ["-zg", "--drop-densest-as-needed", "-l", "ev_stations"],
}


@dataclass(frozen=True)
class TileExportResult:
    kind: str
    geojson_path: Path
    pmtiles_path: Path | None  # None when tippecanoe is unavailable.
    sidecar_path: Path
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
            geometry_wkt,
            synthetic
        FROM src."{warehouse_schema}"."{warehouse_table}"
        WHERE kind = ?
          AND geometry_wkt IS NOT NULL
        """,
        [kind],
    ).fetchall()

    features = []
    for feature_id, display_name, properties, sources, licenses, wkt, synthetic in rows:
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
            "synthetic": bool(synthetic),
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


def _write_conflation_report(features: list[dict], report_path: Path) -> None:
    """Emit a per-layer conflation report alongside the GeoJSON.

    For layers assembled from multiple upstream sources, the mart stores
    a ``sources`` array per feature. This report summarises:

    * Total feature count.
    * Feature counts grouped by the unique *set* of sources that
      contributed to each feature (single-source vs. multi-source merged).
    * The top contributing source combinations, sorted by count.

    The QA gate's conflation check (``qa/conflation.py``) reads this file.
    A large "unresolved" bucket (features with >1 source but no explicit
    dedup key) triggers a ``warn``.
    """
    from datetime import datetime, timezone

    source_combos: Counter[str] = Counter()
    multi_source = 0
    single_source = 0
    no_source = 0

    for feat in features:
        props = feat.get("properties", {})
        raw = props.get("sources", [])
        if isinstance(raw, str):
            try:
                sources = json.loads(raw)
            except json.JSONDecodeError:
                sources = [raw] if raw else []
        else:
            sources = list(raw) if raw else []

        if not sources:
            no_source += 1
            source_combos["(none)"] += 1
        elif len(sources) == 1:
            single_source += 1
            source_combos[sources[0]] += 1
        else:
            multi_source += 1
            combo = " + ".join(sorted(sources))
            source_combos[combo] += 1

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "total_features": len(features),
        "single_source": single_source,
        "multi_source": multi_source,
        "no_source": no_source,
        "source_breakdown": [
            {"sources": combo, "count": n}
            for combo, n in source_combos.most_common()
        ],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2))


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
            sidecar_path = pmtiles_path.with_suffix(".license.json")
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

            # Conflation report — written from the in-memory feature list
            # so we don't have to re-parse the GeoJSON file.
            if count > 0:
                geojson_doc = json.loads(geojson_path.read_text())
                _write_conflation_report(
                    geojson_doc.get("features", []),
                    out_dir / f"{kind}.conflation_report.json",
                )

            # Always write the sidecar when the layer has features, even
            # if tippecanoe wasn't available — the sidecar is the
            # source of truth for attribution and the QA gate's license
            # check looks for it next to the planned PMTiles location.
            if count > 0:
                write_sidecar(
                    conn,
                    warehouse_schema="main_gold_atlas",
                    warehouse_table="gold_atlas__infrastructure_features",
                    kind=kind,
                    layer_name=pmtiles_name.removesuffix(".pmtiles"),
                    feature_count=count,
                    sidecar_path=sidecar_path,
                )

            results.append(
                TileExportResult(
                    kind=kind,
                    geojson_path=geojson_path,
                    pmtiles_path=pmtiles_path if (have_tippecanoe and count > 0) else None,
                    sidecar_path=sidecar_path,
                    feature_count=count,
                )
            )
    finally:
        conn.close()

    return results
