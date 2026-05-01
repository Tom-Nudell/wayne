# Stress-test scenario

**Goal pattern:** "How does the grid respond to a heat-wave load surge / a
major branch outage?"

**Decision points & expected tool sequence:**

1. `list_data_snapshots()` → pick the newest snapshot.
2. `query_grid(table="branches", limit=200)` and sort by `rating_a_mva`
   in your own reasoning to identify the heaviest transfer corridors.
3. `create_scenario(name="stress_<descriptor>",
    change_table={"scale_load": 1.30,
                  "out_of_service_branches": ["<heaviest_branch_id>"]})`.
   Use a single compound scenario rather than two sequential ones so the
   two stressors compose correctly.
4. `run_power_flow(scenario_id)`.
   - `signal.converged == false` → the stress combination is infeasible in
     the base case. Report that and stop — contingency analysis on top of
     an unsolvable base case is meaningless.
5. `run_n1_contingency(scenario_id)`.
   - Baseline RTS-GMLC at 1.30× load typically produces thousands of
     overloads; that is not a bug. Focus the report on the **top 5 worst**
     pairs from `value.ranking`, not raw counts.
6. Report: worst outage, most-loaded monitored branch, loading percentage,
   and which bridge branches (`value.islanding_outages`) would additionally
   island the system if taken out.

**Anti-pattern:** do not propose mitigation for a stress test; the goal is
*characterization*, not *repair*.
