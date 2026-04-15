# gridagent

Autonomous interconnection-study and market-simulation platform built on
NREL Sienna and a PowerChain-style verifiable agent loop.

> This tree is the in-progress scaffold for the plan at
> `/root/.claude/plans/gentle-exploring-starfish.md`. All packages are
> wired-up skeletons — schemas, registries, and seams are in place;
> end-to-end execution is not yet hooked up. See each subdirectory's
> README for what's stubbed.

## Packages

| Package | Lang | Phase | Role |
|---|---|---|---|
| `gridagent-data/` | Python (Dagster + dbt + DuckDB) | 1 | ETL: `bronze → silver → gold_{network,atlas,market}` from PUDL, PyPSA-USA, GridStatus, LBNL Queued Up, OSM, HIFLD, NREL SMART-DS, EPRI, GEM. |
| `gridagent-julia/` | Julia 1.10 (PowerSystems.jl) | 2–3 | NREL Sienna stack: power flow, N-1 LODF screening, UC+ED PCM. `Executor` abstraction (`local_cpu` / `madnlp_gpu` / `distributed`) hides hardware from the agent. |
| `gridagent-tools/` | Python | 4 | Typed tool surface (data / scenario / study). Single registry; same callable used in-process and over MCP. |
| `gridagent-mcp/` | Python | 4 | Thin MCP server re-exporting `gridagent-tools` for external clients (Claude Desktop, Cursor). MCP is a transport, not the framework. |
| `gridagent-orchestrator/` | Python (Anthropic SDK) | 4.5–4.6 | PowerChain-style agent loop: trajectory store → context assembler → planner LLM → tool call → rule-based verifier → durable episode log. |
| `gridagent-atlas/` | TypeScript (MapLibre + PMTiles + DuckDB-WASM) | 5 | Static web atlas over `gold_atlas` and `gold_market`. Scenario overlays from orchestrator episodes. |

## How the pieces talk

```
gold_network ──► to_sienna.py ──► gridagent-julia (run.jl)
                                    ▲
gold_atlas   ──► to_pmtiles.py ──► gridagent-atlas
gold_market  ──► to_duckdb.py  ──► (atlas + tools)
                                    ▲
                            gridagent-tools  ◄─── gridagent-orchestrator
                                    ▲
                            gridagent-mcp (transport)
```

Two invariants worth defending:

1. **The orchestrator never sees CPU vs GPU vs distributed** — that lives
   behind the Julia `Executor` type, selected per-tool via an `executor=`
   string argument.
2. **Every tool returns `(value, signal)`** — the verifier reads `signal`
   only, so its decisions are reproducible and don't depend on parsing
   free-form payloads.

## What we deliberately don't build

- A re-derivation of EIA/FERC/CEMS forms (we ingest PUDL's parquet release).
- Our own electrical solver — PowerSystems.jl + PowerFlows.jl + PowerSimulations.jl.
- Our own MCP framework — we use the standard `mcp` SDK as a transport.
- Distribution grid in v1 (Phase 7).
- A non-US dataset in v1 (schema is global-ready; US first).
- A backend tile server — PMTiles + DuckDB-WASM = fully static atlas.

## Reference

- Plan: `/root/.claude/plans/gentle-exploring-starfish.md`
- PowerChain (verifier + dynamic context): arXiv 2508.17094
- NREL Sienna: https://nrel-sienna.github.io/PowerSystems.jl/
- PowerSimData (read-only inspiration): `../powersimdata/`

## Repo conventions

- Python: `uv` for dependency management, `ruff` lint, `pytest`.
- Julia: standard `Pkg`, run with `julia --project gridagent-julia/run.jl ...`.
- TypeScript: `pnpm`, Vite.
- All packages target Python ≥ 3.11 / Julia 1.10 / Node ≥ 20.
