# Beneficiary-Load Screening — Production Handoff

**From:** Wayne prototype (`codex/set-influence-beneficiary-load-spec`)
**To:** production app implementers
**Date:** 2026-08-06 · **revised 2026-08-07** after a semantics review with the
project owner (see §1a — it supersedes anything that contradicts it)
**Companion spec:** [`wayne-set-influence-beneficiary-load-spec.md`](wayne-set-influence-beneficiary-load-spec.md) — same branch, originally PR [#20](https://github.com/Tom-Nudell/wayne/pull/20). All section references below (§4, §7, §8, §9, §20) point into that document.

Wayne is a prototype test bed. It uses pandapower to produce its own PTDF/LODF
tables. You will produce OTDF / DFAX / LODF tables with commercial software
instead. **Everything downstream of those tables is identical**, and that
downstream part is what this handoff delivers.

---

## 1. What the algorithm answers

> Which candidate **load POIs** are worth an expensive full-AC study, because a
> dispatch of the distributed **ADER fleet** could plausibly unlock meaningful
> incremental deliverability there?

The screen produces, per POI: **headroom** (additional MW before any constraint
binds, ≥ 0), **next capacity** (headroom if the first binding constraint were
resolved), and a **certified potential bound** (an upper bound on what any valid
ADER dispatch could unlock). The study set `S ⊂ L` — the POIs that go on the
map and forward to AC study — is selected on the potential bound, because an
optimistic bound guarantees no DC false negatives.

Both transfers share one balancing-area (BA) reference vector `alpha`:

- ADER injection is balanced by BA backdown; ADER withdrawal by BA generation;
- incremental POI load is *independently* supplied by BA generation.

The ADER set never "supplies" the beneficiary load. The relationship is
constraint-mediated. Spec §2 and §16.3 make this a contract-test requirement,
and it matters commercially — do not let it drift in the production UI.

---

## 1a. Settled semantics (2026-08-07 review) — read this first

These decisions came out of a review with the project owner and are labeled per
spec §20's convention. They supersede the fixed-dispatch framing used elsewhere
in early drafts.

1. **Constraint set** *(correctness)*: `k = (m, c)` over monitored facilities
   `m ∈ M` and contingencies `c ∈ C`, where **C includes the intact network**
   (no contingency) as an ordinary screening state.
2. **Recourse dispatch** *(operational feasibility — restructures the
   optimization)*: the ADER fleet is dispatched **once per contingency**. One
   vector `x_c` within bus bounds serves every monitored facility under `c`;
   under a different contingency a different `x_c'` may be used. What this rules
   out: a different response per constraint under the same event, and
   re-dispatch as the load level grows.
3. **Validity** *(operational feasibility)*: a dispatch that worsens the managed
   flow or creates any **new** binding constraint is invalid; the fallback is
   always do-nothing (`x = 0`). Pre-existing violations (present at `x = 0`) are
   held to *no worse than base* — a dispatch is never required to cure a
   violation the load does not create. Consequence: **unlocked capacity is ≥ 0
   by construction.** A negative unlock anywhere in a result is a bug or a
   semantics drift, full stop.
4. **Per-POI outputs** *(product)*: headroom (≥ 0; 0 means a pre-existing
   binder), next capacity, potential bound, and the binding/co-binding
   constraints. **The map metric is the Tier-1 certified bound** (below).
5. **Ultimate goal** *(product)*: for each POI in `S`, find the *minimum set* of
   ADER nodes that maximally increases withdrawal capacity — final validation in
   **full AC with all constraints**, which is the expensive computation this
   screen exists to gate. The min-cardinality selection is a MILP and is
   deferred; the per-contingency LP's dispatch supports are the screening proxy.
6. **Fixed-dispatch evaluation is a sub-tool, not the screen** *(product /
   trust)*: evaluating one shared dispatch at every POI (the original
   `screen_beneficiary_loads`, spec §13 `evaluate_dispatch_action`) can
   legitimately report a *negative* effect at some POI — a fixed dispatch
   redistributes flow. That is precisely why it is not the POI score.

### The funnel

Each tier is **optimistic relative to the tier below**, so no DC false negatives
flow downward; the expensive tiers do the pruning.

| Tier | What | Cost | Function |
|---|---|---|---|
| 0 | Headroom `T⁰`, binder `k*`, co-binders, next capacity | streaming factor math | `screen_poi_potential` (fields) |
| 1 | **Certified potential bound** — each constraint independently gets its best-case in-box dispatch: `T_bound(k) = t0(k) + relief_max(k)/|g_k|`, `T_pot = min_k T_bound(k)` | streaming factor math | `screen_poi_potential` — **the map metric** |
| 2 | Exact-in-DC recourse value: per contingency `c`, one LP `max T` s.t. all valid `m` under `c` within (no-worsening) limits, `x_c` in box; `T_l = min_c T_c_max` | tiny LPs, mostly skipped | `poi_recourse_capacity` |
| 3 | Full AC / SCOPF with all constraints, min-ADER-set selection | expensive | production, outside Wayne |

The Tier-2 skip rule makes the LP tier nearly free: `T_c0 ≤ T_c_max ≤
T_c_bound`, where `T_c0` is the no-dispatch limit under `c` (already computed in
Tier 0). Processing contingencies in ascending `T_c0`, once the next `T_c0 ≥`
the running min of solved `T_c_max`, nothing that remains can bind — stop. On
RTS this solves 1–2 LPs out of 121 states per POI.

Sandwich invariant, enforced in code and tests: `headroom ≤ recourse ≤
potential bound`, and `potential ≥ headroom` pairwise because relief ≥ 0.

---

## 2. Status: what is verified vs. design-only

Read this table before planning any work. The spec is broader than the code.

| Piece | Status |
|---|---|
| Tier-0/1 screen: headroom, next capacity, certified potential bound (§1a) | **Implemented and verified.** `screen_poi_potential`, intact state included, NaN-rejecting |
| Tier-2 recourse LP with skip rule and no-worsening validity | **Implemented and tested** at prototype scale (`poi_recourse_capacity`, scipy) |
| Fixed-dispatch evaluation (sub-tool; not the POI score — §1a.6) | **Implemented and verified.** `screen_beneficiary_loads`, reproduces the committed RTS-GMLC fixture exactly |
| BA-referencing + invariance to the PTDF slack choice | **Implemented, property-tested** |
| Rank-one N-1 contingency update (`H_m + LODF·H_c`) | **Implemented and verified** at RTS scale |
| Cube-free factorization for production scale (§6 below) | **Verified numerically** (2.2e-16), *not yet implemented* in Wayne |
| Min-cardinality ADER-set selection (MILP; §1a.5) | Design only — LP dispatch supports are the proxy |
| Sensitivity envelope under bus bounds (spec §5.2) | **Implemented** as the Tier-1 relief envelope |
| Certified sparse constraint frontier (spec §8) | Design only |
| N-k Woodbury update (spec §4) | Design only |
| Numerical reliability contract / connectivity checks (spec §9) | Design only — see gap 3 in §8 |
| Cache invalidation contract (spec §10) | Design only |
| Deliverability vs network-capability split (spec §6.1) | Design only — Wayne reports network limits only |
| Production-scale performance gate (spec §15) | **Blocked** — never run; no production model in Wayne |

The RTS-GMLC case (73 buses, 120 branches) established correctness. It is **not**
evidence of screening efficiency at your scale. Spec §15 is explicit about this.

---

## 3. The seam: where your commercial tables plug in

The algorithm is now a solver-agnostic module with no solver imports:

**[`platform/tools/src/gridagent_tools/beneficiary_screen.py`](platform/tools/src/gridagent_tools/beneficiary_screen.py)** — numpy + stdlib only.

Three entry points, and you will likely use only the last two:

```python
otdf_from_ptdf_lodf(ptdf, lodf)   # skip this if your tool exports OTDF directly
ba_referenced_factors(otdf, alpha)
screen_beneficiary_loads(referenced_factors, base_contingency_flow, limit_mw, valid,
                         action_bus_columns=..., action_mw=...,
                         poi_bus_columns=..., constraints_per_poi=4)
```

Wayne's pandapower path lives entirely in
[`platform/tools/eval/beneficiary_load_demo.py`](platform/tools/eval/beneficiary_load_demo.py) — snapshot loading, DC power
flow, `makePTDF`/`makeLODF`, ratings, geometry, JSON. **That file is the part you
replace.** Nothing in it is load-bearing for the algorithm.

### ⚠ The one integration trap: "DFAX" is ambiguous

This is the highest-risk item in the whole handoff.

`ba_referenced_factors` expects **unreferenced** post-contingency sensitivities
`a[q,b]` — factors against whatever arbitrary slack your tool used. It then
applies your BA reference itself.

In commercial usage "DFAX" frequently means factors that **already embed a
source/sink transfer definition**. If you feed such a table into
`ba_referenced_factors`, you double-reference it and every number is silently
wrong — no exception, no NaN, just a plausible incorrect ranking.

Decide which you have before writing any code:

- **Raw PTDF / OTDF against an arbitrary single slack** → pass to
  `ba_referenced_factors(otdf, alpha)`. Correct path.
- **Already referenced to your intended BA participation** → these *are* `d[q,b]`.
  **Skip `ba_referenced_factors` entirely** and pass them straight to
  `screen_beneficiary_loads`.
- **Referenced to some *other* source/sink** (a specific unit, a hub, a different
  footprint) → unusable as-is. Recover the raw factors or re-export.

A cheap, decisive test: for a raw table, `ba_referenced_factors` output must be
**invariant** when you shift every factor row by a per-row constant across the
bus axis (that is exactly what changing the slack bus does). Wayne asserts this
in `test_ba_reference_invariant_to_ptdf_slack_choice`. Run the equivalent check
against your own export before trusting it.

---

## 4. Input contract

Shapes, for `M` monitored elements, `C` contingencies, `B` buses:

| Input | Shape | Notes |
|---|---|---|
| `ptdf` | `(M, B)` | One consistent branch orientation. Rows must also cover the contingency elements when used with `otdf_from_ptdf_lodf` |
| `lodf` | `(M, C)` | Monitored `m` under outage of `c`. Non-finite entries are zeroed *for arithmetic only* — exclude them via `valid` |
| `otdf` | `(M, C, B)` | Post-contingency factors, if exported directly. See the DFAX warning above |
| `alpha` | `(B,)` | BA participation, **must sum to 1.0**. Frozen and serialized per study |
| `base_contingency_flow` | `(M, C)` | Post-contingency flow *before* the ADER action: `f_m + LODF·f_c` |
| `limit_mw` | `(M, 1)` or `(M, C)` | Directional rating. Broadcast to `(M, C)` |
| `valid` | `(M, C)` bool | `False` for self-outage, islanding, and anything your reliability screen rejects |
| `action_bus_columns` / `action_mw` | `(P,)` | ADER bus columns and signed MW. `+` = inject at node, BA backs down |
| `poi_bus_columns` | `(L,)` | Candidate load POI bus columns |

Conventions you must confirm against your tool's export — each of these fails
**silently**:

1. **Branch orientation.** PTDF, LODF, base flows, and limits must share one
   from→to sign convention. A flipped subset produces wrong-signed headroom.
2. **LODF diagonal.** Self-outage must be excluded via `valid`, not left as a
   value.
3. **Units.** The DC model is MW. Wayne uses `rating_a_mva × 1.25` as a stand-in
   emergency limit. Real MVA ratings need an explicit MW conversion policy.
4. **Rating selection.** Which rating applies to which contingency and duration
   (normal / emergency / short-term) is spec §20 Q3 and is *unresolved*. Wayne's
   1.25 multiplier is a demo placeholder, not a recommendation.
5. **Bus indexing.** `action_bus_columns` and `poi_bus_columns` index the *bus
   axis of your factor tables*, not your internal bus numbers. Get this mapping
   from one place.

---

## 5. The algorithm, in five steps

For monitored/contingency pair `q = (m, c)`, bus `b`:

**1. Post-contingency sensitivity** (rank-one, exact under lossless DC):

```
a[q,b] = H[m,b] + LODF[m,c] · H[c,b]
f0[q]  = f[m]   + LODF[m,c] · f[c]
```

**2. BA-reference the factors** — this is what puts the ADER action and the load
transfer in one electrical coordinate system:

```
d[q,b] = a[q,b] − Σ_b′ a[q,b′]·alpha[b′]
```

`+1` MW injection at `b` (BA backs down) moves `q` by `+d[q,b]`.
`+1` MW load at `b` (BA supplies) moves `q` by `−d[q,b]`.

**3. Apply the signed ADER action** `x`:

```
Δf[q] = Σ_i d[q, ader_i] · x_i        f1[q] = f0[q] + Δf[q]
```

**4. Per-POI transfer limit.** Load factor `g[q] = −d[q, ℓ]`; for each state
`k ∈ {base, managed}`:

```
T[q]  =  (limit − fk[q]) / g[q]      if g[q] >  1e-9
         (fk[q] + limit) / (−g[q])   if g[q] < −1e-9
         +∞                          otherwise
T_ℓ   =  max(0, min over all valid q of T[q])
```

**5. Score and rank:** `unlocked_ℓ = T_ℓ(managed) − T_ℓ(base)`, descending.
Report the binding constraint in each state — they are frequently different, and
that difference is the interesting engineering output.

---

## 6. Scale: do not build the cube

Wayne materializes the full `(M, C, B)` factor cube. At RTS that is 8.4 MB. At
your scale it is not viable, and spec §3.2/§7 forbid it:

| Case | `(M, C, B)` | Cube, float64 |
|---|---|---|
| RTS-GMLC (Wayne) | 120 × 120 × 73 | 8.4 MB |
| Production (spec §1) | 10,000 × 100,000 × 1,000 | **8.0 TB** |

A single `(M, C)` slice at production scale is already 8 GB, so even one POI's
load-factor matrix will not fit in memory. Tiling is mandatory.

### The identity that makes it cheap

**BA-referencing commutes with the rank-one contingency update.** Reference the
*base* PTDF once, and the contingency update is unchanged:

```
d_base[:, b] = H[:, b] − (H · alpha)            # one column per bus of interest

d[m,c,b] = d_base[m,b] + LODF[m,c] · d_base[c,b]
```

Verified against the full-cube computation on the real RTS case:
**max absolute error 2.2e-16** (`allclose` at 1e-9), for both the full cube and
the per-POI slice a tiled loop would build.

So you never store the cube. You store BA-referenced **base columns** only —
`(M+C) × (P + L)` for your ADER nodes and candidate POIs, ≈ **0.9 GB** at
production scale — plus LODF, and you synthesize each `(M, C)` tile on the fly:

```
load_factor_tile[m,c] = −( d_base[m,ℓ] + LODF[m,c] · d_base[c,ℓ] )
ader_tile[m,c]        =    z[m]        + LODF[m,c] · z[c]     where z = d_base[:, ader] @ x
```

Both reductions the algorithm needs — `min` over pairs, and top-k per POI — are
streaming. Tile over contingency blocks, reduce, discard, advance. This is spec
§7's `O(P(M+C) + MC)` shape, and it is the single most important structural
decision in your implementation.

**Not implemented in Wayne.** The identity is verified; the tiled screen is
yours to build. Spec §8 defines the certified-frontier retention rules that keep
pruning free of false negatives — implement those, not an ad-hoc top-k, if the
output is going to be called authoritative.

---

## 7. Reading the demo result — and its important caveat

Committed fixture: [`web/src/lib/study/beneficiary-load-demo.json`](web/src/lib/study/beneficiary-load-demo.json).
RTS-GMLC, 6 ADER nodes (per-node bounds ±60 MW), 6 candidate POIs, intact
network included in the tier screen.

Tier screen (the map numbers), per POI — headroom is 251.5 MW for all six, and
`next capacity = headroom` for all six because the binder co-binds with its
mirror pair (resolving one constraint alone buys nothing):

| Rank | POI | Headroom MW | Potential MW (Tier-1 bound) | Potential unlock MW |
|---|---|---|---|---|
| 1 | 313 Cecil | 251.5 | 611.5 | 360.0 |
| 2 | 319 Clay | 251.5 | 611.5 | 360.0 |
| 3 | 315 Chase | 251.5 | 611.4 | 359.9 |
| 4 | 314 Chain | 251.5 | 595.6 | 344.1 |
| 5 | 310 Caruso | 251.5 | 544.6 | 293.1 |
| 6 | 303 Caesar | 251.5 | 325.1 | 73.6 |

Contrast with the fixed-dispatch sub-tool (net +165 MW action), which produced
a four-way tie at exactly 165.0 unlocked — the Tier-1 screen breaks that tie
because each POI's *second* constraint (the one that binds after the shared
interface is relieved) differs, and the bound sees it. Diagnosis of the
remaining structure:

