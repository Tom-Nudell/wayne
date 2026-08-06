# Wayne BA-Referenced Set Influence and Beneficiary-Load Specification

**Status:** draft for constraint review, 2026-08-06  
**Audience:** Wayne study-engine, data, orchestration, and product reviewers  
**Scope:** DC sensitivity screening and beneficiary-load discovery  
**Implementation status:** design only; production-scale benchmark required before approval

---

## 1. Executive summary

Wayne needs to answer two related but distinct questions:

1. How can a signed dispatch across a set of distributed nodes influence
   monitored transmission constraints under contingencies?
2. Which load POIs gain the most incremental deliverability because that
   dispatch created transmission headroom?

The distributed-node set is called the **ADER set** in this document. ADER
describes the candidate nodes; it does not imply that those nodes sell or
deliver energy to a beneficiary load. Both studies instead use the same
balancing-area (BA) reference participation vector:

- an ADER injection is balanced by BA backdown;
- an ADER withdrawal is supplied by BA generation;
- an incremental target load is separately supplied by BA generation.

The common BA reference puts the ADER action and the load transfer in one
electrical coordinate system. It makes statements such as "the load adds X MW
to constraint q while the ADER dispatch removes Y MW" mathematically valid.

The architecture must not materialize a candidate-bus by monitored-facility by
contingency cube. At representative scale,

\[
P=1{,}000,\quad M=10{,}000,\quad C=100{,}000,
\]

the cube contains \(10^{12}\) values, or 4 TB in float32. Wayne instead stores
base factor slices and contingency updates, evaluates them lazily, and reduces
results into a certified sparse constraint frontier.

The authoritative beneficiary metric is the increase in BA-to-load
contingency-limited transfer capability:

\[
\operatorname{Benefit}_\ell=T_\ell^{\text{managed}}-T_\ell^{\text{base}}.
\]

---

## 2. Terminology and sign convention

| Term | Meaning |
|---|---|
| ADER set | A configured set of distribution-connected candidate nodes. It is bus-class-agnostic inside the engine. |
| BA reference | A frozen participation vector \(\alpha\) over BA transmission buses, with \(\mathbf 1^\top\alpha=1\). |
| Dispatch action | Signed injection or withdrawal \(x\) at ADER nodes, with the opposite net movement assigned to the BA reference. |
| Target load POI | A candidate load bus whose incremental BA-supplied deliverability is evaluated. |
| Constraint | A monitored facility \(m\), directional limit, and contingency \(c\), denoted \(q=(m,c)\). |
| Headroom | Directional distance between the post-contingency flow and the relevant facility limit. |
| Constraint frontier | The certified retained set of constraint-contingency pairs capable of binding a query. |

Bus injections use the standard sign convention:

- positive: injection into the transmission network;
- negative: withdrawal from the transmission network.

The engine must never describe the ADER dispatch as supplying the target load.
The relationship is constraint-mediated, not a bilateral energy transaction.

---

## 3. Goals and non-goals

### 3.1 V1 goals

1. Establish one frozen, serialized BA reference vector for every study.
2. Compute contingency-adjusted, BA-referenced bus sensitivities without a
   \(P\times M\times C\) cube.
3. Evaluate a supplied signed ADER dispatch action.
4. Compute per-constraint ADER set sensitivity envelopes under bus bounds,
   clearly labeled as bounds rather than operating dispatches.
5. Construct a deterministic, certified sparse constraint frontier.
6. Rank target load POIs by the increase in contingency-limited BA-to-load
   transfer capability after the ADER action.
7. Name the primary binding element and any co-binding elements.
8. Persist sufficient provenance to reproduce every result.

### 3.2 Explicit non-goals for this pass

- Claiming that a sensitivity-envelope witness is an operationally feasible
  dispatch.
- Allowing the dispatch composition to re-optimize as individual resources
  saturate.
- Unit commitment, ramping, reserves, reactive power, voltage, or AC
  feasibility.
- A combined transmission-and-distribution network model.
- Probabilistic screening as an authoritative completeness mechanism.
- Reconciling legacy implicit-slack injection-study results with the new
  BA-referenced result family.

---

## 4. DC factor kernel

Let \(H\) be the base PTDF matrix, with branch rows and bus-injection columns
under one consistent branch orientation. Let \(L_{m,c}\) be the LODF of
monitored branch \(m\) for outage \(c\).

