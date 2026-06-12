# Engineering Brief — Wayne Workflows & Conversational Agent Mode

**Owner:** trn
**Status:** draft 2026-06-11 — follows the map agent-study track (PR #9, dev-flagged study loop). Companion to `grid-map-engineering-brief.md` §16 Phase 4.

---

## 1. What this brief covers

Three connected capabilities on the Wayne agent platform:

1. **Workflows** — N-1 contingency analysis becomes a *learned, fixed* workflow the agent executes deterministically, never re-planning. The LLM leaves the step-selection loop entirely for known studies.
2. **Workflow composition** — new workflows are assembled from a library of learned **activities** (typed nodes on a workflow graph), either distilled from successful agent episodes or composed via conversation.
3. **Glass overlay** — a conversational text interface over the map to ask Wayne for studies beyond N-1 and to guide the agent mid-session, replacing the read-only event log.

Everything here stays behind `PUBLIC_WAYNE_AGENT=1`. Nothing ships in the customer bundle path.

## 2. Why workflows, stated plainly

Today every map-button study run pays the full planner cost: the LLM re-derives the same 4-step sequence (`list_data_snapshots → query_grid → create_scenario → run_n1_contingency`) that is already hard-coded as prose in `_INSTRUCTIONS` (`planner.py:41–75`) and enforced by the verifier. The plan never varies; only the parameters do. That's the definition of a workflow:

- **Deterministic** — same steps every time, auditable, no request-limit babysitting (`GRIDAGENT_MAX_REQUESTS` exists only because models loop).
- **Fast** — zero planner round-trips to Ollama; runs at tool speed.
- **UX payoff** — the UI can render the full step list *upfront* with pending/running/done states instead of a trailing log (see §7).

The LLM's remaining jobs for a workflow run: extract parameters from the user's request (optional — the map button supplies them structurally), and narrate the result summary (optional).

## 3. Core abstractions

### 3.1 Activity (node)

A typed wrapper around an existing tool. Tools already have `ToolSpec(name, description, fn, schema)` in `registry.py:17–25`; an activity adds explicit **ports** so composition can be validated statically:

```yaml
activity: create_scenario
consumes: { snapshot_id: SnapshotId }
produces: { scenario_id: ScenarioId }
verify: default            # verifier rule name; rules stay in verifier.py
retry: { max_attempts: 2 } # mirrors current _power_flow_rule behavior
```

Ports are derived from what tools already emit in `ToolResult.signal`/`value` (e.g. `create_scenario` → `signal.scenario_id`, `run_n1_contingency` → ranking). v1 declares ports by hand for the 7 registered tools. *(Shipped: `ACTIVITY_PORTS` in `gridagent_orchestrator/workflow.py` — orchestrator-side, not `platform/tools/`; moving them next to tool registrations is open for Track 2.)*

### 3.2 WorkflowSpec

A small DAG over activities, stored as YAML in `platform/orchestrator/src/gridagent_orchestrator/workflows/`. Shipped format (see `workflows/n1_contingency.yaml` for the canonical example):

```yaml
workflow: n1_contingency
description: Screen N-1 contingencies on the newest snapshot.
inputs:
  scenario_name: { default: N-1 baseline }
  change_table:  { default: {} }
nodes:
  - id: snapshot
    tool: list_data_snapshots
  - id: branches
    tool: query_grid
    bind: { table: branches, snapshot_id: $snapshot.latest }
  - id: scenario
    tool: create_scenario
    bind: { name: $inputs.scenario_name, change_table: $inputs.change_table, snapshot_id: $snapshot.latest }
  - id: n1
    tool: run_n1_contingency
    bind: { scenario_id: $scenario.scenario_id }
summary: "N-1 screen on {snapshot.latest}: {n1.n_overloads} overload(s) …"
```

Binding syntax: `$inputs.*` (workflow parameters), `$<node>.<port>` (upstream output), literals. `goal`/`summary` templates render the episode's display goal and deterministic finish summary from the same reference grammar. No conditionals or loops in v1 — a workflow is a straight-line DAG; anything needing judgment falls back to agent mode.

### 3.3 Workflow runner

A new `run_workflow(spec, inputs, episode)` in the orchestrator that:

- Topologically executes nodes, calling `TOOL_REGISTRY[name].fn()` directly — **no pydantic-ai agent, no model in the loop**.
- Applies the same `Verifier.decide()` per node (`verifier.py:51–70`). `RETRY` re-runs the node up to its policy; `REPLAN` (and tool exceptions, and retry exhaustion) **escalates to agent mode** with the episode-so-far as context (the workflow's failure is the agent's starting state — this is the safety valve). `ABORT` is **terminal, no escalation** — it means a numerical bug (e.g. non-monotone ranking), which the agent can't fix either.
- Emits the same `EpisodeStep` JSONL records and `on_event` callbacks (`episode.py:23–51`), so `overlay_export.py`, the NDJSON bridge, and the StudyPanel work **unchanged**. One new event: `{event: "workflow", workflow, nodes: [...]}` emitted at start so the UI can render the full plan upfront.

### 3.4 Routing

How a request becomes a workflow run vs. an agent run:

- **v1 (structural):** the map button's `StudyRequest.fromFeature` routes straight to `n1_contingency`. A free-form `goal` with no matching workflow goes to the existing planner path. CLI: `python -m gridagent_orchestrator.run --workflow n1_contingency --inputs '{...}'`.
- **v2 (matcher):** a cheap classifier (the existing `retrieve()` keyword-overlap stub in `retrieval.py`, upgraded to embeddings) matches free-text requests to workflow descriptions; below a confidence threshold, agent mode. The router's choice is always shown to the user and overridable ("just run the N-1" / "no, plan this fresh").

## 4. Track 1 — N-1 as the first workflow

Deliverable: map-button N-1 runs execute the fixed workflow with zero LLM planning round-trips.

1. `WorkflowSpec` + loader + registry (mirror `TOOL_REGISTRY` shape).
2. Activity port declarations for the 7 existing tools.
3. Workflow runner with verifier integration, escalation-to-agent on `REPLAN`/`ABORT`, and episode/event emission.
4. Hand-authored `n1_contingency.yaml` (it's the playbook from `_INSTRUCTIONS`, transcribed).
5. `--workflow` CLI flag in `run.py`; `/api/study` routes `fromFeature` requests to it.
6. New `workflow` event in `StudyEvent` union (`shared/api/src/index.ts:92–118`); StudyPanel renders the upfront node list with live states (§7, minimal version).

Acceptance: an N-1 run from the map completes with `request_limit` usage = 0 planner calls, identical overlay output to the agent path, and survives the same fault injections the verifier already gates (non-convergence → retry, non-monotone → abort → escalation).

## 5. Track 2 — learning and composing workflows

Deliverable: Wayne can turn a successful novel episode into a reusable workflow, and a user can compose one conversationally.

1. **Distillation.** An episode JSONL is already `(tool, arguments, signal, decision)` per step — structurally a workflow trace. `wayne workflow distill <episode_id>`: extracts the ADVANCE-path steps, generalizes literals into `$inputs.*` parameters (LLM-assisted: "which arguments were specific to this request?"), emits a draft `WorkflowSpec`. **Human approves before it enters the registry** — distillation proposes, never auto-promotes.
2. **Save-as-workflow in session.** After a successful free-form agent episode, Wayne offers: *"Save this as a workflow?"* — same distillation path, triggered conversationally.
3. **Compose from activities.** "Build me a workflow that creates a 20% load-growth scenario then runs production cost" → LLM emits a `WorkflowSpec` constrained to the activity library; static validation (ports match, DAG acyclic, inputs resolvable) + dry-run against a small snapshot before saving.
4. **Validation gate.** Every new workflow must pass: schema validation → port type-check → dry-run with synthetic inputs → human approval. Stored specs are git-tracked (workflows are code).

This closes the learning loop: agent episodes → distilled workflows → fewer agent episodes. Trajectory exemplars in `trajectory_store/` remain the few-shot guidance for *novel* goals; workflows replace them for *recurring* ones.

## 6. Track 3 — glass overlay (conversational agent mode)

Deliverable: a chat dock over the map to request any study, watch workflow progress, and steer the agent — replacing the read-only log for interaction (the log remains as the audit trail).

### 6.1 Session model

Keep NDJSON-over-fetch (no WebSocket — fits the existing client, avoids Vercel WS friction; this is dev-flagged/local anyway). Add a **turn-based session**:

- `POST /api/study` gains `{session_id?, message?}`. The server keeps a session registry (`session_id → orchestrator subprocess or serialized message history`). pydantic-ai message-history serialization makes the stateless-replay variant possible if keeping subprocesses alive proves fragile.
- Each turn streams events exactly as today; the turn ends with `finish` or a new `ask` event.
- **Agent asks back:** add a `ask_user` deferred tool to the planner — when the agent needs clarification ("which snapshot?", "mitigate or just report?"), the turn ends with `{event: "ask", question, options?}` and resumes on the next POST. This is the cheap, robust form of "guiding the agent": steering happens at turn boundaries, not mid-tool-call. True mid-run interjection is explicitly deferred.

### 6.2 UI

New `ChatDock.svelte` in `web/src/lib/study/` — bottom-center glass panel matching the existing aesthetic (loam bone `rgba(243,237,224,0.96)`, blur backdrop, Inter 0.85rem, tokens from `@wayne/ui`):

- **Input line** with suggestion chips seeded from the workflow registry ("Run N-1 here", "Production cost, 24h", "Stress test").
- **Transcript** interleaving user turns, Wayne's narration, and structured cards:
  - **Workflow card** — the upfront node graph from the `workflow` event, nodes ticking pending → running → done/retry/escalated. Straight-line DAG renders as a step rail; no graph library needed in v1.
  - **Result card** — overlay chip ("38 overloads drawn", click toggles `wayne-study-overlay` layer), worst-loading headline, link to episode log.
  - **Ask card** — the `ask` event rendered as buttons/free-text reply.
- **Escalation visibility** — when a workflow escalates to agent mode, the card says so explicitly. Workflow steps and improvised agent steps must be visually distinct (deterministic vs. model-chosen is the core trust distinction of this whole design).
- StudyPanel survives as the collapsed "details" view of the same event stream.

## 7. Sequencing

| Phase | Scope | Depends on |
|---|---|---|
| **1. Workflow engine + N-1** (Track 1) | Spec, runner, ports, n1 yaml, routing, minimal upfront-steps panel | nothing |
| **2. Glass overlay core** (Track 3, partial) | ChatDock, session turns, free-text goal → router → workflow or agent, ask-back | Phase 1 (workflow event + router) |
| **3. Learning loop** (Track 2) | Distill, save-as-workflow, compose, validation gate | Phases 1–2 (specs to target, chat to drive it) |
| **4. Polish** | Workflow suggestion chips from registry, escalation UX, embedding-based router | 1–3 |

Phase 2 before 3 deliberately: composing workflows conversationally needs the conversation surface to exist, and the chat dock delivers user-visible value immediately, while distillation is invisible until there are novel episodes worth saving.

## 8. Open questions

1. **Subprocess sessions vs. stateless replay** — keeping the orchestrator subprocess alive across turns is simplest but leaks on crashed tabs; serialized message-history replay per turn is stateless but re-pays model context. Decide in Phase 2 with a spike.
2. **Where do user-composed workflows live** — repo-tracked YAML (auditable, but requires a writable checkout) vs. `GRIDAGENT_DATA_ROOT/workflows/` (runtime-writable, but drifts from git). Lean: repo for built-ins, data-root for user-composed, registry merges both.
3. **Escalation policy** — when a workflow node hits `REPLAN`, does the agent get the *whole* remaining workflow as its goal, or just the failed node? Lean: whole remaining goal, with the completed prefix as episode context.
4. **Parameter extraction for free-text workflow runs** — a small LLM call to map "N-1 on the Diablo Canyon scenario with 20% more load" onto workflow inputs. Bounded and schema-constrained, but it's the one place a model sits in front of a "deterministic" run; surface the extracted inputs for confirmation before executing.
