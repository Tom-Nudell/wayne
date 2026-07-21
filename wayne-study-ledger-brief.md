# Design Brief — Wayne Study Ledger (System of Record)

**Owner:** trn
**Status:** design draft v2, 2026-07-21 — incorporates trn's first review
round. No implementation until this survives iteration. Companion to
`wayne-workflows-brief.md` (Tracks 2–3) and `wayne-tellegen-brief.md` §9.

---

## 1. What this is

Wayne's **system of record for grid analysis**: a queryable, append-only
registry of every study run on **any model, any subsystem, any analytical
question** — plus the machinery that makes entries reproducible, auditable,
and consumable by three very different clients:

1. **The map** — the study-first view: "show me everything we know here."
2. **The customer** — dossiers and artifacts (e.g. a PDF interconnection
   report) whose every conclusion links back to ledger entries.
3. **The agent** — its **object-knowledge** store (§7). The agent's
   **process knowledge** lives in a distinct register; the two must not be
   conflated (trn review, v2).

## 2. Model identity and packaging (new in v2)

The ledger does not hang off "a network id." The identity layer:

- **Model** — any analyzable artifact, identified by a **model id (content
  hash)**. A model is not necessarily a grid: transmission networks,
  distribution feeders, **plant models (including dynamic models)**, and
  future kinds are all models. A *network id* is a human-facing name; the
  *model id* is the hash the ledger keys against.
- **Model package** — composition and layering: scenarios are packages
  over a base model (base + change layers), and models compose into
  packages (a plant model packaged with the network it connects to). This
  is the parent ↔ child study concept at the *model* level, and it maps
  naturally onto powerio's package/operating-point/study-block layering
  (candidate serialization, still 0.x).
- **Subsystem** — the common concept encoding **element scope**: a named
  selection of elements (buses/branches/plants/areas) within a model that
  a study is *about*. Entries reference (model id, subsystem), not ad-hoc
  element lists.
- **Common properties layer** — certain physical properties (substation
  locations, connection points, base topology anchors) must be **common
  across models**: a dynamic plant model exists-at / connects-at a given
  substation that the network model also knows. This is a shared reference
  registry all models point into — it is what lets the ledger say "these
  five studies, across three model kinds, concern *this* substation."

*(Open: exact hashing/versioning rules for packages — does a package hash
pin its children's hashes (lean: yes, Merkle-style), and where the
common-properties registry lives relative to snapshots.)*

## 3. What counts as a study (the formalization)

> A study is a question asked of a defined model state, answered by a
> versioned method, whose result could be cited by a conclusion.

A ledger **entry** carries five required parts:

| part | contents |
|---|---|
| subject | model id (+ package refs) + **subsystem** |
| question | typed intent (`n1_screen`, `price_surface`, `injection_screen`, …) + free text |
| model state | package/scenario layers + snapshot manifest hash — the inputs |
| method | tagged workflow version, or agent episode + tool/solver versions |
| results | signals + values, overlay refs, and the full step trace |

Two rules decide entry-hood mechanically:

**Rule 1 — entry ⇔ commit.** Slider previews, sensitivity drags, and
intermediate solves are ephemeral, never entries. A completed workflow
run, a finished agent episode, or a user explicitly pinning a what-if
commits — always an entry. Sub-solves inside a study are its **trace**;
composite studies are one parent entry with child runs.

**Rule 2 — precedent (new in v2).** If a study of this type already
exists — identical or analogous workflow / business objective — then a new
run of that type **is a study**. Precedent forces consistency: the system
never records "300 MW at bus A" while treating "300 MW at bus B" as
ephemeral. Operationally: workflow-typed runs inherit entry-hood from
their type's first entry, so the judgment call happens once per study
*type*, not per run.

Edge cases to pressure-test: batch sweeps (24-hour price run: one entry
with 24 child runs — lean); infeasible runs (entries — infeasibility is a
finding); agent answers produced purely from ledger retrieval without
solving (not entries — they cite entries).

## 4. Dossiers and artifacts

- **Dossier**: a frozen, named selection of entry ids — "the final set of
  analysis inputs and outputs that support these conclusions." Immutable
  once issued; staleness (§6) annotates dossiers, never rewrites them.
- **Artifact**: a deliverable (PDF interconnection report, export, deck)
  in its own table, linking to exactly one dossier. Every claim must be
  sourceable to an entry through the dossier.
- Anticipated consumer: a **report-writing agent** drafting artifacts from
  dossiers — the report as a rendered view of ledger entries.

## 5. Reproducibility — Tier 1, approved

**Approved by trn (v2): Tier-1 semantic reproducibility is the target.**

- workflows registered and **tagged** (versioned specs, git-tracked);
- solver/tool versions pinned per entry;
- snapshot/package **manifest hashes** recorded (cheap; integrity +
  change detection).

Re-running an entry reproduces its numbers to solver tolerance; every
entry carries its full audit trail. **Bitwise snapshot reproducibility
remains rejected** ("extra and unnecessary"); retention is dossier policy.

## 6. Staleness → lazy revalidation (decided in v2: lazy)

When tools evolve or input data refreshes, affected prior studies are
revalidated **lazily** — data-lineage for studies, evaluated on demand:

- Every entry declares dependencies (package hash, workflow tag, tool
  versions) — a dependency graph.
- A dependency change marks downstream entries **stale** (a cheap flag
  flip, no compute).
- Revalidation executes when something *asks*: a dossier is opened, an
  entry is cited, the map renders a stale overlay, the agent retrieves a
  stale fact. Re-execution writes **new entries** linked by
  `supersedes / superseded_by` edges — originals never mutate.