For a single-branch outage, the post-contingency bus sensitivity is

\[
a_{q,b}=H_{m,b}+L_{m,c}H_{c,b},\qquad q=(m,c).
\]

In block form,

\[
H^{(c)}_{M,P}=H_{M,P}+L_{M,c}H_{c,P}.
\]

This is an exact rank-one update under the lossless DC model. The corresponding
post-contingency base flow is

\[
f_q^0=f_m+L_{m,c}f_c.
\]

For a multi-element outage set \(K\), the update generalizes to

\[
H^{(K)}_{M,P}
=H_{M,P}+\Phi_{M,K}(I-\Phi_{K,K})^{-1}H_{K,P},
\]

provided the post-contingency system remains connected and the small update
system is numerically reliable.

### 4.1 BA-referenced bus factor

For frozen BA reference participation \(\alpha\), define

\[
\boxed{d_{q,b}=a_{q,b}-a_q^\top\alpha.}
\]

Then:

- \(+1\) MW injection at bus \(b\), balanced by BA backdown, changes flow on
  \(q\) by \(+d_{q,b}\);
- \(+1\) MW load at bus \(b\), supplied by BA generation, changes flow on
  \(q\) by \(-d_{q,b}\).

All ADER nodes and target load POIs must use the same \(\alpha\) within a study.

---

## 5. ADER dispatch action

Let \(E_D\) map the configured ADER nodes into transmission buses. Let
\(x\in\mathbb R^P\) contain signed ADER changes in MW. The balanced network
injection is

\[
p_D=E_Dx-\alpha\mathbf 1^\top x.
\]

The flow change on contingency constraint \(q\) is

\[
\boxed{\Delta f_q^D=d_{q,D}^\top x.}
\]

The managed post-contingency flow is

\[
f_q^1=f_q^0+\Delta f_q^D.
\]

The API must preserve the signed action. It must not split injections and
withdrawals into incompatible reference conventions.

### 5.1 Dispatch capability inputs

Each ADER node may provide:

```yaml
node_id: ADER_104
transmission_bus_id: BUS_905
withdrawal_available_mw: 12.0
injection_available_mw: 24.0
interface_import_limit_mw: 15.0
interface_export_limit_mw: 20.0
capability_snapshot_id: ader-cap-2026-08-06T18:00Z
provenance: distribution_capacity_snapshot
```

The effective bounds are

\[
-w_i\le x_i\le u_i,
\]

after applying any distribution-interface limits.

The net BA response is \(-\mathbf 1^\top x\). If \(\mathbf 1^\top x>0\), BA
generation backs down; if it is negative, BA generation ramps up. If the BA
participation is intended to represent a feasible response rather than only a
sensitivity reference, its upward and downward capability snapshots must also
be checked and serialized.

### 5.2 Set sensitivity envelope

For one constraint, the exact box-support bound is

\[
U_q=\max_{-w\le x\le u}d_{q,D}^\top x
=d_{q,D}^\top\mu+\lVert Wd_{q,D}\rVert_1,
\]

where

\[
\mu_i=\frac{u_i-w_i}{2},\qquad
W=\operatorname{diag}\!\left(\frac{u_i+w_i}{2}\right).
\]

The maximum movement in the opposite direction is

\[
D_q=-d_{q,D}^\top\mu+\lVert Wd_{q,D}\rVert_1.
\]

The corresponding box-extreme vector is an exact witness for this envelope,
but not a jointly feasible operating point. It must be returned as

```text
result_kind: independent_sensitivity_bound
feasibility_scope: bus_bounds_only
```

with the user-facing caveat:

> Worst-case sensitivity bound under DC assumptions. This witness is not an
> operating recommendation and has not been checked for other network limits,
> commitment, ramping, voltage, or AC feasibility.

A multi-constraint guarded LP is a future mode when Wayne is authorized to
choose the dispatch composition. A supplied dispatch action can be evaluated
against all retained constraints in v1 without that LP.

---

## 6. Target load and beneficiary metric

For \(T\) MW of incremental load at target POI \(\ell\), supplied by the BA,

\[
p_\ell^L=T(\alpha-e_\ell).
\]

Its flow sensitivity is

\[
\boxed{g_{q,\ell}=-d_{q,\ell}.}
\]

