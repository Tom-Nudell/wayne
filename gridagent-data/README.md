# gridagent-data

ETL pipeline that produces three coordinated, versioned data marts from heterogeneous
public power-systems sources:

- **`network`** — analysis-grade bus / branch / generator / load tables, Sienna-ready
- **`atlas`** — visualization-grade `infrastructure_features` catalog with provenance, tile-ready
- **`market`** — hourly LMPs, load, queue, generation by BA

Sources are treated as upstream layers, not the canonical schema. PUDL handles EIA/FERC/CEMS,
PyPSA-USA contributes pre-balanced transmission topology, GridStatus provides real-time market
data, OSM + HIFLD give visualization-grade geospatial features, and NREL SMART-DS / EPRI
cover synthetic distribution grids.

**License posture:** every source is fully open (CC-BY-4.0, ODbL, BSD/MIT,
US public domain). Mixed-license sources (e.g. Global Energy Monitor, whose
trackers vary tier-by-tier) are deferred until we can confirm a fully open
subset for the global build.

## Layout

```
src/gridagent_data/        # Python package
  definitions.py            # Dagster Definitions entrypoint
  sources/                  # one module per upstream source
    pudl/
    pypsa_usa/
    gridstatus/
    lbnl_queued_up/
    osm/
    hifld/
    nrel_smart_ds/
    epri/
  exporters/                # bundle exporters
    to_sienna.py            # MATPOWER + EIA sidecar
    to_pmtiles.py           # tippecanoe driver
    to_duckdb.py            # in-browser DB for atlas
dbt/                        # dbt project (DuckDB target)
  models/
    silver/                 # per-source cleaning models
    gold_network/           # canonical analysis schema
    gold_atlas/             # canonical visualization schema
    gold_market/            # canonical market schema
bundle/                     # snapshot_YYYYMMDD/ output directories
tests/
```

## Running

```bash
uv sync
uv run dagster dev               # Dagster UI on :3000
uv run dbt run --profiles-dir dbt --project-dir dbt
```

A snapshot bundle is produced by:

```bash
uv run dagster job execute -j build_snapshot --config date=$(date +%Y-%m-%d)
```

See `../README.md` for how this fits into the wider gridagent platform.
