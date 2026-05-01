# @wayne/map

MapLibre style.json, paint specs, layer registry, popovers. Cartography as code.

Consumed by:
- `web/` — the commercial map product
- `platform/atlas/` — the internal agent dev viewer

Both surfaces render from the same paint specs and palette, so they cannot diverge visually. When a stylesheet change lands here, the visual regression in the data pipeline's QA gate (see brief §7) catches drift before it ships.

The unit-tested deterministic parts of cartography (color classification, voltage bins, feature filters) live in `src/`; the runtime style.json (forked from Protomaps) lands in `src/styles/` in Phase 1.