For directional facility limits \([\underline f_q,\bar f_q]\), the transfer
limit imposed by \(q\) in state \(k\in\{0,1\}\) is

\[
T_{q,\ell}^{k}=
\begin{cases}
(\bar f_q-f_q^k)/g_{q,\ell},&g_{q,\ell}>\epsilon_g,\\[4pt]
(f_q^k-\underline f_q)/(-g_{q,\ell}),&g_{q,\ell}<-\epsilon_g,\\[4pt]
+\infty,&|g_{q,\ell}|\le\epsilon_g.
\end{cases}
\]

The network-limited BA-to-load capability is

\[
T_\ell^k=\min_{q\in Q}T_{q,\ell}^k.
\]

The authoritative beneficiary score is

\[
\boxed{\operatorname{Benefit}_\ell=T_\ell^1-T_\ell^0.}
\]

This result must report the binding constraint before and after the ADER
dispatch. They may be different.

### 6.1 Deliverability versus network capability

The load result separates:

- `network_load_limit_mw`;
- BA upward supply capability;
- POI acceptance or interconnection capability;
- authoritative `deliverable_load_mw`.

If BA or POI capability is missing, Wayne may return a network limit but must
not call it deliverable MW:

```yaml
status: CAPABILITY_INCOMPLETE
network_load_limit_mw: 184.2
ba_supply_limit_mw: null
poi_acceptance_limit_mw: 220.0
deliverable_load_mw: null
```

Missing capability is never interpreted as infinite. An explicitly unbounded
assumption must be supplied and recorded as such.

---

## 7. Lazy representation and required operations

For requested candidate buses \(P\), monitored facilities \(M\), and
contingencies \(C\), the N-1 factor object stores or generates:

- \(H_{M,P}\);
- \(H_{C,P}\);
- \(L_{M,C}\);
- BA projection \(H\alpha\);
- base flows and directional limits as a separate operating-state layer.

For N-k contingencies, `C` above is replaced by the outage-element blocks
\(H_{K,P}\) and the corresponding small Woodbury update for each contingency.

For a supplied action \(x\), let \(s=\mathbf 1^\top x\) and form the
BA-referenced branch signatures

\[
z_M=H_{M,P}x-(H_M\alpha)s,
\qquad
z_C=H_{C,P}x-(H_C\alpha)s.
\]

The full N-1 contingency effect can then be reduced without the factor cube:

\[
\Delta F
=z_M\mathbf 1_C^\top
+L_{M,C}\odot\left[\mathbf 1_Mz_C^\top\right].
\]

The arithmetic cost is \(O(P(M+C)+MC)\), with \(M\times C\) processed in
bounded tiles and reduced immediately.

The factor interface should support:

```text
factor(bus, monitored, contingency)
apply_dispatch(x, monitored, contingencies)
dispatch_envelope(bounds, monitored, contingencies)
load_transfer_limit(load_bus, constraint_frontier, state)
rank_beneficiary_loads(dispatch_result, load_buses)
```

---

## 8. Constraint-frontier construction

Even after collapsing \(P\), \(M\times C=10^9\) values must not be retained.
Wayne processes contingencies in blocks and produces a sparse frontier \(Q\).

The retained union must include:

1. every existing base or managed-state violation;
2. every pair below a configured directional-headroom threshold;
3. every pair whose certified bound allows it to beat the current limiting
   transfer;
4. top headroom gains and losses globally;
5. top \(k\) pairs per monitored facility;
6. top \(k\) pairs per contingency;
7. numerical gray-zone and near-islanding cases;
8. guard constraints that could replace a relieved constraint as the new
   beneficiary-load bottleneck.

For a load transfer, suppose \(G_q\ge |g_{q,\ell}|\) is a deterministic upper
bound. Then

\[
T_{q,\ell}
\ge
\frac{\min(r_q^+,r_q^-)}{G_q}.
\]

If this lower bound exceeds the best exact transfer limit already found, the
pair cannot bind and may be discarded without a false negative.

Every network-limit result carries one of:

```text
constraint_coverage: CERTIFIED
constraint_coverage: CANDIDATE_ONLY
constraint_coverage: INCOMPLETE
```

Only `CERTIFIED` coverage supports an authoritative network transfer limit.
If a processing budget expires, Wayne returns `INCOMPLETE` with evaluated
coverage rather than silently returning an approximate complete result.

### 8.1 Screening policy for v1

