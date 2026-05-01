"""Cross-language schema source of truth.

These Pydantic models are emitted to TS and committed to
``shared/schema/src/index.ts``. The generator
(:mod:`gridagent_data.schema.generate_ts`) walks ``model_fields`` and
emits ``export interface`` declarations with matching field types and
optionality.

Rules for editing:

* Add a new model here, then run ``python -m
  gridagent_data.schema.generate_ts --out shared/schema/src/index.ts``
  from the repo root.
* Don't edit ``shared/schema/src/index.ts`` by hand. CI rejects drift.
* Keep field types to the subset the generator understands:
  ``str``, ``int``, ``float``, ``bool``, ``None`` literal,
  ``Literal[...]``, ``X | None``, ``tuple[X, ...]`` / ``list[X]``, and
  references to other models in this module.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


# ---- Type aliases ----------------------------------------------------------

FeatureKind = Literal[
    "plant",
    "unit",
    "substation",
    "transmission_line",
    "data_center",
    "gas_pipeline",
    "distribution_feeder",
    "queue_project",
]

Tier = Literal["free", "pro", "enterprise"]


# ---- Models ---------------------------------------------------------------


class GridFeatureProperties(BaseModel):
    """Per-feature provenance carried in the gold_atlas mart and on every
    rendered popover. ``sources`` and ``licenses`` are arrays so a
    conflated feature can credit every upstream input."""

    id: str
    kind: FeatureKind
    name: str | None = None
    sources: tuple[str, ...]
    licenses: tuple[str, ...]


class ManifestLayer(BaseModel):
    """One entry in the runtime manifest: a layer's tile URL, its license
    sidecar URL, and the tier required to render it."""

    id: str
    kind: FeatureKind
    tile_url: str
    license_url: str
    tier: Tier


class Manifest(BaseModel):
    """Top-level manifest the frontend fetches on boot. The frontend never
    hardcodes a tile URL; everything routes through here so a data
    refresh does not require an app deploy."""

    version: str
    generated_at: str
    layers: tuple[ManifestLayer, ...]


class LicenseSidecar(BaseModel):
    """The ``license.json`` written next to every PMTiles archive at
    export time. Read by the frontend to render attribution at the zoom
    levels each license demands; consumed by the build-time
    ``/attribution`` page generator."""

    source: str
    retrieved_at: str
    license: str
    citation: str
    attribution_required_at_zoom: int | None = None
