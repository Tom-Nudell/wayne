# Wayne — Session Handoff (2026-07-22)

For the next agent picking up this project. Everything durable is on
GitHub (`Tom-Nudell/wayne`); nothing lives only on a machine except the
local toolchain (see §5).

## 1. Where the project stands

Merged to `main` (PRs #10–#18, all green):

- **Platform**: tellegen DC OPF executor (verified LMP duals),
  pandapower/LODF N-1, injection/withdrawal studies, production-cost sweep,
  fixed workflows (n1_contingency, dc_opf, injection_study) + escalation to
  the agent, rule-based verifier.
- **Agent-first mode v1**: goal-driven planner across all five study tools
  (the N-1-only playbook is gone), MVP guardrail rules explicitly marked as
  such in `planner.py`.
- **Study ledger v1** (the big recent work): append-only object-knowledge
  store with entry⇔commit, staleness pins, lazy revalidation, supersession
  chains, `query_ledger` agent tool. Two docs govern it:
  - `wayne-study-ledger-brief.md` — design intent (v2, trn-reviewed).
  - `wayne-study-ledger-architecture.md` — as-built contract, trn-audited.
    **Read both before touching ledger code; the audit corrections in the
    architecture doc are load-bearing.**
- **Data**: US + GB/EU open-data stacks (EIA-930, USGS, Open-Meteo, BMRS,
  ENTSO-E, carbon, FX), RTS-GMLC snapshot bundle.
- **Map**: LMP choropleth, live what-if slider (tellegen ~10 ms solves),
  studyable gating (server-side 422 on synthetic features).

## 2. In flight — PR open for async review

**`feat/distgrid-bench`** — DistGrid-AgentBench planning eval
(`evals/distgrid_agentbench/`). Benchmark built by a PIQ advisor; trn:
free reign to use. Fetch-at-pin (no vendoring), independent strict scorer,
runner against any OpenAI-compatible endpoint.

**Paused state**: first baseline run stopped at trn's request at 43/200
tasks. Result: **P@1 = 0.0%** for gemma4:26b — mostly genuine (tool-set
coverage 3/43), dominated by skipped loader/setup steps, plus 14
malformed-response errors that need a harness look. Full breakdown in the
eval README; raw rows committed alongside it.

## 3. Next steps, in rough priority order

1. **Finish the benchmark story** (small): investigate the 14 response
   errors (prompt vs extraction); optionally add an args-leniency scoring
   mode; resume the run for the remaining 157 tasks
   (`planning_eval.py --benchmark-dir ... --model gemma4:26b`; ~22 s/task);
   consider a second run with a stronger model for contrast.
2. **Draw the conclusion into the roadmap**: 0% raw planning over a
   108-tool catalog vs Wayne's workflow+verifier scaffold is the concrete
   argument for codified process knowledge. Feed error analysis into
   trajectory exemplars (fuzzy → candidate → codified ladder, ledger brief
   §7).
3. **Ledger next slices** (design settled, not built — architecture doc
   §10): dossiers + artifacts tables, process register, governance
   enforcement (fields already reserved on every entry), model-id hashing.
4. **Known v1 limitations worth fixing when touched** (from trn's audit):
   planner's `query_ledger` wrapper lacks `include_stale`/`snapshot_id`/
   `limit`; entry⇔commit collapses multiple same-tool studies per episode
   (per-tool-name keying).
5. **Map**: study-first view over the ledger (brief §1 consumer #2 — the
   ledger is queryable now; the view is unbuilt).

## 4. Working agreements with trn (do not relearn these the hard way)

- Scoped branches + PRs per subsystem; **merge only on trn's explicit
  word**; keep the working tree clean.
- Design docs before implementation for anything architectural; trn
  audits as-built claims against code — quote call sites, don't paraphrase
  docstrings.
- Minimal changes when asked for minimal; flag MVP-era rules as such in
  code comments.
- Numbers in summaries come verbatim from tool/solver output.
- **Coding tasks run in subagents on a lower-power model** (trn,
  2026-07-22): sonnet-class for real implementation, haiku-class for
  mechanical edits; the main session orchestrates, reviews diffs, and
  runs tests before committing.

## 5. Machine-local setup (not in the repo)

- `tellegen` binary: `cargo install --path crates/tellegen-cli` from
  github.com/eigenergy/tellegen; `GRIDAGENT_TELLEGEN_BIN` or `~/.cargo/bin`.
- `powerio` (PyPI) in the orchestrator venv; venvs via `uv sync`.
- Ollama with `gemma4:26b` for live agent runs (`GRIDAGENT_LLM_MODEL`).
- macOS quirk: if shell/file tools get EPERM on `~/Documents`, it's a TCC
  grant (System Settings → Privacy & Security); new grants need an app
  restart. Working around it via a scratchpad GitHub clone works fine.

## 6. Open questions parked with trn

- Ledger storage engines per facet (duckdb vs JSONL+index) — deferred
  until dossiers force the question.
- Study-determination edge cases: sweeps (one entry with children?),
  retrieval-only answers (currently never entries).
- Process-knowledge governance: who owns a workflow distilled from one
  tenant's studies.
- Whether the benchmark eval should also exercise Wayne's full planner
  scaffold (verifier + ledger consult) rather than the bare model.
