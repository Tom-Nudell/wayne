# Canonical Schema

Three independent gold marts share dimension keys but otherwise evolve
independently. Downstream tools bind to these contracts.

## `gold_network` — analysis-grade

The Sienna export reads from these tables.

| Table | Grain | Notes |
|---|---|---|
| `gold_network__buses` | one row per electrical bus | TBD; first source: PyPSA-USA |
| `gold_network__branches` | one row per AC branch | TBD; HIFLD geometry + OSM voltage refinement |
| `gold_network__generators` | one row per generator unit | First slice: PUDL EIA-860 |
| `gold_network__loads` | one row per load | TBD; FERC-714 + EIA-861 |
| `gold_network__dclines` | one row per DC link | TBD |

### Conflict resolution rules

- **Generators**: PUDL EIA-860 is the master for US units. PyPSA-USA aggregations
  are kept as a separate column for downstream consumers that prefer the bus-level
  rollup. Non-US authority is deferred until we identify a fully-open global source
  (Global Energy Monitor's commercial-tier trackers are out of scope for v1).
- **Branches**: HIFLD geometry; OSM `voltage` tag refines voltage class when HIFLD
  reports a wider range. Conflicts logged as dbt test warnings, not failures.

## `gold_atlas` — visualization-grade

| Table | Grain | Notes |
|---|---|---|
| `gold_atlas__infrastructure_features` | one row per physical thing | Open-set `kind` |

`kind` discriminator (open-set, but currently expected values):

- `plant` — generation plant point
- `unit` — generator unit (a plant typically has multiple units)
- `substation` — substation footprint or point
- `transmission_line` — line geometry
- `data_center` — data center site
- `gas_pipeline` — gas pipeline geometry
- `distribution_feeder` — distribution feeder topology (Phase 7)

## `gold_market` — market data

| Table | Grain | Notes |
|---|---|---|
| `gold_market__lmp_hourly` | (iso, node, interval_start_utc) | First source: GridStatus |
| `gold_market__load_hourly` | (ba, interval_start_utc) | EIA-930 + GridStatus |
| `gold_market__queue_snapshot` | one row per queue request per snapshot | LBNL Queued Up |

## Provenance columns

Every gold row carries:

- `sources` (array<varchar>) — source layers that contributed to the row
- `licenses` (array<varchar>) — license tags matching `sources`

The atlas frontend renders these in popovers; the `to_pmtiles` exporter
preserves them as feature properties.
