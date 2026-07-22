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
| 2026-07-22 | gemma4:26b | 43/200 (paused) | 0.0% | 0.0% | partial first baseline, strict scorer |

Partial-run failure breakdown (43 tasks: general 20, powerflow 20,
infeasibility 3; raw rows in `baseline_partial_gemma4_26b_20260722.jsonl.txt`):

- **15 wrong/missing tool** — the real capability gap. Dominated by skipped
  loader/setup steps: `load_distribution_network` missed 13×, `load_load`
  10×, `load_transmission_network` 4×.
- **14 right tool, wrong args** — near-misses, partly scorer strictness
  (e.g. `capacitor` vs `capacitors`); a leniency pass would recover some.
- **14 response errors** — malformed/unparseable model output; investigate
  whether prompt or extraction is at fault before blaming the model.
- Tool-set coverage (all GT tools present, ignoring args and order): only
  **3/43** — so the zero is mostly genuine, not scorer artifact.

Read: gemma4-class models don't have setup-step discipline over a 108-tool
catalog. This is the exact behavior Wayne's fixed workflows + verifier
exist to compensate for, and a concrete argument for codified process
knowledge (ledger brief §7) over raw planning.

## Relationship to Wayne

This evals the *model*, not the full Wayne planner loop (verifier,
retrieval, ledger consultation are not in the loop). Next steps if we want
them: (1) swap in Wayne's actual planner prompt scaffold to measure the
scaffold's contribution; (2) family-level error analysis → trajectory
exemplars for the store (fuzzy process knowledge, ledger brief §7).
