# gridagent-orchestrator

Verifiable LLM agent loop modeled on **PowerChain** (Badmus, Sang, Stamoulis,
Pandey — *Verifiable Agentic Orchestration for Power Systems*, arXiv 2508.17094).

## Why PowerChain (and not raw MCP / ReAct)

Two ideas from the paper carry their weight here:

1. **Tool-grounded supervisory signals.** Every tool call returns a
   `signal` dict alongside its value (convergence flag, monotonicity,
   slack magnitude). The orchestrator's `verifier` reads only the signal
   to decide `advance | retry | replan | abort` — the LLM never decides
   whether its own previous action was OK.
2. **Dynamic context from expert-annotated trajectories.** Instead of one
   giant system prompt, we retrieve a small set of vetted reasoning
   trajectories and assemble them into the per-step prompt.

## Layout

```
src/gridagent_orchestrator/
  trajectory_store/       # YAML/Markdown exemplars (hand-seeded)
    baseline_pf.md
    n1_screen_and_mitigate.md
    queue_cluster_impact.md
    single_day_pcm.md
    capacity_add_feasibility.md
  retrieval.py            # embedding-based retrieval over trajectory_store/
  context.py              # assembles per-step prompt
  planner.py              # LLM-driven tool-call proposer
  verifier.py             # rule-based gate over (tool, signal) -> Decision
  episode.py              # durable jsonl log of every step
  run.py                  # CLI entrypoint
```

## Verifier rules (initial)

| Tool                  | Signal field          | Decision                                          |
|-----------------------|-----------------------|---------------------------------------------------|
| `run_power_flow`      | `converged`           | `false` → retry once with flat start, then replan |
| `run_n1_contingency`  | `monotone`            | `false` → abort (numerical issue)                 |
| `run_n1_contingency`  | `n_overloads`         | `>0` → advance (planner proposes mitigation)      |
| `run_production_cost` | `solver_status`       | `!= OPTIMAL` → replan                             |
| `run_production_cost` | `slack_mw`            | `> threshold` → replan (likely missing capacity)  |

## Trajectory harvesting

Every successful episode writes a candidate to
`trajectory_store/_pending/`. Manual review promotes good ones into the active
store — this is how the corpus grows without expert-only authoring.

## LLM provider — local-first

Default planner is a local OpenAI-compatible server (Ollama at
`http://localhost:11434/v1`) running an open-weight model from the **Gemma**
family. No hosted API key required.

Override via env vars or flags:

| Env var                    | Default                          |
|----------------------------|----------------------------------|
| `GRIDAGENT_LLM_BASE_URL`   | `http://localhost:11434/v1`      |
| `GRIDAGENT_LLM_MODEL`      | `gemma3:27b`                     |
| `GRIDAGENT_LLM_API_KEY`    | `ollama` (ignored by Ollama)     |

Same code path works against vLLM, llama.cpp `server`, or any other
OpenAI-compatible endpoint. Hosted providers (Anthropic, OpenAI) can be added
as alternative `LLM` Protocol implementations once we want a head-to-head
benchmark — they are not the default.

## Run

```bash
ollama pull gemma3:27b   # one-time, ~17 GB

uv run gridagent-orchestrator \
  --goal "Add 2 GW of solar at the largest substation in ERCOT and run an N-1 study."
```