- The Tier-0 binding pair for all six POIs is **A34 monitored / A30 out** — an
  inter-area tie at 607.5 MW against a 625 MW emergency limit (97.2% loaded in
  base), co-binding with its mirror **A30 | A34**.
- On that pair, all six ADER nodes *and* all six POIs have the **identical**
  BA-referenced factor `d = +0.06966`. They sit behind the same wide-area
  interface relative to a system-wide BA reference. That is why the top of the
  table still shows a two-way tie (313/319) and why headroom alone ranks nothing.
- The unlock ceiling at the shared binder is the full box: `6 × 60 × 0.06966 /
  0.06966 = 360 MW` — a pure 1:1 MW swap, visible as the plateau at the top of
  the table. POIs fall away from the plateau exactly when a **local** constraint
  (C-network branches) starts binding below it.

The generalizable lessons for production: **when a wide-area interface binds,
every candidate behind it is electrically identical at Tier 0**, and the ranking
power comes from the *next* constraints down — which is what the Tier-1 bound
measures. A top group pinned at the full-box ceiling (here 360 MW) means those
POIs are indistinguishable until the monitored set includes more local
constraints. `next capacity == headroom` is the co-binding tell that resolving a
single facility cannot help.

---

## 8. Known gaps to close in production

Found while extracting and verifying. None are fixed in Wayne.

