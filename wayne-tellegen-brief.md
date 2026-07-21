# Engineering Brief — Tellegen Solver Integration & Study-First Demo UI

**Owner:** trn
**Status:** draft 2026-07-03 — branch `feat/tellegen-solver`. Companion to `wayne-workflows-brief.md` (Phase 1 merged in PR #10).

---

## 1. What this brief covers

Evaluation of two eigenergy open-source packages and the integration plan for each, plus the downstream demo-UI work they unblock:

1. **tellegen** (github.com/eigenergy/tellegen, MIT) — browser/WASM OPF solver, candidate for a new Wayne executor and the kernel of an interactive map engine.
2. **powerio** (github.com/eigenergy/powerio, MIT/Apache-2.0) — power system data I/O library, candidate interchange layer and study system-of-record format.
3. **Demo UI track** — grey out non-studyable nodes, study-first view over the study system of record, results overlaid on the map.
4. **Reference:** atlas.compoundingenergy.com architecture notes (open-mapped energy data done well).

Findings below are from reading both repos at HEAD (2026-07-03 clones), not from running them. Anything not yet verified by execution is marked.

## 2. tellegen — what it actually is

A Rust workspace that compiles the same solver code to native and WebAssembly. From `crates/tellegen/src/` and `docs/src/formulations.md`:

- **Formulations:** DC PF + DC OPF (B–θ, convex QP via Clarabel), AC power flow (Newton–Raphson polar), and the Jabr SOCWR conic relaxation. Full nonlinear AC OPF is explicitly "on the roadmap," not shipped.
- **Sensitivities:** analytical KKT/adjoint columns — ∂LMP/∂demand at a bus, ∂LMP/∂rating at a binding branch — under a versioned contract (`sens/contract.rs`, `docs/src/sensitivity-contract.md`). This powers their signature interaction: drag a slider → sensitivity column previews live → release → exact re-solve in WASM.
- **Study abstraction:** `Study.preview(deltas) / commit / sensitivity` (`study.rs`, exposed in `@tellegen/engine`) — deltas keyed by bus/branch id or powerio row uid.
- **Packaging:** `@tellegen/engine` (framework-agnostic npm, WASM + workers), `@tellegen/svelte` (map, panels, solve card as Svelte components), `tellegen-server` (Axum HTTP: case JSON, cached base solution, SSE solve stream, rate-limited compute), `tellegen-cli`.
- **Scale proof point (their claim):** demo serves ACTIVSg7000 (6,717 buses) and CATS (8,870 buses) solving in-browser. Not verified by us yet.
- **Case parsing is powerio** — the two projects are one stack.

### Verdict as an engine kernel

Yes for what it does; it is not a Wayne backend replacement. The gaps against our `Backend` protocol (`backends/protocol.py`): no N-1/LODF screening and no UC/ED production cost. What it adds that nothing in our stack has: browser-resident solves with instant sensitivity previews, LMP surfaces, and a Svelte component kit that matches our web stack. Treat it as (a) a new **executor for OPF/LMP studies** and (b) the **interactive kernel for the demo map**, alongside pandapower/Sienna, not instead of them.

## 3. powerio — review

The more immediately useful of the two for the platform. It is the format hub we would otherwise end up writing:

- **Readers/writers:** MATPOWER `.m`, PSS/E `.raw` (rev 33/34/35), PowerWorld `.aux`/`.pwb`/`.pwd`, GE PSLF, PowerModels JSON, pandapower JSON, PyPSA CSV, EGRET, GOC3, OPFData, GridFM parquet; OpenDSS/PMD/BMOPF on the distribution side. Round-trips preserve source bytes where the reader kept them; conversions report every dropped field as warnings.
- **`powerio-matrix`:** Ybus, B′/B″, incidence, Laplacian, PTDF-style sensitivity factors as sparse ops.
- **`powerio-pkg` / `.pio.json`:** a package format holding the parsed model **plus provenance** (source file+row per element, parser warnings, validation results), operating points, and — the part that matters most to us — a **`study` block**: an ordered list of commits (demand deltas, rating deltas, field updates) materialized against a base payload, with an `app` map for per-app metadata (`docs/src/study-block.md`). This is a serialization format for exactly the "system of record of all studies we've run" concept in §6.
- **Bindings:** Python package on PyPI with zero required deps (PyO3), C ABI, Julia. Ships an **MCP server** (`python/powerio/mcp/`) exposing convert/parse/matrix/diagnostics — directly usable as Wayne agent tools.
- **Engineering quality signals:** fuzz targets for every binary parser, conversion matrix CI, oracle validation against pandapower/PowerModels/PSSE/pypsa, benchmark suite. This is unusually disciplined for a young project.

**Caveats:** young (schemas are `pio-package 0.1`, BMOPF is a draft spec); the study-block authoring CLI is still an open issue (#185) — reading/materializing is implemented, tooling around it is not; API surface may still move.

**Verdict:** adopt. Use it first as the snapshot↔tellegen bridge (it parses pandapower JSON natively, so our existing pandapower path is a two-hop bridge with fidelity warnings), and evaluate `.pio.json` study blocks as Wayne's study system-of-record format rather than inventing our own.

## 4. Fit with Wayne's backend architecture

Our dispatch is already shaped for this (`study_tools.py`: executor strings; `backends/protocol.py`: three methods). Plan:

- New `backends/tellegen.py` registering executor `"tellegen"`:
  - `power_flow` → tellegen AC PF.
  - `n1_contingency`, `production_cost` → raise `BackendUnavailable` with a pointer to pandapower/sienna (protocol methods are per-backend optional in practice; the dispatcher already surfaces availability).
- New study type `run_dc_opf` (LMPs + dispatch + binding constraints) — pandapower can implement it too, giving us cross-engine parity checks, but tellegen is the motivating engine.
- **Transport decision:** start with `tellegen-server` over HTTP (docker-compose service, same pattern as Sienna-via-container; SSE stream maps onto our episode events). A PyO3 binding of the `tellegen` crate is the later, lower-latency option if the HTTP hop matters.
- **Bridge:** snapshot parquet → pandapower net (existing code in `backends/pandapower.py`) → pandapower JSON → powerio → tellegen network JSON. Later, a direct snapshot→powerio writer drops the middle hop.

## 5. Sequencing

| Phase | Scope | Depends on |
|---|---|---|
| **A. Executor** ✅ | `tellegen` backend (CLI subprocess), `run_dc_opf` tool, parity + eval harness — shipped on this branch, see §8 | nothing |
| **B. Browser engine** | `@tellegen/engine` in the demo web app; serve case JSON from snapshots via powerio; slider-preview interactions on real nodes | A (case bridge) |
| **C. Study record** | `.pio.json` study blocks as the persistent study ledger; every `run_*` appends a commit with provenance | A |
| **D. Demo UI** (§6) | greyout, study-first view, results overlays | B, C |

## 6. Demo UI track (downstream)

Captured here so it's on the record; detailed design belongs in its own pass:

1. **Grey out non-studyable nodes.** Only nodes backed by real snapshot rows (bus_id present, in-service, connected to a solvable island) accept studies. Everything else renders desaturated with no study affordance. Requires a per-node `studyable` flag computed at snapshot load, delivered with the map layer.
2. **Studies run only on real nodes.** Enforce server-side in `/api/study` (reject requests targeting synthetic/display-only features), not just in the UI.
3. **Study-first view.** A toggle that inverts the map: instead of network-first with study overlays, show the ledger of every study run — where, when, what kind, key result — as the primary layer. Backed by the §5C study record; the existing `web/static/overlays/<hash>/provenance.json` output is the seed of this.
4. **Results overlaid on the map.** Generalize the current N-1 GeoJSON overlay into per-study-type overlay contracts (N-1: loading/overloads on branches; DC OPF: LMP choropleth on buses — tellegen's demo bus-color-by-LMP is the reference rendering).

## 7. Atlas reference notes (atlas.compoundingenergy.com)

Inspected via headless browser (map itself needs WebGL, so layers were read from `js/core/registry.js` and network traffic, not rendered):

- **Stack:** MapLibre GL + **PMTiles** — every dataset is a static, pre-built tile archive on the CDN; no tile server, no per-request backend. Layer registry groups: Infrastructure, Markets & Economics, Analysis & Forecasting.
- **Datasets referenced:** plants/substations/cables, ENTSO-E flows + generation, GB BMRS balancing actions, ESO constraints, LMP zones, US interconnection queue, US planned transmission, IRA zones, wind/solar capacity-factor rasters, suitability/exclusion zones.
- **Feature modules visible in source:** site analysis/scoring/report, voltage headroom, comparison panel, asset placer, pipeline mode, forecast panel (open-meteo adapter), CSV export, price ticker, chat.
- **Takeaways for Wayne:** (1) PMTiles is the right shape for our static overlay bundles too — our 677MB locally-built tile bundle problem is exactly what PMTiles solves; (2) their "site analysis" pattern (click anywhere → scored report from loaded layers) is the static-data cousin of our "click a node → run a study" — the differentiator we should lean into is that Wayne's numbers come from live solves, not precomputed rasters.

## 8. Measured results (2026-07-03, RTS-GMLC snapshot, 73 buses / 120 branches / 158 gens)

Phase A is implemented on this branch: `backends/tellegen.py` (subprocess over
the `tellegen` CLI — stateless network-JSON-on-stdin turned out simpler than
the HTTP server for v1; the server remains the browser/deploy path), `dc_opf`
on the Backend protocol with pandapower and tellegen implementations,
`run_dc_opf` in the tool registry, tests in `platform/tools/tests/`, and the
evaluation harness `platform/tools/eval/tellegen_eval.py` (results JSON
committed beside it). Numbers below from that harness.

### 8.1 Correctness: tellegen is right, our pandapower DC OPF is not

Identical MATPOWER input into three solvers:

| solver | objective $/h | LMP range | duals |
|---|---:|---|---|
| scipy/HiGHS reference LP | 177,338 | −8.42 … 30.00 | — |
| tellegen dcopf | 177,363 (**+0.014%**) | −8.44 … 30.00 | ✓ |
| pandapower `rundcopp` | 162,100 (**−8.6%**) | — | `lam_p` ≈ 1e-10, unusable |

pandapower's objective sits *below* the feasible optimum — its solution
violates line limits (it is not enforcing them on this case), and its LMP
duals come back zero. **Any prices-on-map work must not use `rundcopp`.**
Tellegen matches an independent LP to 2 bps, with sane congestion LMPs
(3 binding lines, negative LMP pockets).

Also found and fixed while wiring this up: both backends' "midpoint"
starting dispatch left ~15% of RTS load on the slack bus and the *base-case*
AC power flow had been returning `converged: false`. Dispatch is now
proportional-to-capacity scaled to load; pandapower AC PF converges on the
base case.

### 8.2 Latency (M-series laptop, subprocess overhead included)

| operation | time |
|---|---:|
| tellegen DC OPF (full solve, LMPs+flows+dispatch) | **9.6 ms** |
| snapshot → network JSON bridge | 8.4 ms |
| pandapower `rundcopp` (and wrong, per above) | 23 ms |
| pandapower full LODF N-1 screen | 500 ms |
| powerio native LODF matrix (Rust, in-process) | **3.9 ms** |
| powerio native PTDF | 1.7 ms |
| 24-period DC OPF price sweep (est.) | 0.24 s |

### 8.3 Verdicts on the three strategic options

**(1) Tellegen as pre-compute conditioner — narrow yes, different shape than
expected.** A tellegen base-case solve ranks branches whose top-20 covers 79%
of the branches that actually overload in the full N-1 (94% of overload
pairs), in 10 ms vs 500 ms. But restricting the monitored set doesn't speed
up the LODF screen itself (matrix build dominates), and a screen that drops
6% of overloads is a prioritizer, not a filter. The measured win hiding
underneath: **powerio's Rust LODF is ~130× faster than our
pandapower/pypower path** (3.9 ms vs 500 ms). Recommendation: use tellegen
for the base point + prices, rebuild the N-1 kernel on powerio PTDF/LODF, and
revisit "conditioning" when we hit ACTIVSg7000-scale grids where full screens
genuinely hurt.

**(2) Port Sienna to Rust / holomorphic embedding — not now, and not as a
port.** The measured robustness gap is real but it is an *initialization*
gap, not a language gap: tellegen's flat-start Newton fails on our stressed
base case (105° angle spread) where pandapower's DC-initialized Newton
converges up to 1.4× load; DC OPF stays feasible to 1.6×. The cheap,
high-value move is contributing a DC-init warm start to tellegen upstream
(they're the same Newton otherwise). HELM-class methods only pay off in the
1.4×–1.6× nose region — a voltage-stability product feature we don't have on
the roadmap. Park it; no Sienna port.

**(3) OPF → SCOPF prices on the map — strong yes, this is the winner.**
Verified-correct LMPs in 10 ms means live price choropleths, 24-period
sweeps in a quarter second, and slider-interactive what-ifs are all in
budget today at RTS scale. Path: `run_dc_opf` (done, this branch) → LMP
overlay contract (§6.4) → preventive SCOPF via powerio-prob's
`ScopfInstance`/GOC3 machinery + tellegen solves per contingency (the 94%
screen from (1) picks the contingency set) → hourly production-cost prices
replacing the pandapower stopgap. Note: the SOCWR formulation needs the
`conic` cargo feature (not in the default CLI build); rebuild with
`--features conic` when we want AC-quality price bounds.

## 9. Next phases (logged 2026-07-21, per trn)

1. **Study ledger as full system of record — design discussion required
   before any implementation.** trn's vision is bigger than the §5C/§6.3
   sketch ("full system of record — I don't think you have enough context
   to appreciate yet"). powerio's `.pio.json` study blocks remain a
   candidate substrate, but do not build until the design session happens.
2. **Agent-first mode / broader agent overlay.** Today the agent can only
   kick off N-1 contingency — not even injection/withdrawal studies. The
   expectation: answer arbitrary grid questions, kick off any study type,
   and *learn* new studies (workflows brief Tracks 2–3: distillation,
   composition, glass overlay are the machinery). Early concrete steps:
   injection/withdrawal study tools; route `run_dc_opf` through the agent;
   free-text goal → study routing.

In-flight now (branch `feat/live-map-lmp`): the first three §6/§8.3 items —
LMP choropleth overlay, browser WASM engine with slider previews, and
studyable-node gating. The ledger (§6.3) is explicitly deferred to (1).

## 10. Open questions

1. **CLI subprocess vs PyO3 for the tellegen executor** — *(updated: shipped as CLI subprocess, ~10 ms/solve including process spawn at RTS scale)*. Revisit bindings only if ACTIVSg-scale cases make spawn+serialize costs material.
2. **Solver trust boundary** — tellegen's DC OPF fits piecewise-linear costs to quadratics (documented in `formulations.md`); acceptable for demo LMPs, needs a flag in results provenance so study records say which cost model produced them.
3. **`.pio.json` schema maturity** — pin the schema version we adopt and vendor the JSON Schema files; the format is 0.x and explicitly still moving.
4. **How `studyable` is decided** (§6.1) — snapshot-derived only, or also solver-derived (island/convergence checks)? Lean: snapshot-derived v1, refine with solver feedback.
5. **Upstream relationship** — both projects are active and small; decide early whether we contribute (e.g. a parquet snapshot reader for powerio) or wrap at arm's length.