V1 uses deterministic bounds and exact tiled fallback. The Cauchy sketch tier
is not part of the authoritative path. It may be reconsidered only if a
production-scale benchmark shows that deterministic survivor rates cannot meet
the performance budget. Any future probabilistic index may order candidates,
but deterministic guard sets and exact reranking remain mandatory.

### 8.2 Contingency and topology deduplication

The input may contain 100,000 contingency records without containing 100,000
unique network topologies. Wayne maintains separate factor-state and
operating-state hashes.

The factor-state hash canonicalizes:

- outaged elements;
- switching state;
- tap state;
- connected component.

The operating-state hash additionally covers modeled phase-shifter setpoints,
dispatch/injections, flows, ratings, and remedial-action state. Sensitivity
factors are computed once per unique factor state. Operating cases that share
factors reuse the factor layer and recompute the headroom layer. An
implementation may conservatively include phase-shifter setpoints in the
factor-state hash, at the cost of fewer cache hits.

---

## 9. Numerical reliability contract

Wayne must not infer islanding solely from a large LODF.

For every outage set:

1. Perform an exact graph-connectivity check after removing the contingency
   elements.
2. Estimate the reciprocal condition number of
   \(S_K=I-\Phi_{K,K}\).
3. Check the normalized residual of the Woodbury solve.

Initial calibration gates are:

| Condition | Status | Behavior |
|---|---|---|
| Post-outage graph disconnected | `ISLANDING` | Do not return a thermal DFAX result. |
| Connected and `rcond(S_K) >= 1e-8` | `OK` | Use the Woodbury result. |
| Connected and `1e-12 <= rcond(S_K) < 1e-8` | `NEAR_ISLANDING` | Directly refactor the post-contingency matrix and compare. |
| Connected and `rcond(S_K) < 1e-12` | `NUMERICALLY_UNSTABLE` | Return no authoritative factor without a successful direct solve. |

These are initial engineering thresholds, not universal physical constants.
The actual condition estimate, residual, direct-solve discrepancy, and maximum
absolute sensitivity are recorded. Large sensitivity magnitude is diagnostic
metadata, not by itself a rejection rule.

For a single outage, \(1-\phi_{c,c}\) receives the analogous condition and
direct-refactor treatment. Implementations must use float64 for factor
construction and reliability checks even if retained noncritical output is
later compressed.

---

## 10. Cache invalidation contract

Cache layers are separated so invalidation is exhaustive without unnecessarily
discarding raw factors.

| Cache layer | Keyed by / invalidated by | Does not by itself invalidate |
|---|---|---|
| DC network factorization | In-service buses and branches; breaker/switch state; endpoints and incidence; series reactance/susceptance; transformer tap magnitude; connected component; numerical/schema version | Dispatch, load, ratings, fixed phase-shift angle in the standard affine DC model |
| Raw PTDF projection | Network-factor key; branch orientation and ordering; requested bus/branch projection | BA reference, bus capability, dispatch |
| BA-referenced factors | Raw PTDF key; serialized \(\alpha\) and policy version | Base dispatch if \(\alpha\) is already frozen |
| Contingency update | Network-factor key; exact outage/switching set; monitored and contingency definitions; update-algorithm version | Base injections and ratings |
| Base-flow/headroom state | Factor state; injections/dispatch; fixed phase-shifter setpoints; branch ratings and directional limits; remedial actions; operating-state hash | Candidate-set membership |
| Dispatch/set score | BA-factor key; headroom state; ADER mapping; signed action or bus bounds; capability snapshot; metric version | Unqueried bus metadata |
| Constraint frontier/index | Monitored and contingency membership; screening thresholds; coverage policy; index version | Presentation-only metadata |
| Beneficiary-load result | Managed and base state hashes; load POI; BA vector; certified frontier; BA/POI capability snapshots; metric version | Unrelated study results |

In the standard DC formulation, a fixed phase-shifter angle changes the affine
base-flow offset rather than the marginal PTDF. It therefore invalidates the
headroom and downstream result layers. An implementation may conservatively
invalidate raw factors as well, but must never reuse the downstream result.
Tap-magnitude changes invalidate the factorization itself.

Legacy N-1 and `run_injection_study` results that do not serialize their
implicit reference convention are retained as historical records and labeled
`legacy_implicit_single_slack`. They are not comparable to the new
BA-referenced result family and do not seed its caches.

