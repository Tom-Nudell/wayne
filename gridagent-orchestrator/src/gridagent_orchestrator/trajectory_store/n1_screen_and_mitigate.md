# N-1 contingency screen + mitigation

**Goal pattern:** "Add X MW of <fuel> at <location>; identify N-1 overloads
and propose a mitigation."

**Decision points & expected tool sequence:**

1. `query_grid(table="atlas.infrastructure_features", filters={...})` to locate
   the target bus / substation.
2. `create_scenario(name=<descriptive>, change_table={"add_plant": [{...}]})`.
3. `run_power_flow(scenario_id)` — sanity check; verifier must ADVANCE.
4. `run_n1_contingency(scenario_id)`.
   - `signal.monotone == false` → ABORT (numerical bug; do not paper over).
   - `signal.n_overloads == 0` → no mitigation needed; report and end.
   - `signal.n_overloads > 0` → ADVANCE; planner inspects `value.ranking`
     for the worst contingency / monitored line pair.
5. Mitigation: `create_scenario(name=<base>+"_uprate",
   change_table={"scale_branch_capacity": {<branch_id>: 1.5}})` derived from
   the worst-overload pair returned in step 4.
6. `run_n1_contingency(scenario_id_v2)` — verify mitigation reduces
   `value.ranking[0].loading_pct` below 100%.

**Stopping rule:** at most 3 mitigation iterations per episode; if not solved,
escalate to user.
