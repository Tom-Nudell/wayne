# Single-day production cost simulation

**Goal pattern:** "Run a 24-hour production cost simulation for <ISO> on
<date> and report nodal LMPs."

**Decision points & expected tool sequence:**

1. `query_lmp(iso, start, end)` — pull historical LMPs for cross-check
   (sanity-check oracle, not an input to PCM).
2. `create_scenario(name=<iso>+"_"+<date>, change_table={})`.
3. `run_production_cost(scenario_id, horizon_hours=24)`.
   - `signal.solver_status != "OPTIMAL"` → REPLAN (likely missing reserves
     constraint or transmission limit relaxation).
   - `signal.slack_mw > 50` → REPLAN; investigate which BA / hour is short.
   - Otherwise → ADVANCE. Compare `value.lmp_by_node` to the historical
     query; report mean / p95 deviation per ISO.

**Stopping rule:** PCM is expensive — at most one full re-run per episode;
beyond that, report the slack diagnosis to the user.
