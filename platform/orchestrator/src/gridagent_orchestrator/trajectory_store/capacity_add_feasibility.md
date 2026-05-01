# Interconnection capacity-add feasibility

**Goal pattern:** "Can the grid absorb <N> MW of <fuel> at <location>
without N-1 thermal violations? If not, what upgrades are needed?"

This is the canonical interconnection-study question. The output the user
cares about is *either* "feasible, here's the evidence" *or* "here's the
upgrade cost envelope."

**Decision points & expected tool sequence:**

1. `query_grid(table="buses", filters={"zone": "<region>"})` and
   `query_grid(table="generators", filters={"bus_id": "<candidate>"})` to
   confirm the point of interconnection (POI) exists and has headroom.
2. `create_scenario(name="poi_<bus>_<fuel>_<MW>",
    change_table={"add_plant": [{"bus_id": "<bus>", "fuel": "<fuel>",
    "p_max_mw": <N>, "p_min_mw": 0}]})`.
3. `run_power_flow(scenario_id)` — must converge before N-1.
4. `run_n1_contingency(scenario_id)`.
   - `signal.n_overloads == 0` → **report feasible.** Summarize the headroom
     (worst pre-existing base-case loading) and stop.
   - `signal.n_overloads > 0` → enter upgrade-search loop (step 5).
5. Upgrade-search loop, bounded to 3 iterations:
   a. Identify the most-frequently overloaded monitored branch across the
      top 10 `value.ranking` rows.
   b. `create_scenario(name=<base>+"_upgrade_v<n>",
       change_table={"add_branch": [{...parallel on that branch...}]})`.
   c. `run_n1_contingency` on the upgraded scenario.
   d. If `worst_loading_pct < 100` → report the upgrade set as the network
      deliverability cost.
6. Final summary must list: POI, injection size, pre-upgrade violations,
   upgrade set (if any), post-upgrade worst loading.

**Anti-pattern:** never recommend a capacity-add as feasible on the basis of
power flow alone without an N-1 screen; that is the #1 study-quality
failure mode in real interconnection queues.
