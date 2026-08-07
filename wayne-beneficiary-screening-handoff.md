# Beneficiary-Load Screening — Production Handoff

**From:** Wayne prototype (`codex/set-influence-beneficiary-load-spec`)
**To:** production app implementers
**Date:** 2026-08-06
**Companion spec:** [`wayne-set-influence-beneficiary-load-spec.md`](wayne-set-influence-beneficiary-load-spec.md) — same branch, originally PR [#20](https://github.com/Tom-Nudell/wayne/pull/20). All section references below (§4, §7, §8, §9, §20) point into that document.

Wayne is a prototype test bed. It uses pandapower to produce its own PTDF/LODF
tables. You will produce OTDF / DFAX / LODF tables with commercial software
instead. **Everything downstream of those tables is identical**, and that
downstream part is what this handoff delivers.

---

## 1. What the algorithm answers

> Given a signed dispatch across a set of distributed nodes (the **ADER set**),
> which candidate **load POIs** gain the most incremental deliverability because
> that dispatch created post-contingency transmission headroom?

Output: candidate load POIs ranked by **unlocked MW** — the increase in
contingency-limited BA-to-load transfer capability — each with the constraints
that bind before and after the dispatch.

The two transfers are kept deliberately separate and share one balancing-area
(BA) reference vector `alpha`:

- ADER injection is balanced by BA backdown; ADER withdrawal by BA generation;
- incremental POI load is *independently* supplied by BA generation.

The ADER set never "supplies" the beneficiary load. The relationship is
constraint-mediated. Spec §2 and §16.3 make this a contract-test requirement,
and it matters commercially — do not let it drift in the production UI.

---

## 2. Status: what is verified vs. design-only

Read this table before planning any work. The spec is broader than the code.

| Piece | Status |
|---|---|
| DC screening algorithm (rank, before/after limits, binding constraints) | **Implemented and verified.** `beneficiary_screen.py`, 9 unit tests, reproduces the committed RTS-GMLC fixture exactly |
| BA-referencing + invariance to the PTDF slack choice | **Implemented, property-tested** |
| Rank-one N-1 contingency update (`H_m + LODF·H_c`) | **Implemented and verified** at RTS scale |
| Cube-free factorization for production scale (§6 below) | **Verified numerically** (2.2e-16), *not yet implemented* in Wayne |
| Sensitivity envelope under bus bounds (spec §5.2) | Design only |
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
RTS-GMLC, 6 ADER nodes (net **+165 MW**), 6 candidate POIs, 14,042 screened pairs.

| Rank | POI | Base MW | Managed MW | Unlocked MW |
|---|---|---|---|---|
| 1 | 310 Caruso | 251.5 | 416.5 | 165.0 |
| 2 | 313 Cecil | 251.5 | 416.5 | 165.0 |
| 3 | 314 Chain | 251.5 | 416.5 | 165.0 |
| 4 | 319 Clay | 251.5 | 416.5 | 165.0 |
| 5 | 315 Chase | 251.5 | 362.6 | 111.2 |
| 6 | 303 Caesar | 251.5 | 299.5 | 48.0 |

**Do not read this as a validation of ranking power.** Every POI has the same
base capacity, and the top four tie exactly at the net ADER dispatch. Diagnosed:

- The binding pair for all six POIs is **A34 monitored / A30 out** — an inter-area
  tie at 607.5 MW against a 625 MW emergency limit (97.2% loaded in base).
- On that pair, all six ADER nodes *and* all six POIs have the **identical**
  BA-referenced factor `d = +0.06966`. They sit behind the same wide-area
  interface relative to a system-wide BA reference.
- So the unlock is a pure 1:1 MW swap: `11.49 MW / 0.06966 = 165.0 MW`, exactly
  the net dispatch. The screen cannot distinguish those four POIs *because they
  are not electrically distinct with respect to the constraint that binds.*

Ranks 5 and 6 differentiate only because a **local** constraint (C6) binds first.

The generalizable lesson for production: **when a wide-area interface binds,
every candidate behind it is electrically identical and the screen has no
discriminating power.** Your monitored set must include local constraints, or
you will produce confidently-ranked ties. Treat a run whose top group ties at
the net dispatch as a signal that the monitored set is too coarse, not as a
result.

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
2. **`nanmin` hides NaN.** `_capacity` uses `max(0.0, nanmin(...))`, which
   silently drops NaN entries. A degenerate `0/0` that slips past the `1e-9`
   epsilon yields a *too-generous* capacity rather than an error. Fail loudly.
3. **Unguarded `alpha` normalization.** The demo does `alpha /= alpha.sum()`
   with no zero-guard, and the core does not validate that `alpha` sums to 1.
   Validate at the boundary: a malformed `alpha` propagates as plausible numbers.
4. **Rounding-order sensitivity in ties.** Wayne's original script sorted POIs on
   the *rounded* (3 dp) unlocked MW with `bus_id` as tie-break; the extracted core
   sorts on the raw value. Identical on this fixture (parity verified), but they
   diverge if two POIs differ by <0.0005 MW. Pick a deliberate tie-break policy —
   given §7, near-ties will be common.
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
2. **Contingency semantics** (§20 Q4) — are your ~100k records unique outage
   sets, operating cases, or remedial-action variants? Determines whether spec
   §8.2's factor/operating-state hash split collapses the work by orders of
   magnitude.
3. **BA footprint and policy** (§13) — ERCOT-wide, or an explicit PJM/MISO
   sub-footprint? Which resolver (`pro_rata_pmax`, `pro_rata_headroom`,
   `governor_participation`)? `alpha` must be frozen and serialized per study.
4. **Monitored-set scope** — see §7. Grid-wide-only monitoring produces
   degenerate ties. What local-constraint coverage will you include?
5. **Ranking objective** (§20 Q8) — MW gain only, or weighted by contingency
   probability, severity, duration, or commercial value? The current score is
   raw MW.
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
| [`platform/tools/src/gridagent_tools/beneficiary_screen.py`](platform/tools/src/gridagent_tools/beneficiary_screen.py) | **The deliverable.** Engine-neutral core, numpy only |
| [`platform/tools/tests/test_beneficiary_screen.py`](platform/tools/tests/test_beneficiary_screen.py) | 9 tests: sign convention, slack invariance, directionality, ranking |
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
   your own factor pipeline. That is your parity oracle.
3. Replace the cube with the tiled `d_base` + LODF formulation from §6.
4. Add spec §9 connectivity and conditioning gates (gap 1) — before running any
   real model, not after.
5. Add coverage status and the deliverability split (gaps 5, 6).
6. Run spec §15's production-scale gate and publish the survivor rates. Spec §8.1
   makes the probabilistic-sketch decision contingent on that data; deterministic
   bounds plus exact tiled fallback are the authoritative path until then.
