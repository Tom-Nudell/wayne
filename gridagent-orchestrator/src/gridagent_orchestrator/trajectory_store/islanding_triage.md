# Islanding / bridge-branch triage

**Goal pattern:** "Which outages would split the system? How resilient is
the current topology?"

**Decision points & expected tool sequence:**

1. `create_scenario(name="baseline", change_table={})`.
2. `run_n1_contingency(scenario_id)`.
3. Read `value.islanding_outages` — a list of branch IDs whose N-1 outage
   disconnects the network. Verifier decision is always ADVANCE (islanding
   is information, not a thermal overload).
4. For each islanding branch, `query_grid(table="branches",
   filters={"branch_id": "<id>"})` to report the from/to buses and
   voltage, so the user knows *where* on the system the bridge is.
5. Report: count of islanding branches, their endpoints, their voltage
   class. If 0 → the N-1 topology is robust; if > 10 → the system has
   significant radial exposure and the user should consider looping
   study.

**Anti-pattern:** mixing islanding branches into the thermal-overload
ranking. They are a separate class of result and mixing them makes the
ranking look like the system is on fire when it is simply radial.
