"""HIFLD bronze loader.

Homeland Infrastructure Foundation-Level Data published open substations +
transmission lines until its 2022 archive. The geoplatform still hosts the
archived datasets as GeoJSON; we pull those verbatim into bronze. Silver
dbt models project into ``gold_network__buses`` / ``branches`` and
``gold_atlas__infrastructure_features``.
"""

from __future__ import annotations

from .bronze import LAYERS, HifldLayer, fetch_layer

__all__ = ["LAYERS", "HifldLayer", "fetch_layer"]
