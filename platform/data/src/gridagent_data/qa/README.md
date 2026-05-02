# gridagent_data.qa

Visual QA gate for the data pipeline. Sits between `platform/data`'s build and tile promotion to the public R2 prefix. See `grid-map-engineering-brief.md` §7 for why this is the moat, not boring infra.

## Run

```bash
PYTHONPATH=platform/data/src python -m gridagent_data.qa.gate \
  --bundle-dir data_root/bundle/snapshot_latest
```

With a baseline for drift comparison:

```bash
PYTHONPATH=platform/data/src python -m gridagent_data.qa.gate \
  --bundle-dir data_root/bundle/snapshot_2026-04-30 \
  --baseline-dir data_root/bundle/snapshot_2026-04-01 \
  --json
```

Exit codes: `0` for pass / all skipped, `2` for any failure.

## Checks

| # | Module | Today | Phase 1 work |
|---|---|---|---|
| 1 | `density.py` | skipped | feature-count per layer per zoom; alert on >25% drift vs baseline |
| 2 | `coverage.py` | skipped | every state has non-zero feature count for layers tagged national |
| 3 | `visual.py` | skipped | render N reference viewports headless, pixel-diff vs baseline, manual review on >2% |
| 4 | `attribution.py` | skipped | every license-required attribution string present at the zoom levels its license demands |
| 5 | `conflation.py` | skipped | human-readable conflict/merge/drop report; warn over threshold; fail on changed-without-review |
| 6 | `licenses.py` | **real** | walks PMTiles + checks for matching `license.json` sidecars |

The license-sidecar check is the only one with real behavior in this skeleton — it walks the bundle dir and fails if any PMTiles is missing its sidecar. The exporter does not yet emit sidecars (Phase 1 work in `to_pmtiles.py`), so on real bundles this check currently fails; that's expected and tracked.

## Adding a check

1. Create `platform/data/src/gridagent_data/qa/<name>.py` with a single function `check_<name>(*, bundle_dir: Path, ...) -> CheckResult`.
2. Register it in `gate.py`'s `run_gate` list.
3. Update the table above and add a row to `__init__.py` if it's part of the public surface.
4. If the check produces artifacts (diff PNGs, CSVs), populate `CheckResult.artifact_paths` so CI can upload them.
