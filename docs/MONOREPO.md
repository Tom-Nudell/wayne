# Monorepo Layout

This doc captures the structural decisions for the Wayne monorepo: what each top-level directory is, what goes in it, and how to decide where new code lives. Read it once when joining the project; consult it when adding a new package, service, or web surface.

It does NOT cover open-source posture (deferred), hosting provider choices (see the engineering brief at the repo root), or data architecture (see `docs/ARCHITECTURE.md`).

## Principle

Each top-level directory answers a single question: **what kind of thing is this?** Not "what feature does it implement." A new feature usually lives inside an existing top-level dir as a route, module, or sub-package. New top-level directories are reserved for new *kinds* of artifacts.

The structure is plural where we know plurality is coming and flat where it isn't. Premature plural directories with one child are noise. Belated splits when a directory has six children doing different things are friction. We pick the inflection point per directory rather than applying one rule everywhere.

## Top-level directories

```
wayne/
├── web/             customer + admin + marketing (SvelteKit)
├── shared/          TS code with 2+ consumers
├── services/        non-SvelteKit backend deployables (group)
├── platform/        the data + solver + agent stack (group)
├── infra/           Terraform: R2, Workers, DNS, secrets
└── docs/            engineering docs
```

### `web/`

Single SvelteKit app. Contains all customer-facing surfaces — marketing routes (`/`, `/about`, `/pricing`), public app routes (`/map`), authenticated product routes (`/app/*`), admin routes (`/admin/*` gated by role).

One web surface, one auth session, one CSP. SvelteKit handles routing, render strategy (SSG for marketing, SSR for product), and code-splitting; we don't split it across deployables until a real boundary forces us to.

**Promotion rule.** If a second customer-facing web surface emerges with a different deploy boundary — different CSP, different auth audience, different release cadence — add it as a top-level sibling first (`embed/`, `partner-portal/`). When the third sibling is needed, group as `apps/` and move them in.

### `shared/`

TypeScript code consumed by `web/` AND at least one other surface (a `services/*` worker, an internal `platform/*` tool with a TS frontend, etc.). Earned, not aspirational. If only `web/` uses it, it lives in `web/src/lib/`.

Subdirectories are by area, not by consumer:

- `shared/schema/` — TS types derived from the Python source of truth (see "Cross-language seam" below).
- `shared/map/` — MapLibre style.json, paint specs, layer registry, popovers.
- `shared/ui/` — design tokens, brand constants, base CSS, shared layout primitives.
- `shared/api/` — typed clients for `/api/*` endpoints.

**Rule.** No top-level `shared/foo.ts`. Always `shared/<area>/foo.ts`. The areas above are the only ones that exist today; new areas are added when warranted, not because something feels reusable.

**Promotion rule.** When an area inside `shared/` has its own publishable lifecycle, gets a non-trivial public API surface, or needs its own tests/types build, promote it to a top-level workspace package (`packages/<area>`). Until then, subdirectory.

### `services/`

Backend deployables that are NOT SvelteKit. Cloudflare Workers, scheduled jobs, edge functions, microservices. Each is independently deployable with its own runtime config.

This is grouped from day one because we already know we want at least two (tile gating, PNG export rendering) and likely more (scheduled refresh, webhook handlers, abuse rate-limiting). Plurality is not speculative.

**Today.**

- `services/tile-worker/` — Cloudflare Worker that gates paid-tier PMTiles via short-TTL JWTs.

**Adding a service.** New sibling under `services/`. Each service has its own `package.json`, `wrangler.toml` (or equivalent), and `README.md`. Service-to-service shared code goes in `shared/`, not in a sibling service.

### `platform/`

The Wayne data + solver + agent stack. Multi-language (Python + Julia). The parts of the system that produce the artifacts everything else consumes, plus the internal tools that exercise them.

Grouped from day one because we know more packages are coming (distribution-grid, transmission-planner, market-sim modules) and we want a stable place to put them.

**Today.**