1. **No connectivity check.** Wayne infers islanding purely from non-finite
   LODF (`~isfinite(lodf).all(axis=0)`, 2 outages excluded at RTS). Spec §9 is
   explicit that this is wrong: a *near*-islanding contingency yields a large but
   **finite** LODF, passes the finiteness filter, and can inflate factors and
   transfer limits by orders of magnitude with no flag. Implement spec §9's
   graph-connectivity check plus `rcond` gating and the `NEAR_ISLANDING` /
   `NUMERICALLY_UNSTABLE` statuses. **This is the most likely source of
   spectacular wrong answers on a real model.**
2. **`nanmin` hides NaN — fixed in the tier path only.** The legacy
   fixed-dispatch path (`screen_beneficiary_loads`) still uses
   `max(0.0, nanmin(...))`, which silently drops NaN entries. The tier
   functions (`screen_poi_potential`, `poi_recourse_capacity`) instead
   validate inputs and raise `ValueError` on any NaN. Port the tier
   behavior; do not port the legacy behavior.
3. **Unguarded `alpha` normalization.** The demo does `alpha /= alpha.sum()`
   with no zero-guard, and the core does not validate that `alpha` sums to 1.
   Validate at the boundary: a malformed `alpha` propagates as plausible numbers.
4. **Rounding-order sensitivity in ties.** Wayne's original script sorted POIs on
   the *rounded* (3 dp) unlocked MW with `bus_id` as tie-break; the extracted core
   sorts on the raw value. Identical on this fixture (parity verified), but they
   diverge if two POIs differ by <0.0005 MW. Pick a deliberate tie-break policy —
   given §7, near-ties will be common.
   *(Two gaps closed by the 2026-08-07 tier rework, in the tier path only: the
   intact network is now screenable via `append_intact_contingency`, and
   pre-existing violations no longer poison the recourse LP — already-violated
   rows are held to no-worse-than-base per §1a.3.)*
