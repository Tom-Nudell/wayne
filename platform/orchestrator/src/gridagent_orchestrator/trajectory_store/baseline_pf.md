# Baseline AC power flow

**Goal pattern:** "Run a baseline AC power flow on the latest snapshot."

**Decision points & expected tool sequence:**

1. `list_data_snapshots()` → confirm a bundle exists; pick the newest.
2. `create_scenario(name="baseline", change_table={})` → empty change-table.
3. `run_power_flow(scenario_id)`.
   - **If `signal.converged`** → report `value.max_mismatch_mw` and the slack-bus
     dispatch back to the user. Episode complete.
   - **If `!signal.converged`** → first retry uses a flat start (the verifier's
     RETRY decision; the planner switches `init="flat"`). If still
     non-convergent, replan: most often the change-table introduced an
     islanded bus.

**Anti-pattern:** never re-run the same study with identical arguments after a
non-convergence; the verifier will RETRY at most once.
