# N-1 contingency screen + mitigation

**Goal pattern:** "Add X MW of <fuel> at <location>; identify N-1 overloads
and propose a mitigation."

**Decision points & expected tool sequence:**

1. `query_grid(table="generators", filters={"fuel": "<fuel>"}, limit=10)` or
   `query_grid(table="buses", filters={"zone": "<zone>"})` to orient yourself
   in the network and pick a target bus.
2. `create_scenario(name=<descriptive>, change_table={"add_plant": [{...}]})`.
   An `add_plant` entry needs `bus_id`, `fuel`, `p_max_mw`, optionally
   `p_min_mw`.
3. `run_power_flow(scenario_id)` — sanity check; verifier must ADVANCE
   before doing anything expensive.
4. `run_n1_contingency(scenario_id)`.
   - `signal.monotone == false` → ABORT (numerical bug; do not paper over).
   - `signal.n_overloads == 0` → no mitigation needed; report and end.
   - `signal.n_overloads > 0` → ADVANCE; planner inspects `value.ranking`
     for the worst (outage, monitored) pair.
   - `signal.n_islanding > 0` → note the bridge branches in the final
     summary but **do not** treat them as overloads; they are connectivity
     events, not thermal violations.
5. Mitigation candidates (pick one, do not combine blindly on the first try):
   - **Parallel circuit** on the worst monitored line:
     `create_scenario(name=<base>+"_parallel",
      change_table={"add_branch": [{"from_bus_id": ..., "to_bus_id": ...,
      "r_pu": ..., "x_pu": ..., "rating_a_mva": ...}]})` — copy the existing
     branch's impedance as a template.
   - **Generation re-dispatch** via `scale_plant_capacity`: scale *up* a
     generator past the bottleneck, scale *down* a generator on the
     sending side.
6. `run_n1_contingency(scenario_id_v2)` — verify mitigation reduces
   `value.ranking[0].loading_pct` below 100 %.

**Stopping rule:** at most 3 mitigation iterations per episode; if still
overloaded, report what was tried and the residual worst loading to the user.
