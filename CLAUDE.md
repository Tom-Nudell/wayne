# Wayne

## Core

This project is part of the founder's project portfolio. The controlling document is `~/core`.

- Founder principles and agent rules: `~/core/me/principles.md` — read this first. It overrides everything else.
- This project's context and status: `~/core/projects/wayne.md`
- Company context: `~/core/piq/`

## What Wayne Is

Two tightly coupled layers:

1. **Data pipeline** — ingests and conflates public US grid data through a bronze→silver→gold pipeline (Dagster + dbt + DuckDB). Output is audit-grade geospatial data on US energy infrastructure.
2. **Simulation + agent platform** — NREL Sienna (Julia) for power flow and production cost modeling. Python orchestrator with a PowerChain-style agent loop. Typed tool surface via MCP.

The map visualization (`atlas/`, `grid-map-engineering-brief.md`) is both the human QA layer for verifying data quality AND a product surface. These roles are inseparable — the rigor required to make it correct as a QA tool is what makes it valuable as a product.

## Key Directories

| Path | Purpose |
|---|---|
| `platform/data/` | ETL pipeline (Dagster + dbt + DuckDB) |
| `platform/julia/` | NREL Sienna power system solver |
| `platform/orchestrator/` | PowerChain-style agent loop |
| `platform/tools/` | Typed tool surface (MCP-exposed) |
| `platform/mcp/` | MCP server wrapping tools |
| `platform/atlas/` | Map viewer (MapLibre + PMTiles + DuckDB-WASM) |
| `data_root/` | Scenarios and episode logs |

## Running

```bash
# Python packages (install from platform/ subdirectories)
uv sync  # or pip install -e . in each platform/* dir

# Julia solver
cd platform/julia && julia run.jl

# Atlas viewer
cd platform/atlas && pnpm dev
```

## Agent Rules

- Data quality is the moat. If the map looks wrong at any zoom level, fix the data before touching features.
- Every tool returns `(value, signal)` — the verifier reads `signal` only. Do not break this invariant.
- The orchestrator never sees CPU vs GPU vs distributed — that lives behind the Julia `Executor` type.
