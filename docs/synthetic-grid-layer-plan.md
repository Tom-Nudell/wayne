# Plan — Microsoft-style synthetic transmission grid as a Wayne data layer

**Status:** draft, awaiting review
**Owner:** TBD
**Branch:** `claude/plan-synthetic-data-layer-cZ3Hw`
**Reference:** Microsoft Research, *Building a realistic electric transmission
grid dataset at scale: a pipeline from open datasets* — research blog post,
2026.

---

## 1. Why this exists

Today `platform/data/dbt/models/gold_network/` is fed by exactly one upstream:
RTS-GMLC, a 73-bus three-area test system. PyPSA-USA is wired in at the
bronze layer (`sources/pypsa_usa/bronze.py`) but does not yet promote into
silver or gold. The gap in the middle is real:

- **RTS-GMLC** — 73 buses. Toy. Fine for solver smoke tests, useless for any
  study that depends on continental topology, congestion patterns, or
  realistic generator siting.
- **PyPSA-USA** — accurate balanced-area model; production-grade, but its
  topology is a clustered abstraction of HIFLD lines, not a synthesised
  full-detail grid. Different research question, different artefact.
- **Microsoft-style synthetic grids** — buses sited from OpenStreetMap
  substations, generation allocated from EIA, demand allocated from Census,
  electrical parameters back-fit from standard engineering references, and
  the whole thing certified by an AC-OPF solve. Scales arbitrarily, from
  state-level (~11 buses) to the full Eastern Interconnection
  (~21,697 buses), with peak and off-peak demand cases.

Adding the Microsoft layer gives the Sienna stack (`platform/julia/`) a
third independent topology family to study against, and gives the atlas a
synthetic-vs-observed visual contrast that maps directly onto the
"infrastructure as we render it" vs. "infrastructure as the model
believes" axis customers ask about.

## 2. What Microsoft built (relevant subset)

From the blog post:

| Stage | Inputs | Output |
|---|---|---|
| Geographic skeleton | OpenStreetMap power corridors + substations | Candidate bus locations + branch corridors |
| Augmentation | EIA generation + fuel mix; Census population for demand | Sited generators per bus; load per bus |
| Parameter estimation | Standard engineering refs (line impedance, ratings by voltage class) | Per-branch R/X/B, MVA limits |
| Circuit approximation | — | One representative line per corridor instead of every parallel circuit |
| Validation | Solver (AC-OPF) | Solvable case; reject and refit on infeasibility |

Output is a family of MATPOWER-shaped cases, scoped per state or per
interconnection, with peak and off-peak demand variants.

## 3. Goal

Add `ms_synthetic_grid` as a first-class **source family** in
`platform/data/`, on equal footing with `rts_gmlc` and `pypsa_usa`:

- Bronze: pinned, hash-verified ingest of the Microsoft-released dataset.
- Silver: per-case cleaning models in `dbt/models/silver/ms_synthetic_grid/`.
- Gold: union into the existing `gold_network__{buses,branches,generators,loads}.sql`
  tables, ID-namespaced as `MS-<scope>-<n>` (e.g. `MS-EI-12345` for Eastern
  Interconnection bus 12345).
- Atlas: synthetic buses and branches exported into `gold_atlas` as
  `infrastructure_features` with a `synthetic: true` flag, license sidecar,
  and a separate PMTiles archive so the frontend can toggle it.
- QA: existing density / coverage / license gates apply unchanged; one new
  check — AC-OPF feasibility re-solve via pandapower — gates promotion of
  any synthetic case to gold.

Non-goal: re-implementing the Microsoft pipeline ourselves from scratch.
See §6 for why and when that changes.

## 4. Decision: adopt vs. re-derive

Two paths.

**Path A — Adopt the published artefact.** Treat Microsoft's released
dataset the same way we treat RTS-GMLC: pin a commit / archive URL, fetch
the cases, write a manifest with SHA-256 and license string, normalise
through silver into gold. Fast (≈ 1 week wall-clock to wire end-to-end),
deterministic, and the upstream provenance points at peer-reviewed work.

**Path B — Re-derive in-house.** Build a Wayne-native pipeline that takes
OSM + EIA-860M + Census, runs corridor extraction → augmentation →
parameter estimation → AC-OPF validation, and emits synthesised cases.
Slow (≈ 4–8 weeks), more moving parts, but gives us sovereign control over
the algorithm, lets us extend beyond CONUS, and removes any redistribution
concern.

**Recommendation: Path A first, Path B as a Phase-2 fallback.**

Path A unblocks Sienna / atlas / orchestrator immediately and validates the
schema mapping under realistic load. The whole point of the open-data
pipeline is that the *output* is the contribution; reproducing it ourselves
adds no realism and costs weeks. We only commit to Path B if:

- Microsoft's release license is incompatible with our commercial atlas
  tier — needs explicit verification (see §10 OQ1), or
- the released cases stop being maintained, or
- we need geographies or load scenarios outside what they publish.

Schema work in Path A (silver models, gold ID namespace, QA hooks, atlas
flag) is reusable verbatim under Path B; the only piece thrown away is the
bronze loader. So Path A is not lock-in.

