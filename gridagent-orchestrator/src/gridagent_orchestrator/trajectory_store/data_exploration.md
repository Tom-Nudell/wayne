# Data exploration & orientation

**Goal pattern:** "What generators / branches / buses are in the snapshot?
Show me the top N by <attribute>." Used both by humans exploring the
dataset and by the planner in the first step of any study.

**Decision points & expected tool sequence:**

1. `list_data_snapshots()` — always first; confirms which snapshots exist
   and their row counts per table.
2. One or more `query_grid(table, filters, limit)` calls, using *narrow*
   filters. Rules:
   - Request only as many rows as you need for the decision you are about
     to make. Default `limit=50`. Raise to 200 only if you're scanning for
     a min/max. Never request > 1000.
   - Prefer equality filters (`{"fuel": "solar"}`) over returning
     everything and sifting.
   - If a table is very wide, narrow by the most-discriminative column
     first (`zone` / `iso` for buses, `fuel` for generators,
     `from_bus_id` for branches).
3. The returned rows are for **your planning**, not for the user's final
   report. Summarize them; do not paste them verbatim into the summary.

**Anti-pattern:** calling `query_grid` with no filters and `limit=1000`
just to "see the data" — that floods the context window and the model
tends to lose the original goal.
