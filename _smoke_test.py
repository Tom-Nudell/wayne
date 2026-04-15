"""End-to-end smoke test: list -> create scenario -> run N-1 contingency.

Drives the public tool surface (gridagent_tools.TOOL_REGISTRY) the way the
orchestrator will, but with a hardcoded plan instead of an LLM. Exists to
prove the platform actually runs against the RTS-GMLC snapshot we built.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.environ.setdefault("GRIDAGENT_DATA_ROOT", str(ROOT / "data_root"))
os.environ.setdefault("GRIDAGENT_SCENARIO_ROOT", str(ROOT / "data_root" / "scenarios"))

from gridagent_tools import TOOL_REGISTRY  # noqa: E402

print("Registered tools:", sorted(TOOL_REGISTRY))
print()

# 1. List snapshots.
listed = TOOL_REGISTRY["list_data_snapshots"].fn()
print(f"list_data_snapshots → signal={listed.signal}")
for s in listed.value["snapshots"]:
    print(f"  - {s['id']}  counts={s['counts']}")
assert listed.signal["count"] >= 1, "Expected at least one snapshot."
snapshot_id = listed.value["snapshots"][0]["id"]
print()

# 2. Inspect a few generators via query_grid (real DuckDB query).
queried = TOOL_REGISTRY["query_grid"].fn(table="generators", limit=3)
print(f"query_grid(generators, limit=3) → signal={queried.signal}")
for row in queried.value["rows"]:
    print(f"  - {row['generator_id']:18s}  bus={row['bus_id']}  fuel={row['fuel']:14s}  Pmax={row['p_max_mw']:6.1f} MW")
print()

# 3. Create a baseline scenario (empty change-table).
baseline = TOOL_REGISTRY["create_scenario"].fn(
    name="baseline_rts", change_table={}, snapshot_id=snapshot_id
)
print(f"create_scenario(baseline) → signal={baseline.signal}")
baseline_id = baseline.value["scenario_id"]

# 4. Run baseline N-1 contingency screen.
n1_base = TOOL_REGISTRY["run_n1_contingency"].fn(scenario_id=baseline_id, executor="pandapower")
print(f"run_n1_contingency(baseline) → signal={n1_base.signal}")
print(f"  ranking_total={n1_base.value['ranking_total']}, top 5:")
for o in n1_base.value["ranking"][:5]:
    print(f"  · outage={o['outage']:6s}  monitored={o['monitored']:6s}  "
          f"flow={o['post_flow_mw']:8.1f} MW  rating={o['rating_mva']:6.1f}  loading={o['loading_pct']:6.1f}%")
print()

# 5. Stress scenario: scale all loads up 30 %, take the heaviest branch out of service.
branches = TOOL_REGISTRY["query_grid"].fn(
    table="branches", filters={"in_service": True}, limit=200
).value["rows"]
heaviest_branch = max(branches, key=lambda b: b["rating_a_mva"])["branch_id"]

stress = TOOL_REGISTRY["create_scenario"].fn(
    name="stress_30pct_load_minus_heaviest_branch",
    change_table={
        "scale_load": 1.30,
        "out_of_service_branches": [heaviest_branch],
    },
    snapshot_id=snapshot_id,
)
print(f"create_scenario(stress) → signal={stress.signal}")
stress_id = stress.value["scenario_id"]

n1_stress = TOOL_REGISTRY["run_n1_contingency"].fn(scenario_id=stress_id, executor="pandapower")
print(f"run_n1_contingency(stress) → signal={n1_stress.signal}")
print(f"  ranking_total={n1_stress.value['ranking_total']}, top 5:")
for o in n1_stress.value["ranking"][:5]:
    print(f"  · outage={o['outage']:6s}  monitored={o['monitored']:6s}  "
          f"flow={o['post_flow_mw']:8.1f} MW  loading={o['loading_pct']:6.1f}%")
print()

# Sanity-check: stress scenario should have at least as many overloads as baseline.
assert n1_stress.signal["n_overloads"] >= n1_base.signal["n_overloads"], (
    f"Stress scenario unexpectedly less stressed than baseline: "
    f"{n1_stress.signal['n_overloads']} vs {n1_base.signal['n_overloads']}"
)
assert n1_base.signal["monotone"] and n1_stress.signal["monotone"], "Ranking must be monotone."
print("OK — all signals consistent and rankings monotone.")