- A revalidation that changes a *conclusion* (not just digits) flags
  affected dossiers and doubles as the **learning outcome signal** (§7):
  process knowledge whose conclusions survive revalidation gains
  confidence; knowledge whose conclusions flip gets demoted for review.

Open: diff thresholds for "conclusion changed"; an optional batch
revalidation maintenance job on top of the lazy default.

## 7. Agent knowledge: object vs process (rewritten in v2)

trn's framing, adopted: the agent needs **two kinds of knowledge**, and
the boundary between the system of record and everything else lives on
this line.

- **Object knowledge** — facts about the world's objects: "what do we
  know about bus 309," "which studies exist for this substation," "what
  did the last screen at this plant conclude." **The ledger IS the object
  knowledge store.** Retrieval over entries answers these.
- **Process knowledge** — knowing *how*: "how to configure a proper load
  injection screening study in ERCOT," including the self-knowledge of
  **whether we have already learned that workflow or not**. This lives in
  a distinct **process register** — the workflow registry generalized:
  each process entry carries its applicability scope (question type ×
  jurisdiction/model kind), its provenance (distilled from which ledger
  entries), and its **confidence grade**.

### Process knowledge has graded confidence

| grade | meaning | representation |
|---|---|---|
| **codified** | there is a correct way to do it — **written, asserted, tested in code** | tagged workflow + assertions + CI tests; citable by dossiers |
| **candidate** | "we think this is the correct process, but need more examples and/or external data to test against" | draft workflow / structured exemplar, flagged; runnable, results enter the ledger at reduced trust |
| **fuzzy** | reasoning patterns, not yet a procedure | trajectory exemplars (today's `trajectory_store/`) |

**Distillation must include a codification step** (trn, v2): promotion
from candidate → codified is not a metadata flip — it requires the
process to be *written as code with assertions and tests* (workflow spec
+ typed ports + verifier rules + test cases — exactly the substrate the
workflow engine already validates). What blocks codification is explicit
on the candidate: "needs N more examples," "needs external benchmark data
to validate against." Every promotion is a ledger event with provenance
("workflow ercot_injection_screen v1.0 codified from entries X, Y, Z").

The agent consults **both stores on every goal**: the process register
first ("do I already know how to do this here?" — codified: use it;
candidate: use but flag; nothing: improvise and record), and the object
store throughout ("what's already known about this subject?").

## 8. Trust tiers

Any run may enter the ledger; **dossiers cite only entries above a trust
threshold**. Trust derives from process-knowledge grade (§7):

1. codified-workflow run on a released package — citable;
2. candidate-workflow or agent-improvised episode — recorded, flagged,
   citable after review;
3. user-pinned what-if — recorded as exploration, not citable.

## 9. Data governance, lineage, permissions (drafted in v2)

Direction-level draft per trn; needs its own detailed pass before build.

- **Access model.** Every ledger object (entry, dossier, artifact, model,
  process-register item) carries `owner`, `tenant`, `visibility`
  (private / tenant / shared / public) from day one. Studies on a
  customer's model are the customer's records; Wayne-run open-data
  studies (RTS, public queues) can be public tier. Subsystem-level
  visibility is out of scope for v1 (model-level is the boundary).
- **License lineage.** The bronze→gold provenance chain (`source`,
  `license` columns) extends through analysis: an entry inherits the
  licenses of every input its package touched; artifacts surface the
  aggregate attribution set (the map's credits pattern, applied to
  reports). A study over ODbL-derived features carries that obligation
  into the PDF.
- **Model custody.** Customer-supplied models (and dynamic plant models,
  often vendor-NDA'd) never leave their tenant. The common-properties
  layer (§2) must be partitioned so shared physical anchors (public
  substation locations) never leak private model content.
- **Process-knowledge governance.** A workflow distilled solely from
  tenant-A entries is tenant-A's unless generalized from public data —
  distillation provenance makes this decidable. Real product question,
  flagged, undecided.
- **Storage is multi-faceted** (trn, v2). Not one store:
  - **working memory** — in-flight episodes, previews, agent scratch
    (ephemeral, hot);
  - **long-term record** — the ledger + dossiers (append-only, indexed,
    the SoR);
  - **model store** — content-addressed models/packages (large, cold,
    hash-keyed);
  - **process register** — workflows/exemplars (small, git-friendly,
    versioned);
  - **artifact store** — rendered deliverables (blobs + metadata table).
  Different durability/access/backup policies per facet; the ledger
  references across facets by hash/id, never by path.

## 10. Deliberately not decided yet

- Storage engines per facet (duckdb / JSONL+index / object store mix).
- `.pio.json` as the package serialization (candidate; schema 0.x).
- Retrieval implementation, and whether object vs process knowledge share
  an embedding space (lean: separate indexes, shared entity vocabulary).
- Ledger write path: orchestrator-side vs dedicated service.
- Package hashing rules (Merkle over children — lean yes).

## 11. Iteration log

- 2026-07-21 v1 — initial draft from the design session: scope, entry ⇔
  commit rule, dossier/artifact split, Tier-1 reproducibility proposal,
  revalidation direction, three-store memory sketch, governance opened.
- 2026-07-21 v2 — trn review round 1: model/package/subsystem identity
  layer added (model id ≠ network id; models of any kind; common
  properties layer); precedent rule added to study determination; Tier-1
  reproducibility **approved**; revalidation decided **lazy**; memory
  section rewritten around **object vs process knowledge** with graded
  confidence and a mandatory codification step in distillation;
  governance + multi-faceted storage drafted. Planner MVP-guardrail
  caveat landed separately on PR #15.
