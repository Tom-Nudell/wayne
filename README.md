# gridagent

Autonomous interconnection-study and market-simulation platform built on
NREL Sienna and a PowerChain-style verifiable agent loop.

End-to-end execution works today against the RTS-GMLC test system via a
pandapower backend stopgap; NREL Sienna (Julia) is the target production
engine. See each subdirectory's README for details.

## Packages

| Package | Lang | Phase | Role |
|---|---|---|---|
| `gridagent-data/` | Python (Dagster + dbt + DuckDB) | 1 | ETL: `bronze → silver → gold_{network,atlas,market}` from PUDL, PyPSA-USA, GridStatus, LBNL Queued Up, OSM, HIFLD, NREL SMART-DS, EPRI. (All fully-open licenses.) |
| `gridagent-julia/` | Julia 1.10 (PowerSystems.jl) | 2–3 | NREL Sienna stack: power flow, N-1 LODF screening, UC+ED PCM. `Executor` abstraction (`local_cpu` / `madnlp_gpu` / `distributed`) hides hardware from the agent. |
| `gridagent-tools/` | Python | 4 | Typed tool surface (data / scenario / study). Single registry; same callable used in-process and over MCP. |
| `gridagent-mcp/` | Python | 4 | Thin MCP server re-exporting `gridagent-tools` for external clients (Claude Desktop, Cursor). MCP is a transport, not the framework. |
| `gridagent-orchestrator/` | Python (OpenAI SDK → local Ollama) | 4.5–4.6 | PowerChain-style agent loop: trajectory store → context assembler → planner LLM → tool call → rule-based verifier → durable episode log. Default model: open-weight Gemma family. |
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

## V1 stance — open and local

Confirmed decisions for the first pass:

- **Open source only.** HiGHS for any MIP/LP work (sufficient for N-1, which
  doesn't need it anyway; revisit Gurobi-class solvers only when PCM at
  realistic scale demands it). All upstream data sources are CC-BY-4.0,
  ODbL, BSD/MIT, or US public domain. Mixed-license sources (e.g. GEM
  commercial-tier trackers) are deferred until we can confirm a fully open
  subset.
- **Open-weight LLM by default.** Orchestrator points at a local Ollama
  endpoint serving an open Gemma model. No hosted API key required.
  Hosted providers can be wired in later as alternative `LLM` backends for
  benchmarking — they are not the default.
- **Local hosting first.** No cloud dependency. The atlas is a static site
  that runs from `pnpm dev` or `pnpm preview`; bundles live on local disk.
- **Open license throughout.** Code under permissive license (TBD; default
  Apache-2.0 unless a package's upstream forces otherwise).

## What we deliberately don't build

- A re-derivation of EIA/FERC/CEMS forms (we ingest PUDL's parquet release).
- Our own electrical solver — PowerSystems.jl + PowerFlows.jl + PowerSimulations.jl.
- Our own MCP framework — we use the standard `mcp` SDK as a transport.
- Distribution grid in v1 (Phase 7).
- A non-US dataset in v1 (schema is global-ready; US first).
- A backend tile server — PMTiles + DuckDB-WASM = fully static atlas.
- A hosted LLM dependency in the default path.

## Aesthetic — a living network

Brand and domain are TBD; codename remains `gridagent`. The visual
language for the atlas (and any chrome that follows) is **mycelium / forest
floor** — the grid as a branching, breathing network, rendered in calm earth
tones. Alarm colors are reserved for scenario overlays so they read against
a quiet base. Working notes in `gridagent-atlas/BRANDING.md`.

## Reference

- PowerChain (verifier + dynamic context): arXiv 2508.17094
- NREL Sienna: https://nrel-sienna.github.io/PowerSystems.jl/
- PowerSimData (design inspiration for change-table DSL): https://github.com/Breakthrough-Energy/PowerSimData

## Desktop bring-up

End-to-end from a blank checkout. Everything below runs on a laptop — no
cloud, no API keys, no GPU. Pick either the **data-only** or the **full
agent** path depending on what you want to exercise.

### Prerequisites

- Python 3.11 + [`uv`](https://docs.astral.sh/uv/) (0.8.x)
- Node 20+ (for the atlas)
- Julia 1.10 (optional; only needed once we wire the Sienna backend in
  Phase 2–3; the pandapower backend stopgap in `gridagent-tools` runs
  without it)
- Ollama or another OpenAI-compatible local LLM server (only for the
  agent path; the offline smoke test drives the exact same tool surface
  via `FunctionModel` so CI doesn't need a GPU)

### Data + dbt + atlas

```bash
cd gridagent-data
uv sync && source .venv/bin/activate

# Bronze: pull RTS-GMLC (fast, ~100 KB) and PUDL (slower, ~500 MB).
python -m gridagent_data.cli ingest rts_gmlc
python -m gridagent_data.cli ingest pudl

# Silver + gold: dbt build reads from data_root/bronze and writes to
# data_root/warehouse.duckdb.
python -m gridagent_data.cli dbt build

# Atlas bundle: bundle.duckdb + one PMTiles per layer.
python -m gridagent_data.cli bundle --atlas-public ../gridagent-atlas/public

cd ../gridagent-atlas && npm install && npm run dev
# → http://localhost:5173 with RTS-GMLC substations and lines rendered.
```

### Agent loop

Offline (no LLM, scripted plan — the CI path):

```bash
python _orchestrator_smoke.py
# → Episode <id> OK; 4 tool calls executed.
```

Live (local LLM via Ollama, default model `gemma4:e12b`):

```bash
# Start the LLM server in one terminal:
ollama serve &
ollama pull gemma4:e12b  # or any tool-calling model; override with
                         # GRIDAGENT_LLM_MODEL / GRIDAGENT_LLM_BASE_URL

# In another terminal:
python -m gridagent_orchestrator.run \
    --goal "Load the RTS-GMLC snapshot, create a baseline scenario, and
            run an N-1 contingency screen. Summarise the worst overload."
# → Episode log at data_root/episodes/<id>.jsonl plus a plain-text summary.
```

## Repo conventions

- Python: `uv` for dependency management, `ruff` lint, `pytest`.
- Julia: standard `Pkg`, run with `julia --project gridagent-julia/run.jl ...`.
- TypeScript: `pnpm`, Vite.
- All packages target Python ≥ 3.11 / Julia 1.10 / Node ≥ 20.
