# DistGrid-AgentBench planning eval

Evaluates the planner model Wayne runs on (local Ollama by default) against
[DistGrid-AgentBench](https://github.com/emmanuelbadmus/DistGrid-AgentBench):
200 distribution-grid analysis tasks across ten families (BESS, PV, EV, GFI,
DSSE, DHC, power flow, infeasibility, combined T&D, general), each with a
canonical ground-truth tool workflow.

## What is measured

The **planning** capability the Wayne agent depends on: given a
natural-language grid question and a catalog of 108 tools (names +
descriptions only), emit the correct tool workflow. Nothing is executed —
the plan is scored against the benchmark's canonical workflow graph. This
sidesteps the parts of the benchmark that are not redistributable (feeder
networks, GIS data, network tool implementations are proprietary and
excluded upstream).

## Metrics (see `scorer.py`)

- **P@1** — task success: every ground-truth step appears in the plan, in
  order, with matching tool name and arguments.
- **precision** — 1.0 only if the plan contains zero extra tool calls
  (upstream's definition).
- **hallucinated tools** — plans citing tool names not in the manifest.

Our scorer is an independent strict re-implementation; the upstream
evaluator adds per-family leniency rules (implicit network loads,
query-conditional optional arguments) that we deliberately omit. Treat our
numbers as a **strict lower bound**, comparable across our own runs (the
point: tracking Wayne's planner model over time), not directly against
upstream-published numbers.

## Why we fetch instead of vendor

The benchmark was built by a PIQ advisor and we have permission to use it
freely (trn, 2026-07-22). We still don't vendor it: `fetch.py` clones the
repo at a pinned commit into `data_root/benchmarks/` (gitignored) at eval
time, which keeps 200 tasks + reference solutions out of our tree and
leaves upstream as the single source of truth. The pin is what makes runs
comparable; bump it deliberately. Vendor later only if hermetic CI needs it.

## Run

```bash
python3 fetch.py                       # clone at the pin into data_root/benchmarks/
python3 test_scorer.py                 # scorer unit tests (also pytest-compatible)
python3 planning_eval.py \
  --benchmark-dir data_root/benchmarks/DistGrid-AgentBench \
  --model gemma4:26b                   # full 200-task run, ~75 min local
```

Useful flags: `--families general,powerflow` to subset, `--limit N` for a
smoke run, `--base-url` for a non-Ollama endpoint. Results land in
`results/planning_<model>_<stamp>.jsonl` with a per-family summary table on
stdout.

## Baseline results

| date | model | tasks | P@1 | precision | notes |
|---|---|---|---|---|---|
| 2026-07-22 | gemma4:26b | 200 | _running_ | _running_ | first baseline, strict scorer |

## Relationship to Wayne

This evals the *model*, not the full Wayne planner loop (verifier,
retrieval, ledger consultation are not in the loop). Next steps if we want
them: (1) swap in Wayne's actual planner prompt scaffold to measure the
scaffold's contribution; (2) family-level error analysis → trajectory
exemplars for the store (fuzzy process knowledge, ledger brief §7).