5. **No deliverability split.** Wayne reports network limits only. Spec §6.1
   requires `network_load_limit_mw`, BA supply capability, and POI acceptance to
   be separate fields, with `deliverable_load_mw: null` and status
   `CAPABILITY_INCOMPLETE` when inputs are missing. Missing capability must never
   be read as infinite. This is a customer-trust requirement, not a nicety.
6. **No coverage status.** Every network-limit result needs
   `CERTIFIED` / `CANDIDATE_ONLY` / `INCOMPLETE` (spec §8). Only `CERTIFIED`
   supports an authoritative limit.

---

## 9. Questions that block implementation

From spec §20, narrowed to the ones that change the screening code. The spec
records the full list of twelve.

1. **Ratings** (§20 Q3) — which rating for which contingency and duration?
   Wayne's `rating_a × 1.25` is a placeholder. This scales every output.
   The recourse structure (§1a.2) adds a timing sub-question: dispatching
   *after* the contingency is only valid if the ADER response fits inside the
   post-contingency rating window (emergency/short-term duration vs. dispatch
   latency).
2. **Contingency semantics** (§20 Q4) — are your ~100k records unique outage
   sets, operating cases, or remedial-action variants? Determines whether spec
   §8.2's factor/operating-state hash split collapses the work by orders of
   magnitude.