---

## 11. Distribution-to-transmission mapping and degeneracy

The engine accepts buses, not an ADER-specific electrical type. ADER membership
is configuration supplied by the study.

Every distribution node must map explicitly to a transmission bus. If multiple
distribution nodes map to the same transmission bus, their transmission-level
factor columns are identical by construction. Wayne must:

1. detect the identical-column degeneracy;
2. compute the factor once;
3. retain node aliases and separate capability bounds;
4. avoid presenting duplicate electrical rows as independent locations.

If a target load and an ADER node map to the same transmission bus, their
BA-referenced factors are equal and their injection/withdrawal effects have
opposite signs.

For an ADER vector \(x\), positive and negative node actions may offset. If
\(E_Dx-\alpha\mathbf 1^\top x\) is numerically zero, return
`NO_NETWORK_EFFECT` rather than an infinite or undefined network result.

The BA footprint is a parameter. ERCOT may use the whole system; multi-BA
regions such as PJM or MISO must supply the intended footprint explicitly.

---

## 12. Binding-element semantics

A finite transfer level must have exactly one `primary_binding` and may have
zero or more `co_binding` elements within

\[
\tau_T=\max(10^{-4}\text{ MW},10^{-6}T^*).
\]

The primary is the smallest computed limit with a deterministic identifier
tie-break. Co-binding elements are preserved because a source capability and
network constraint, or several network constraints, can bind simultaneously.

The dispatch action and beneficiary load have separate binding scopes:

- dispatch capability or violated/active managed constraint;
- base-state load-transfer binding constraint;
- managed-state load-transfer binding constraint;
- BA or POI capability limit, when applicable.

An incomplete capability result may name the network-binding element but must
not claim an authoritative deliverable MW. An entirely unbounded or
insufficiently specified result uses a non-success status rather than inventing
a physical binder.

---

## 13. Proposed APIs

```text
evaluate_dispatch_action(
    scenario_id,
    ba_reference_participation,
    dispatch_nodes,
    signed_dispatch_mw,
    monitored,
    contingencies
)
```

```text
dispatch_envelope(
    scenario_id,
    ba_reference_participation,
    dispatch_nodes,
    injection_withdrawal_bounds,
    monitored,
    contingencies
)
```

```text
rank_beneficiary_loads(
    dispatch_result_id,
    load_pois,
    ba_reference_participation,
    constraint_frontier_id,
    top_k
)
```

The `ba_reference_participation` policy resolves to a frozen vector before it
enters the sensitivity core. Initial resolvers may include:

| Policy | Derivation | Notes |
|---|---|---|
| `single_reference(bus)` | \(e_{bus}\) | Regression comparison only. |
| `explicit(vector)` | Caller supplied | Named portfolio or fixed study reference. |
| `pro_rata_pmax(footprint)` | Generator Pmax | Asset-snapshot-derived. |
| `pro_rata_headroom(footprint, operating_state)` | Available directional headroom | Dispatch-derived; freeze vector and serialize state. |
| `governor_participation(footprint, snapshot)` | Supplied governor weights | Freeze and serialize source data. |

No resolver logic is allowed inside the factor kernel or its cache lookup.

---

## 14. Result schema

