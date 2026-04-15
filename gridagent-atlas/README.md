# gridagent-atlas

MapLibre + PMTiles + DuckDB-WASM browse surface over the canonical
`gold_atlas` and `gold_market` schemas. **First-class deliverable** — the
human-facing way to extract value from the platform.

## Architecture

```
gridagent-data exporters/         gridagent-atlas (this repo)
   to_pmtiles.py  ───────►  /tiles/*.pmtiles      (PMTiles via HTTP range)
   to_duckdb.py   ───────►  /data/bundle.duckdb   (DuckDB-WASM in-browser)
                            /                     (Vite static site)
```

No backend tile server. No backend query API. Static deploy to
S3 / R2 / Cloudflare Pages, browser does the rest.

## Layers

- **Base:** terrain, satellite, ISO/BA boundaries, retired plants.
- **Feature catalog** (toggleable, all from `gold_atlas.infrastructure_features`):
  - `substation` (point, voltage-styled)
  - `transmission_line` (line, voltage-styled)
  - `plant` / `unit` (point, fuel-styled)
  - `gas_pipeline`
  - `data_center`
  - `distribution_feeder` (Phase 7)
- **Time-varying:** hourly LMP heatmap (deck.gl `HeatmapLayer` over
  `gold_market.lmp_hourly`, scrubber timeline).
- **Scenario overlays:** orchestrator episodes write
  `episode_{id}_overlay.geojson` (red overload edges, green mitigation
  upgrades); selectable by ID.

## Provenance

Every popover shows `sources=[...]` and `licenses=[...]` joined to the
dbt-generated manifest, matching the per-feature provenance promise from
`gridagent-data`.

## Stack

- Vite + TypeScript
- MapLibre GL JS (vector tiles)
- deck.gl (analytical overlays)
- PMTiles client (HTTP range requests, no tile server)
- DuckDB-WASM (in-browser SQL over the bundle)

## Cartography reuse

- OpenInfraMap MapLibre styles (Apache-2.0) for power/voltage styling.
- PyPSA-USA plotting recipes for fuel-color palettes.

## Develop

```bash
pnpm install
pnpm dev      # http://localhost:5173
pnpm build    # static output to dist/
```

Serves PMTiles & DuckDB from `./public/` in dev; configure
`VITE_TILE_BASE` / `VITE_DATA_BASE` for production deploys.