3. **BA footprint and policy** (§13) — ERCOT-wide, or an explicit PJM/MISO
   sub-footprint? Which resolver (`pro_rata_pmax`, `pro_rata_headroom`,
   `governor_participation`)? `alpha` must be frozen and serialized per study.
4. **Monitored-set scope** — see §7. Grid-wide-only monitoring produces
   degenerate ties. What local-constraint coverage will you include?
5. **Ranking objective** (§20 Q8) — *partially resolved 2026-08-07*: the screen
   ranks by the Tier-1 potential bound in raw MW (§1a.4). Still open: whether
   commercial weighting (contingency probability, severity, duration, value)
   enters at the map layer or only at AC-study prioritization.
   Also settled: the intact network is in the constraint set, and a standing
   (intact-state) dispatch is economically distinct from a rare contingency
   response — compute it identically, report it separately.
6. **POI acceptance and ADER capability data owners** (§20 Q6, Q7) — needed
   before any output can be called *deliverable* rather than network-limited.

Spec §20 asks that reviewers **add constraints rather than silently revise
settled semantics**, and label each addition as a correctness, data/provenance,
operational-feasibility, performance, or product-language constraint. Please
follow that when you feed findings back.

---

## 10. Files and how to run it

| Path | Role |
|---|---|
| [`platform/tools/src/gridagent_tools/beneficiary_screen.py`](platform/tools/src/gridagent_tools/beneficiary_screen.py) | **The deliverable.** Engine-neutral core, numpy only (scipy lazily, for the Tier-2 LP alone). Tier screen: `screen_poi_potential`, `poi_recourse_capacity`, `append_intact_contingency`. Sub-tool: `screen_beneficiary_loads` |
| [`platform/tools/tests/test_beneficiary_screen.py`](platform/tools/tests/test_beneficiary_screen.py) | 9 tests: sign convention, slack invariance, directionality, ranking |
| [`platform/tools/tests/test_beneficiary_screen_tiers.py`](platform/tools/tests/test_beneficiary_screen_tiers.py) | Tier tests: do-nothing floor, envelope arithmetic, co-binding, intact binder, recourse-beats-fixed, no-worsening validity, skip-rule exactness, sandwich |
| [`platform/tools/eval/beneficiary_load_demo.py`](platform/tools/eval/beneficiary_load_demo.py) | pandapower harness — **the part you replace** |
| [`web/src/lib/study/beneficiary-load-demo.json`](web/src/lib/study/beneficiary-load-demo.json) | Committed RTS fixture (reference numbers) |
| [`web/src/lib/study/beneficiary-load.ts`](web/src/lib/study/beneficiary-load.ts) | Presentation only — map overlay + slider projection. No algorithm |
| [`wayne-set-influence-beneficiary-load-spec.md`](wayne-set-influence-beneficiary-load-spec.md) | Full spec: envelopes, frontier, N-k, caches, numerics, result schema |