```yaml
status: COMPLETE
method: dc_ba_referenced_beneficiary_load_v1

reference:
  policy: pro_rata_pmax
  footprint: ERCOT
  vector:
    - {bus_id: BUS_1, share: 0.12}
    - {bus_id: BUS_2, share: 0.08}
    # Additional entries omitted; serialized shares must sum to 1.0.
  vector_hash: "..."

dispatch:
  action_id: "..."
  signed_node_changes_mw:
    - {node_id: ADER_104, transmission_bus_id: BUS_905, p_mw: 20.0}
    - {node_id: ADER_221, transmission_bus_id: BUS_917, p_mw: -8.0}
  net_ader_injection_mw: 12.0
  ba_response_mw: -12.0
  capability_snapshot_id: "..."
  capability_complete: true
  feasibility_scope: supplied_action_dc_constraints

constraint_frontier:
  id: "..."
  coverage: CERTIFIED
  monitored_count: 10000
  contingency_count: 100000
  retained_pair_count: 183421
  retention_reasons:
    violation: 12
    low_headroom: 19230
    transfer_bound: 151204
    per_monitor_guard: 8010
    per_contingency_guard: 4980
    numerical_gray_zone: 7

beneficiary_load:
  poi_id: LOAD_772
  transmission_bus_id: BUS_772
  network_limit_base_mw: 91.6
  network_limit_managed_mw: 184.2
  network_benefit_mw: 92.6
  ba_supply_limit_mw: 205.0
  poi_acceptance_limit_mw: 220.0
  deliverable_base_mw: 91.6
  deliverable_managed_mw: 184.2
  deliverable_benefit_mw: 92.6
  capability_complete: true

binding:
  base:
    primary:
      kind: network_constraint
      monitored: M031
      contingency: C118
      limit_mw: 91.6
    co_binding: []
  managed:
    primary:
      kind: network_constraint
      monitored: M123
      contingency: C456
      limit_mw: 184.2
    co_binding:
      - kind: ba_supply_capability
        resource_id: GEN_17
        limit_mw: 184.20003

numerics:
  status: OK
  worst_rcond: 0.00031
  worst_residual: 2.1e-12
  direct_refactor_fallbacks: 7

breakpoints: []

provenance:
  topology_hash: "..."
  operating_state_hash: "..."
  factor_schema_version: 2
  metric_version: beneficiary_load_v1
  dispatch_result_id: "..."
```

`breakpoints` is reserved for future redistribution-on-saturation behavior.

---

## 15. Scale and performance acceptance gate

RTS-GMLC established the rank-one identity and small-case correctness but is
not evidence of screening efficiency. Before implementation approval, run one
ERCOT- or PJM-class case from the model library and record:

1. model dimensions and count of unique factor topologies;
2. base factorization and projection build time;
3. memory footprint of \(H_{M,P}\), \(H_{C,P}\), and retained \(L_{M,C}\) or
   its on-demand representation;
4. exact tiled scan throughput in monitor-contingency pairs per second;
5. deterministic-bound survivor rate and retained-pair reasons;
6. peak resident memory;
7. cached `evaluate_dispatch_action` latency;
8. beneficiary-load pre-ranking and exact reranking latency;
9. number of islanding, near-islanding, and direct-refactor cases;
10. parity against direct post-contingency PTDF rebuilds and DC solves.

The benchmark must publish its case hash, hardware, numeric precision, block
sizes, and completeness mode. If no production-scale model is available, this
acceptance gate remains blocked rather than being inferred from RTS results.

---

## 16. Validation plan

### 16.1 Correctness

- Compare N-1 rank-one factors with directly rebuilt post-outage PTDFs.
- Compare N-k Woodbury factors with direct post-contingency factorization.
- Verify BA-referenced column invariance to the arbitrary PTDF reference bus.
- Verify dispatch superposition for mixed injection and withdrawal vectors.
- Verify box-support values against their constructed extreme points.
- Verify beneficiary transfer ratios against direct DC power-flow sweeps.
- Verify that certified pruning never removes the true binding constraint.
- Exercise identical distribution-to-transmission mappings and zero-effect
  vectors.

### 16.2 Failure behavior

- Base-state and managed-state existing violations.
- Islanding and near-islanding contingencies.
- Missing BA, ADER, or POI capability data.
- Empty or incomplete constraint frontiers.
- Expired computation budgets.
- Co-binding network and capability limits.
- Stale operating-state and participation hashes.

### 16.3 Result-language tests

Automated contract tests should reject results that:

- describe an ADER-to-load energy transfer;
- call a network-only limit "deliverable" when capability is incomplete;
- present a box-extreme witness as an operating point;
- omit the BA vector or constraint-coverage status;
- report a finite complete limit without a primary binding element;
- hide co-binding elements within tolerance.

---

## 17. Wayne integration points

The first implementation should add a factor/sensitivity module rather than
extend the current full-matrix construction inline. Likely integration points:

- `platform/tools/src/gridagent_tools/backends/`: raw solver-specific factor
  acquisition;
- `platform/tools/src/gridagent_tools/`: engine-neutral BA projection,
  dispatch, frontier, and beneficiary-load logic;
- `platform/tools/src/gridagent_tools/study_tools.py`: registered study tools;
- `platform/tools/tests/`: factor parity, cache, numerical, and result-contract
  tests;
- `platform/tools/eval/`: production-scale performance harness;
- study ledger entries: hashes, coverage, capability, binding, and method
  provenance.