- `platform/data/` — ingest → dbt → DuckDB warehouse → exporters (PMTiles + DuckDB-WASM bundles → R2). The Pydantic models here are the schema source of truth.
- `platform/julia/` — PowerSystems.jl studies (power flow, N-1 LODF screening, UC+ED PCM). `Executor` abstraction hides hardware (CPU/GPU/distributed) from callers.
- `platform/tools/` — Python tool surface used by the orchestrator and re-exported via MCP. Single registry, same callable in-process or over MCP.
- `platform/mcp/` — thin MCP server re-exporting `platform/tools/`. Transport, not framework.
- `platform/orchestrator/` — PowerChain-style agent loop: trajectory store, planner LLM, rule-based verifier, durable episode log.
- `platform/atlas/` — internal map viewer for the agent loop. Renders N-1 overload overlays produced by `platform/orchestrator/`. Not customer-facing.
- `platform/app/` — internal local dev server (FastAPI) that wraps `platform/atlas/` with refresh + agent-run buttons. Not customer-facing. Optional; may be retired once `web/` is the day-to-day surface.

**Naming.** Python module names retain the `gridagent_` prefix (`gridagent_data`, `gridagent_orchestrator`, etc.) — that's the canonical namespace established in code. Directory paths drop the prefix because the parent `platform/` supplies it. `platform/data/src/gridagent_data/...` reads cleanly without redundancy.

**No customer-facing concerns inside `platform/`.** No auth, no billing, no tier gating, no Clerk imports, no Stripe imports. If a `platform/*` package starts reaching for those, it has crossed a boundary and the work belongs in `web/` or `services/` instead. The platform packages should be runnable against open inputs alone — that's the property that makes them iterable.

### `infra/`

Terraform modules for cloud configuration: R2 buckets, Cloudflare Workers, DNS, secrets, IAM. Wrangler configs live with their service in `services/<name>/`; cross-cutting infra lives here.

### `docs/`

Engineering documentation: this file, `ARCHITECTURE.md` (system design and data flow), `DATA_LICENSING.md` (the canonical license matrix, kept in sync with the runtime `/attribution` page), `RUNBOOK.md` (incident response, ops procedures).

Customer-facing documentation, if added, lives in `web/src/routes/docs/` or its own deployable, not here.

## Adding new things — decision tree

1. **Customer-facing web surface?** → route inside `web/`. Sibling/promote only if a real deploy boundary forces it.
2. **Backend deployable that isn't SvelteKit?** → new directory under `services/`.
3. **Data, solver, agent, or internal tooling for those?** → new directory under `platform/`.
4. **TS code that 2+ existing surfaces will consume?** → subdirectory under the appropriate `shared/<area>/`. If no area fits, propose a new area and document it here in the same PR.
5. **Cloud infrastructure config?** → `infra/`.
6. **Engineering documentation?** → `docs/`.

If none of the above fits, *that* is when a new top-level directory is appropriate — a new *kind* of thing has appeared. New top-level directories require updating this document in the same PR.

## Cross-language seam

The Pydantic models in `platform/data/` are the source of truth for the `GridFeature` schema, manifest format, and license sidecar shape. `shared/schema/` is generated from them, not hand-maintained.

CI fails the build if the generated TS types drift from the Pydantic source. Generation script lives in `platform/data/`; output is committed to `shared/schema/` so the TS workspace doesn't depend on a Python install at install time.

## Workspace tooling

- **TypeScript:** pnpm workspaces. Workspace root at the monorepo root. Members: `web`, `shared/*`, `services/*`. Lockfile (`pnpm-lock.yaml`) at root.
- **Python:** uv per package, with `[tool.uv.sources]` linking sibling packages by relative path (e.g. `platform/orchestrator/pyproject.toml` references `../tools` for `gridagent-tools`).
- **Julia:** standard Pkg, package per directory under `platform/julia/`.
- **Build orchestration:** GitHub Actions per language. No Bazel-style cross-language build graph at this scale.

## What this doc does not decide

- **Open-source posture.** Inputs (data sources, solvers) are open. Output license decision is deferred and lives in `LICENSE` + the engineering brief.
- **Hosting providers.** Vercel for `web/`, Cloudflare for `services/`, R2 for tiles, Neon for Postgres — these belong in the engineering brief and `infra/` docs. Layout does not depend on them.
- **Data architecture.** Bronze/silver/gold, conflation rules, immutable manifests, point-in-time snapshots — see `docs/ARCHITECTURE.md` and `docs/DATA_LICENSING.md`.
- **Product scope.** Tiers, features, billing — see the engineering brief at the repo root.

## When this document is wrong

When the structure described here no longer matches reality, this doc is the bug, not the code. Update it in the same PR that changes the structure. The point of writing the philosophy down is to catch drift early — if "what kind of thing is this?" stops working as the organizing question, that's a signal a deeper rethink is due.