Setup and verification (Python 3.11):

```bash
cd platform/tools && uv venv --python 3.11 && uv pip install --python .venv/bin/python -e ".[dev,pandapower]"
```

```bash
platform/tools/.venv/bin/python -m pytest platform/tools/tests/ -q
```

Expect `21 passed, 3 skipped` (the skips are pre-existing, unrelated to this
work — a Tellegen backend that is not installed).

Regenerate the fixture and confirm the algorithm reproduces it:

```bash
GRIDAGENT_DATA_ROOT=data_root platform/tools/.venv/bin/python platform/tools/eval/beneficiary_load_demo.py
```

The committed file is prettier-formatted, so compare parsed JSON rather than
bytes — the values are identical.

---

## 11. Suggested order of work

1. **Resolve the DFAX question in §3** before writing code. Run the slack-shift
   invariance check against a real export. Everything else is wasted if the
   factor convention is wrong.
2. Port `beneficiary_screen.py` as-is and reproduce Wayne's RTS fixture through
   your own factor pipeline. That is your parity oracle. Port the **tier
   functions** as the product surface (§1a); the fixed-dispatch path is a
   sub-tool.
3. Replace the cube with the tiled `d_base` + LODF formulation from §6. The
   Tier-0/1 math is already streaming-shaped; the Tier-2 skip rule keeps the LP
   count near-constant per POI.
4. Add spec §9 connectivity and conditioning gates (gap 1) — before running any
   real model, not after.
5. Add coverage status and the deliverability split (gaps 5, 6).
6. Run spec §15's production-scale gate and publish the survivor rates. Spec §8.1
   makes the probabilistic-sketch decision contingent on that data; deterministic
   bounds plus exact tiled fallback are the authoritative path until then.
7. When `S` is stable, the min-cardinality ADER-set MILP (§1a.5) and full AC
   validation are the endgame — the screen's job is only to make that list
   short.