## 5. Architecture changes

```
platform/data/src/gridagent_data/
  sources/
    ms_synthetic_grid/              ← NEW
      __init__.py
      bronze.py                     ← pinned fetch + SHA256 manifest
      cases.py                      ← case-family registry (state, II, scale)
      validate.py                   ← AC-OPF re-solve via pandapower

  qa/
    synthetic.py                    ← NEW: feasibility gate, see §7

dbt/models/
  silver/
    ms_synthetic_grid/              ← NEW
      _silver_ms_synthetic_grid__models.yml
      silver_ms_synthetic_grid__buses.sql
      silver_ms_synthetic_grid__branches.sql
      silver_ms_synthetic_grid__generators.sql
      silver_ms_synthetic_grid__loads.sql
      silver_ms_synthetic_grid__cases.sql   ← case dimension (scope, peak/off-peak)

  gold_network/
    gold_network__buses.sql         ← union ms_synthetic CTE
    gold_network__branches.sql      ← union ms_synthetic CTE
    gold_network__generators.sql    ← union ms_synthetic CTE
    gold_network__loads.sql         ← union ms_synthetic CTE
    gold_network__cases.sql         ← NEW: scenario dim shared by all sources

  gold_atlas/
    gold_atlas__infrastructure_features.sql   ← add synthetic bus + line rows

schema/models.py
  GridFeatureProperties             ← add `synthetic: bool`
  NetworkCase                       ← NEW: (case_id, scope, demand_scenario,
                                            n_buses, source, license)
```

Conventions held intentionally:

- ID namespacing follows the existing `RTS-<id>` pattern. Synthetic IDs are
  `MS-<scope>-<id>` where `scope` is one of `EI` (Eastern Interconnection),
  `WI` (Western), `TX` (ERCOT), or a USPS state code. This keeps cross-source
  joins unambiguous and makes synthetic IDs visually obvious in logs.
- Every gold row carries `sources: array<string>` and `licenses: array<string>`
  exactly as today. The synthetic case adds `"ms_synthetic_grid"` to the
  array on every contributed row; no schema change to the provenance columns.
- One PMTiles archive per case family (national, peak; national, off-peak;
  per-interconnection variants). The manifest decides what's visible at
  each tier.

## 6. Phasing

**Phase 1 — Bronze ingest (1–2 days).**
- Confirm Microsoft's release URL, license, and citation. Write
  `sources/ms_synthetic_grid/bronze.py` mirroring the shape of
  `sources/rts_gmlc/bronze.py`: pinned URL, streamed download to
  `data_root/bronze/ms_synthetic_grid/<case>/`, SHA-256, manifest JSON with
  source / license / retrieved_at.
- Stand up `sources/ms_synthetic_grid/cases.py` as a typed registry of the
  case families we plan to surface (start with three: ERCOT, the full
  Eastern Interconnection, and one state-scale exemplar). Keeping this
  explicit avoids a "we ingested everything because we could" debt.
- CLI: `python -m gridagent_data.cli ingest ms_synthetic_grid --case <id>`.

**Phase 2 — Silver normalisation (2–3 days).**
- Write four silver models (`buses`, `branches`, `generators`, `loads`)
  that read the bronze MATPOWER tables and project into the same column
  shape `silver_rts_gmlc__*` already uses. Drop the columns we don't carry
  forward (shunts, transformer tap data — Sienna reads those from a
  separate path; revisit at Phase 5).
- Add `silver_ms_synthetic_grid__cases.sql` to expose
  `(case_id, scope, demand_scenario, n_buses)` as a small dimension table.

**Phase 3 — Gold integration (1 day).**
- Extend each `gold_network__*.sql` model with a `ms_synthetic` CTE and
  `union all` it into the existing rts_buses / rts_branches / etc.
  output. ID prefix `MS-<scope>-`.
- Add `gold_network__cases.sql`. Backfill RTS-GMLC as a single
  `RTS-GMLC-DEFAULT` row in the same table so downstream joins are
  uniform.
- Update `_gold_network__models.yml` with column docs and tests
  (uniqueness on `bus_id`, FK from branches to buses) — same shape as today.

**Phase 4 — Atlas (1 day).**
- Extend `gold_atlas__infrastructure_features.sql` to emit one row per
  synthetic bus (`kind = 'substation'`, `synthetic = true`) and one row
  per synthetic branch (`kind = 'transmission_line'`).
- Add `synthetic: bool` to `GridFeatureProperties` in
  `schema/models.py`; regenerate `shared/schema/src/index.ts`.
- Add a per-case PMTiles export entry in
  `exporters/to_pmtiles.py::_TIPPECANOE_FLAGS` keyed on `synthetic_*`.
- Add a license sidecar entry for each synthetic PMTiles archive.

**Phase 5 — QA + Sienna (2–3 days).**
- New `qa/synthetic.py::feasibility_gate`: for each case, run AC-OPF via
  pandapower (already a Wayne dependency) and emit `feasible: bool` plus
  per-bus voltage and per-line loading summaries. The gate fails the
  promotion if AC-OPF doesn't converge. This re-certifies Microsoft's
  release on our own solver rather than trusting their CI.
