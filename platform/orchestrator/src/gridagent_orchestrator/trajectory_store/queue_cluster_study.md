# Interconnection queue cluster study

**Goal pattern:** "What happens to the grid if we interconnect the next
cluster of <N> projects from the queue in <ISO>?"

Cluster studies are the real workhorse of ISO planning. The agent's job is
to co-model the cluster as a single compound scenario rather than studying
each project in isolation.

**Decision points & expected tool sequence:**

1. `query_grid(table="generators", limit=50)` to see the existing fleet
   shape in the region of interest.
2. Build the cluster as a single `add_plant` list — one entry per queued
   project:
   `create_scenario(name="queue_cluster_<iso>_<yyyymm>",
    change_table={"add_plant": [
      {"bus_id": ..., "fuel": ..., "p_max_mw": ..., "p_min_mw": 0},
      {"bus_id": ..., "fuel": ..., "p_max_mw": ..., "p_min_mw": 0},
      ...
    ]})`.
3. `run_power_flow(scenario_id)`.
   - `signal.converged == false` → the cluster is infeasible at base case;
     report which buses can't absorb their injection and stop.
4. `run_n1_contingency(scenario_id)`.
5. Attribute each overloaded outage to the most-likely cluster contributor
   by sensitivity (inspect whether the overloaded monitored branch is
   electrically close to a single cluster project or to a group). The
   agent reports attribution, not upgrades — upgrade-sizing across a
   cluster is a separate episode.

**Anti-pattern:** do not study the cluster one project at a time; the
non-linearities are the point. Screening sequentially will under-count
violations by a factor of 2–5×.
