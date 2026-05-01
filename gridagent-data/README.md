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

### Local bring-up (desktop validation)

End-to-end path from a blank machine to a browseable atlas:

```bash
# 1. Pull the source data we have loaders for (bronze layer).
uv run python -m gridagent_data.cli ingest rts_gmlc
uv run python -m gridagent_data.cli ingest pudl

# 2. Build the silver + gold marts with dbt. Target DB lives at
#    $DATA_ROOT/warehouse.duckdb (default: ./data_root/warehouse.duckdb).
uv run python -m gridagent_data.cli dbt build

# 3. Export the warehouse into an atlas-friendly bundle. The `bundle`
#    command writes bundle.duckdb (DuckDB-WASM) + one PMTiles per layer,
#    and — with --atlas-public — mirrors them into the Vite dev server.
uv run python -m gridagent_data.cli bundle \
    --atlas-public ../gridagent-atlas/public

# 4. Run the frontend.
cd ../gridagent-atlas && npm install && npm run dev
```

`tippecanoe` is optional at step 3: the bundle command falls back to
writing intermediate GeoJSON (still viewable via deck.gl) so the atlas
can render without installing the native binary first.

### Daily refresh (market + atlas bundle)

Use `refresh-daily` to keep atlas artifacts fresh with one command:

```bash
cd gridagent-data
uv sync && source .venv/bin/activate

# Optional but recommended for market partitions:
export GRIDSTATUS_API_KEY=...

python -m gridagent_data.cli refresh-daily \
  --atlas-public ../gridagent-atlas/public
```

- Default day is **yesterday (UTC)**.
- GridStatus partition failures are logged and skipped so bundle export still runs.
- Queue feed is pulled automatically from `GRIDAGENT_QUEUE_CSV_URL` when set.
- `dbt run` is used (not `dbt build`) so daily refresh is not blocked by test failures.

Queue feed contract (CSV columns expected by the silver model):

`project_id,snapshot_date,iso_region,queue_status,fuel_type,capacity_mw,queue_date,proposed_completion_date,point_of_interconnection,poi_latitude,poi_longitude,source,license`

Queue feed providers:

- `GRIDAGENT_QUEUE_PROVIDER=csv_url` (default) with `GRIDAGENT_QUEUE_CSV_URL=...`
- `GRIDAGENT_QUEUE_PROVIDER=interconnection_fyi_public` (uses public state pages;
  emits deterministic jittered coordinates around state centroids because source
  pages do not include exact lat/lon per project).

Run it every day via cron (example: 06:10 local time):

```bash
10 6 * * * cd /abs/path/to/wayne/gridagent-data && source .venv/bin/activate && python -m gridagent_data.cli refresh-daily --atlas-public ../gridagent-atlas/public >> ../data_root/refresh.log 2>&1
```

See `../README.md` for how this fits into the wider gridagent platform.