- Extend `exporters/to_sienna.py` to materialise synthetic cases into the
  MATPOWER + EIA sidecar shape `platform/julia/` consumes. Smoke-run one
  N-1 contingency screen on the small-scale case to prove the seam.

**Phase 6 — Web product gating (0.5 day).**
- Synthetic layers default to **Pro** tier — they're a derived product,
  not raw public data, and the value is in the curation. Free tier still
  shows real plants / lines / substations.
- Add to `services/tile-worker/` the new layer IDs in the paid allow-list.
- Generated `/attribution` page picks up the new license sidecars
  automatically; no hand-edits.

Total: ~7–10 working days end-to-end, single owner.

## 7. QA gate additions

Existing gates in `platform/data/src/gridagent_data/qa/` apply unchanged
(density, coverage, attribution, licenses, conflation, visual regression).
One new gate:

- **`qa/synthetic.py::feasibility_gate`** — for each case, build a
  pandapower net from the gold tables, run AC-OPF, record convergence and
  per-bus voltage / per-line loading. Promotion to `data_root/bundle/` is
  blocked if any case fails to converge. Output is committed alongside
  build artefacts so we can audit what we shipped.

Aggregate sanity checks worth adding to `qa/synthetic.py` as well:

- Sum of installed capacity per state vs. EIA-860M totals — flag drift
  > 10%.
- Sum of peak demand per state vs. EIA-861 sales — flag drift > 15%.
- Branch count per voltage class — flag if any class is empty for a
  region we know has lines at that class.

These are cheap and catch the worst silent-corruption modes (e.g. unit
mismatches in import) without standing up a full visual regression.

## 8. Sienna-side changes

`exporters/to_sienna.py` is already MATPOWER-shaped. The only edits:

- Filter on `case_id` so a Sienna run targets one synthetic case, not
  every case unioned together.
- For the EIA sidecar, prefer the synthetic case's own generator metadata
  over PUDL where the two disagree (the synthetic case's `bus_id` linkage
  is authoritative; PUDL's `plant_id_eia` is a join key for fuel and
  technology only).

In `platform/julia/`: nothing to change. The MATPOWER shape is
self-describing; the executor abstraction means hardware selection is
already wired.

## 9. Atlas-side changes

- `shared/schema/src/index.ts` regenerated from `GridFeatureProperties`
  with `synthetic: boolean` (camelCased per the existing generator
  convention).
- `shared/map/` adds a paint style for synthetic vs. observed: same hue
  family (mycelium / forest-floor palette is preserved) but lower opacity
  and a different dash pattern on synthetic lines so the visual
  distinction is unmistakable at any zoom. Style lives next to the
  observed-line style; both consumed by `platform/atlas/` and `web/`.
- Layer toggle in `web/src/lib/map/` lets a user turn synthetic on/off
  independently of observed layers.

## 10. Open questions (must resolve before Phase 1 starts)

1. **License of the Microsoft release.** The blog post does not state one.
   Likely MIT / CDLA-Permissive / similar, but until confirmed in writing
   we cannot commit to redistribution via our R2 PMTiles archive. If the
   license forbids redistribution, the synthetic layer is dev-only until
   Path B re-derivation lands.
2. **Which cases to ingest in Phase 1.** Proposal: ERCOT, full Eastern
   Interconnection (peak), and one state-scale exemplar (Iowa or similar
   single-control-area state). Confirm with the user.
3. **Tier policy.** Synthetic cases proposed at Pro. If the licence allows
   free redistribution we could surface the smallest case at Free as a
   teaser. Confirm.
4. **Snapshot cadence.** Microsoft's release likely refreshes
   irregularly. Pin a commit / archive URL the same way we pin RTS-GMLC,
   and revisit on a quarterly basis rather than wiring it into the daily
   refresh path (synthetic cases don't change with the day).

## 11. Out of scope

- Generating our own synthetic cases (deferred — see Path B in §4).
- Distribution-grid synthetic data — Wayne already plans NREL SMART-DS
  and EPRI for that, handled separately in Phase 7 of the platform
  roadmap.
- International coverage — Microsoft's release is US-only.
- Time-series load profiles for synthetic buses — peak and off-peak
  snapshots only at v1. PCM extensions wait until `platform/julia/`
  consumes them.

## 12. Acceptance

Done when:

- `python -m gridagent_data.cli ingest ms_synthetic_grid --case ei` writes
  bronze + manifest.
- `python -m gridagent_data.cli dbt build` produces a gold_network
  containing both `RTS-` and `MS-EI-` rows.
- `python -m gridagent_data.cli bundle --atlas-public ../atlas/public`
  emits a `synthetic_ei.pmtiles` archive with a matching `license.json`.
- The QA gate runs AC-OPF on the synthetic case and writes a
  `feasibility.json` artefact alongside the bundle.
- `platform/atlas/` renders both observed and synthetic transmission with
  the toggle working.
- `to_sienna.py` exports the synthetic case in a shape `platform/julia/`
  can run N-1 screening on, end-to-end.
