# Single-day production cost simulation

**Goal pattern:** "Run a 24-hour production cost simulation on the latest
snapshot and report nodal LMPs."

Current default backend is the pandapower DC-OPF stopgap; Sienna is the
intended high-fidelity backend once the container is wired up. Both
backends return the same `value` / `signal` shape so the trajectory does
not change when we swap engines.

**Decision points & expected tool sequence:**

1. `list_data_snapshots()` → pick the newest bundle.
2. `create_scenario(name="pcm_baseline", change_table={})`.
3. `run_production_cost(scenario_id, horizon_hours=24)`.
   - `signal.solver_status != "OPTIMAL"` → REPLAN. The most common cause is
     insufficient generation to meet load; scale a cheap gen up with
     `scale_plant_capacity` and retry.
   - `signal.slack_mw > 50` → REPLAN. Investigate which bus is short by
     inspecting `value.bus_slack_mw`.
   - Otherwise → ADVANCE. Report mean and p95 LMPs across buses, the
     top 3 most-expensive buses, and the total production cost.

**Stopping rule:** PCM is expensive — at most one full re-run per episode;
beyond that, report the slack diagnosis to the user.