The current N-1 implementation computes complete PTDF/LODF and post-flow
matrices before applying the monitored filter. It is a parity oracle for early
tests, not the target large-system query architecture.

---

## 18. Implementation order

1. **Reference and mapping contract**
   - Freeze and serialize \(\alpha\).
   - Add explicit ADER-to-transmission mapping and degeneracy detection.
   - Fence legacy implicit-reference results.
2. **Lazy factor kernel**
   - N-1 rank-one factor operations.
   - N-k update seam, connectivity check, numerical statuses.
3. **Dispatch evaluation**
   - Signed action semantics, capability validation, flow/headroom diffs.
   - Independent set-envelope bounds with mandatory witness framing.
4. **Deterministic frontier**
   - Tiled scan, certified bound pruning, exact fallback, completeness status.
5. **Beneficiary loads**
   - BA-to-load factors, before/after transfer limits, binding transitions.
   - Adjoint pre-ranking followed by exact reranking on the certified frontier.
6. **Scale gate**
   - Production model benchmark and survivor-rate decision.
7. **Tool and ledger integration**
   - Registered APIs, stable result schema, immutable provenance.

---

## 19. Deferred seams

The schema and module boundaries should leave room for, but not implement:

- multi-constraint guarded dispatch LP;
- redistribution when an ADER or BA participant saturates;
- probabilistic electrical embeddings or Cauchy sketches;
- endogenous OPF-derived response inside the factor core;
- corrective redispatch and SCOPF;
- AC sensitivity and voltage/reactive constraints;
- combined transmission-and-distribution factors.

---

## 20. Constraints and questions for the next reviewing agent

The next agent should add constraints rather than silently revising settled
semantics. In particular, review:

1. **Dispatch provenance:** Is a supplied ADER action sufficient for v1, or
   must Wayne also generate a constraint-managing action?
2. **BA feasibility:** Is \(\alpha\) merely an electrical reference, or must
   its resource-level up/down capability always be enforced?
3. **Ratings:** Which normal/emergency/short-term rating applies to each
   contingency and duration?
4. **Contingency semantics:** Are the expected 100,000 records unique outage
   sets, operating cases, remedial-action variants, or combinations?
5. **Constraint classes:** Besides branch MW/MVA limits, must v1 represent
   interfaces, nomograms, voltage constraints, or stability proxies?
6. **Load capability:** What data source supplies POI acceptance limits, and
   when is network-only capability an acceptable product output?
7. **ADER capability:** What data source owns node injection, withdrawal, and
   interface bounds, including timestamp and confidence?
8. **Objective:** Is beneficiary ranking based only on MW gain, or should it
   incorporate contingency probability, constraint severity, duration, or
   commercial value?
9. **Completeness:** What latency budget may return `INCOMPLETE`, and which
   workflows require `CERTIFIED` coverage?
10. **Topology controls:** How should phase-shifter moves, switching actions,
    and remedial-action schemes partition factor versus operating-state caches?
11. **Islands:** Are load and ADER actions allowed on separately balanced
    islands, and how is a BA vector partitioned after islanding?
12. **Operational validation:** Which top-ranked results require DC OPF, SCOPF,
    or AC confirmation before appearing in a customer-facing workflow?

Review additions should identify whether they are:

- a mathematical correctness constraint;
- a data/provenance requirement;
- an operational feasibility requirement;
- a performance acceptance condition;
- a product-language or trust constraint.

---

## 21. Decisions recorded by this draft

1. ADER means the configured set of distributed nodes, not a generator class
   and not the source of energy for a beneficiary load.
2. ADER dispatch and target load are separate BA-referenced transactions.
3. `ba_reference_participation` replaces ambiguous "slack" or "source"
   vocabulary in this study family.
4. Positive ADER injection and negative ADER withdrawal use one signed action
   vector and one frozen BA reference.
5. Beneficiary load is measured by before/after BA-to-load contingency-limited
   transfer capability.
6. Network capability and authoritative deliverability are separate outputs.
7. A finite complete limit has one primary binder and may have co-binders.
8. Deterministic completeness is required for authoritative results; sketches
   are deferred pending production-scale evidence.
9. Legacy implicit-reference results are historical and non-comparable.
10. The DC factor, operating-state, capability, screening, and result caches
    have separate invalidation semantics.
