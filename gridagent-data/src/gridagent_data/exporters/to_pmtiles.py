"""Export ``gold_atlas__infrastructure_features`` to PMTiles.

Drives ``tippecanoe``. Stub for now; the function signature is fixed so the
atlas frontend can be wired against the planned tile filenames.
"""

from __future__ import annotations

from pathlib import Path

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


def export(snapshot_dir: Path, out_dir: Path) -> dict[str, Path]:
    """Materialise one PMTiles archive per atlas ``kind``.

    Returns a mapping from ``kind`` to the written PMTiles path.
    """
    raise NotImplementedError("Wired up once gold_atlas__infrastructure_features has geometry.")
