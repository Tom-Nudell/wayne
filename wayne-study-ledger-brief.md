# Design Brief — Wayne Study Ledger (System of Record)

**Owner:** trn
**Status:** design draft 2026-07-21 — captures the trn/agent design discussion.
No implementation until this survives iteration. Companion to
`wayne-workflows-brief.md` (Tracks 2–3) and `wayne-tellegen-brief.md` §9.

---

## 1. What this is

Wayne's **system of record for grid analysis**: a queryable, append-only
registry of every study run on **any network, any bus, any analytical
question** — plus the machinery that makes entries reproducible, auditable,
and consumable by three very different clients:

1. **The map** — the study-first view: "show me everything we know here."
2. **The customer** — dossiers and artifacts (e.g. a PDF interconnection
   report) whose every conclusion links back to ledger entries.
3. **The agent** — episodic memory ("what do we know about bus 309?") and
   the substrate its learning loop consolidates from.

Decided framing: this is **one event store with three consumers**, not a
ledger plus a separate learning system.

## 2. What counts as a study (the formalization)

> A study is a question asked of a defined grid state, answered by a
> versioned method, whose result could be cited by a conclusion.

A ledger **entry** carries five required parts:

| part | contents |
|---|---|
| subject | network id + element scope (buses/branches/areas touched) |
| question | typed intent (`n1_screen`, `price_surface`, `injection_screen`, …) + free text |
| grid state | snapshot reference (+ manifest hash) and change-table — the inputs |
| method | tagged workflow version, or agent episode + tool/solver versions |
| results | signals + values, overlay refs, and the full step trace |

**The entry ⇔ commit rule.** What is *not* a study is decided mechanically,
not philosophically, using the preview/commit seam the platform already has:

- Slider previews, sensitivity drags, and intermediate solves inside a study
  are **ephemeral** — never entries.
- A completed workflow run, a finished agent episode, or a user explicitly
  pinning a what-if **commits** — always an entry.
- Sub-solves inside a study are its **trace**, not sibling entries.
  Composite studies (an interconnection screen = OPF + N-1 + diff) are one
  parent entry with child runs.

*(trn: "determining what counts as a study is a bit tricky" — this rule is
the current proposal; edge cases to pressure-test in review: batch sweeps
(24-hour price runs: one entry or 24?), failed/infeasible runs (proposal:
entries — an infeasibility is a finding), and agent runs that answer purely
from ledger retrieval without solving (proposal: not entries).)*

## 3. Dossiers and artifacts

- **Dossier**: a frozen, named selection of entry ids — "the final set of
  analysis inputs and outputs that support these conclusions." Immutable
  once issued.
- **Artifact**: a deliverable (PDF interconnection report, export, deck) in
  its own table, linking to exactly one dossier. Every claim in the
  artifact must be sourceable to an entry through the dossier.
- Anticipated consumer: a **report-writing agent** that drafts the artifact
  *from* the dossier — the report becomes a rendered view of ledger
  entries, which is what makes it defensible.

## 4. Reproducibility (decided)

Target is **Tier 1 — semantic reproducibility**:

- workflows are **registered and tagged** (versioned specs; already
  git-tracked YAML);
- solver/tool versions pinned per entry (tellegen build, pandapower
  version, gridagent-tools rev);
- snapshot **manifest hashes** recorded per entry — hashing is nearly free
  and gives integrity checking + change detection.

Re-running an entry reproduces its numbers to solver tolerance, and every
entry carries a complete audit trail (the episode trace) for debugging.

**Rejected: Tier-2 bitwise snapshot reproducibility.** trn 2026-07-21:
"the whole perfect bitwise snapshot… feels extra and unnecessary." We keep
the hashes (cheap), not the guarantee. Snapshot *retention* is a policy
decision per dossier, not an architectural mandate.

## 5. Staleness → automatic revalidation (design direction)

trn's instinct, adopted as the working design: when **tools evolve** or
**input data refreshes**, the system automatically re-runs / re-validates
affected prior studies, with lineage — *data lineage for studies*.

Sketch:

- Every entry declares its dependencies: snapshot version, workflow tag,
  tool/solver versions. That is a dependency graph (dbt for studies).
- A dependency change marks downstream entries **stale**; a revalidation
  pass re-executes them and writes **new entries** linked by
  `supersedes / superseded_by` edges — never mutating the originals.
- A revalidation that changes the *conclusion* (not just digits) is the
  interesting event: it flags affected dossiers/artifacts and is exactly
  the **outcome signal the learning loop currently lacks** (a workflow
  whose conclusions keep surviving revalidation earns trust; one whose
  conclusions flip gets re-examined).

Open sub-questions: revalidate eagerly vs lazily-on-query (cost control);
diff thresholds for "conclusion changed"; whether issued dossiers pin to
their original entries forever (lean: yes — dossiers are frozen; staleness
annotates them, never rewrites them).

## 6. Memory architecture (three stores, one substrate)

| memory | holds | embryo in code today | consolidation |
|---|---|---|---|
| episodic / factual | what was studied, what was found | episode JSONL (write-only, unqueryable) | becomes the ledger; retrieval answers "what do we know about X" |
| exemplar | fuzzy know-how, not yet rigid | `trajectory_store/*.md` (hand-written) | harvested from good episodes |
| procedural | learned workflows | workflow registry (hand-written YAML) | distilled from recurring exemplars, then **tagged** |

**Distillation is memory consolidation** (episodic → exemplar →
procedural), and each promotion is itself a ledger event with provenance:
"workflow v1.2 distilled from entries X, Y, Z." The tagging that gives us
reproducibility (§4) and the learning loop's promotion gate are the same
mechanism. Per trn: the ledger is *not* the agent's only memory — the
procedural store (learned workflows) is a first-class peer, and the agent
must track both.

Open: one retrieval index or two (procedural "how do I run this study" vs
factual "what do we know about this bus" may want different embedding
spaces); when a workflow's pinned tools evolve, does it keep running pinned
or enter revalidation (§5 applies to workflows too).

## 7. Trust tiers

Any run may enter the ledger; **dossiers cite only entries above a trust
threshold**. Working ladder (to refine):

1. tagged-workflow run on a released snapshot — citable;
2. agent-improvised episode — recorded, flagged, citable after review;
3. user-pinned what-if — recorded as exploration, not citable.

## 8. Data governance, lineage, permissions (opened, undesigned)

Raised by trn as a companion problem: who may see which networks, studies,
and dossiers; how source-data licenses propagate into entries and artifacts
(the provenance `source`/`license` columns already flow bronze→gold — the
ledger extends that chain to *analysis*); multi-tenant separation when
customer networks enter the system. Needs its own design pass; the schema
should reserve `owner`/`visibility`/`license` fields from day one so
governance is additive, not a migration.

## 9. Deliberately not decided yet

- Storage engine (duckdb table vs append-only JSONL + index vs both).
- Whether `.pio.json` study blocks serialize the grid-state part of an
  entry (candidate, schema still 0.x — see tellegen brief §3 caveats).
- Retrieval implementation (the MiniLM upgrade to `retrieval.py`).
- Ledger write path: orchestrator-side (every episode commits) vs a
  dedicated service.

## 10. Iteration log

- 2026-07-21 — initial draft from trn/agent design session: scope (any
  network/bus/question), analysis-vs-artifact split with lineage, entry ⇔
  commit rule proposed, Tier-1 reproducibility decided (bitwise rejected),
  auto-revalidation direction adopted, three-store memory model, governance
  opened.
