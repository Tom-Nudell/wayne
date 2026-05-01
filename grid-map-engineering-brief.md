# Engineering Brief — Commercial US Energy Infrastructure Map

**Codename:** TBD
**Target launch:** v1 paid product in 4–5 months
**Owner:** [you]
**Status:** revised 2026-04-30 — refocused on data quality as the moat, aligned with monorepo structure (`docs/MONOREPO.md`).

---

## 1. What this brief covers

A commercial geospatial web app that visualizes US energy infrastructure (power plants, transmission, substations, gas pipelines, planned upgrades, data centers, EV charging) on an interactive vector map. Free tier for casual exploration; paid tiers unlock detail layers, saved views, exports, point-in-time data snapshots, and (later) API access.

This brief covers **the commercial product only** — the customer-facing web app and the services that gate it. It does NOT cover the Wayne agent platform (`platform/orchestrator/`, `platform/julia/`, `platform/tools/`, `platform/mcp/`), which sits underneath as the engine and is not part of the v1 commercial surface. The product reads from artifacts the platform produces; agent runs are not bundled into the customer experience at v1. The seam is preserved (see §16) so it can be wired up post-launch without a rewrite.

**Defensible value comes from data curation, conflation, and cartography quality** — specifically, from the rendered map looking *right* at every zoom, with audit-grade lineage on every feature. Code is commodity; the moat is the data product.

Inspirational reference: [opengridworks.com](https://opengridworks.com/) — same UX shape, different commercial posture.

---

## 2. Scope at v1

**In scope**
- US-only data layers
- Web app (desktop + responsive mobile)
- Free + Pro tiers, with billing
- Org/seat model groundwork (used at v2 for Enterprise)
- Saved views, PNG export, CSV export of filtered selections
- Lineage/citation surfaced in the UI on click
- **Visual QA gate** in the data pipeline before any tile is promoted to public R2 (§7)

**Out of scope at v1, parked for v2+**
- Non-US geographies (Global Energy Monitor, international OSM coverage)
- Submarine cables (TeleGeography commercial license deferred)
- API access for customers (Enterprise tier)
- SSO/SAML (Enterprise tier)
- Real-time generation telemetry (separate compliance scope)
- User-uploaded layers (trust + abuse problem)
- Mobile apps
- "Run a study from the map" — surfacing `platform/orchestrator/` runs as a Pro feature is post-launch

---

## 3. Stack

| Layer | Choice | Why |
|---|---|---|
| Framework | **SvelteKit (Svelte 5, runes)** | Smaller runtime, fast paint, team preference |
| Workspace | **pnpm workspaces** | TS monorepo: `web/`, `shared/*`, `services/*` |
| Deploy adapter | `@sveltejs/adapter-vercel` | Vercel familiarity |
| Hosting (app) | **Vercel** | Edge HTML, content-hashed static, brotli, sfo1+iad1 |
| Hosting (tiles) | **Cloudflare R2** | Zero egress, cheap storage, custom domain, portable |
| Tile gateway | **Cloudflare Worker** in front of R2 for paid-tier auth checks | Free at scale, sub-ms cold start |
| Map renderer | **MapLibre GL JS** (vanilla, no React wrapper) | License-clean, WebGL, framework-agnostic |
| Tile format | **PMTiles** (single-file vector archives, HTTP Range reads) | One file per layer, no tile server |
| Basemap | **Protomaps Basemaps** (CC-BY) | Commercial-clean, self-hosted PMTiles, MapLibre-native |
| Auth | **Clerk** + Organizations add-on (caveat below) | SOC 2 Type II, billing-ready, SSO at v2 |
| Billing | **Stripe** (Checkout + Customer Portal) | Standard |
| Errors | **Sentry** + Performance + Session Replay | Map debugging gold |
| Product analytics | **PostHog Cloud** | Feature flags double as tier gates |
| Web analytics | **Vercel Web Analytics** | First-party, no cookie banner |
| DB | **Postgres on Neon** (saved views, user state) | Branching, generous free tier |
| Cache / KV | **Upstash Redis** | Presence, rate limits |
| CI/CD | GitHub Actions → Vercel + R2 | |
| IaC for R2/Workers | Wrangler + Terraform module for the rest | Avoids click-ops drift |

**Lock-in posture.** "Local" in our internal vocabulary means *portable, under our full control* — not localhost. Cloud is fine; vendor lock-in is the real concern. Most of the stack above is swappable in days (R2 → S3, Vercel → any Node host, Neon → any Postgres). The exception is **Clerk**, which holds user identity and SSO config — meaningful lock-in. Mitigation: don't depend on Clerk-specific features outside the spec'd allowlist; keep the user export path tested; track Better Auth and Lucia as plausible replacements if Clerk becomes painful.

---

## 4. Architecture

```
        ┌───────────────────────────────────────┐
        │   platform/data  (Python, dbt, DuckDB)│
        │   ingest → bronze → silver → gold     │
        │   → exporters (PMTiles, DuckDB-WASM)  │
        │   → visual QA gate (§7)               │
        └────────────────┬──────────────────────┘
                         │ versioned manifest + PMTiles + license.json
                         ▼
        ┌───────────────────────────────────────┐
        │   Cloudflare R2                       │
        │   /basemap/*.pmtiles                  │
        │   /layers/*.pmtiles                   │
        │   /license/<layer>/*.json             │
        │   /manifest/v<YYYY-MM-DD>.json        │
        └────────────────┬──────────────────────┘
                         │ HTTP Range (public for free, JWT for paid)
                         ▼
        ┌───────────────────────────────────────┐
        │   services/tile-worker (Cloudflare)   │
        │   validates JWT for paid layers       │
        │   (tiles.<domain>)                    │
        └────────────────┬──────────────────────┘
                         │
                         ▼
   ┌──────────────────────────────────────────────────┐
   │   web/  (SvelteKit on Vercel)                    │
   │   +server.ts endpoints:                          │
   │     /api/manifest                                │
   │     /api/tile-token                              │
   │     /api/saved-views                             │
   │     /api/exports                                 │
   │     /api/stripe/webhook                          │
   │   imports shared/{schema, map, ui, api}          │
   └──────┬──────────┬─────────────┬─────────────┬────┘
          ▼          ▼             ▼             ▼
        Clerk      Stripe        Neon PG     Upstash Redis
     (auth/orgs) (billing)      (state)     (rate limits)

  Internal (not customer-facing):
    platform/atlas    — agent dev viewer; renders orchestrator overlays
    platform/app      — local FastAPI surface for dev (optional)
```

For the full monorepo layout and "where does this code live?" decisions, see [`docs/MONOREPO.md`](docs/MONOREPO.md).

**Key design decisions.**

- The app domain (`app.<domain>`) serves SvelteKit. Tiles serve from `tiles.<domain>` (R2 + Worker). Auth cookies stay scoped, CORS clean, tile infra swappable without touching the app.
- **Free-tier tiles are public on R2.** Don't sign them. Save the Worker invocation cost for paid layers.
- **Paid-tier tiles** route through the Worker: `tiles.<domain>/layers/<layer>/<z>/<x>/<y>` validates a short-TTL JWT (signed by SvelteKit `/api/tile-token`) before issuing a Range request to R2. Cache aggressively at the Worker.
- **Nothing premium ships in the JS bundle.** Everything tier-gated must be server-side enforceable.
- **Manifest-driven.** Frontend never hardcodes a tile URL. It fetches `/api/manifest` on boot, which returns the current dataset version. Lets us deploy data without redeploying the app.
- **Schema as a contract.** `shared/schema/` is generated from Pydantic models in `platform/data/`. CI fails on drift. The map and exports rely on the same TS types as the data pipeline.

---

## 5. What we reuse from `platform/`

The Wayne platform already has substantial pieces of what this brief needs. We extend; we don't duplicate.

| Brief concept | Existing in `platform/` | Status |
|---|---|---|
| ETL ingest sources | `platform/data/.../sources/` — HIFLD, OSM, PUDL, GridStatus, LBNL, AFDC, PyPSA-USA, queue_feed | exists; extend with EIA-860M, FRA NARN, FHWA NHS, BLM/USFS, USACE NWN, IM3, Epoch AI, WRI Aqueduct, OurGridFuture |
| dbt warehouse | `platform/data/dbt/` — bronze/silver/gold (network, atlas, market) | exists; extend `gold_atlas` with new sources |
| PMTiles export | `platform/data/.../exporters/to_pmtiles.py` | exists; extend tile-layer registry |
| DuckDB-WASM bundle | `platform/data/.../exporters/to_duckdb.py` | exists |
| Per-feature provenance | `gold_atlas__infrastructure_features.sql` carries `sources` + `licenses` arrays per row | exists |
| MapLibre style + paint specs | `platform/atlas/src/main.ts` (mycelium palette in `theme.ts`) | exists; fork into `shared/map/` and let `platform/atlas` consume the same package |
| Tippecanoe per-layer configs | `platform/data/.../exporters/to_pmtiles.py` (`_TIPPECANOE_FLAGS`) | exists |
| GridFeature Pydantic models | `platform/data/.../schema/` | exists; generate TS to `shared/schema/` (new) |

**New work in `platform/data/` for the commercial product.**
- `license.json` sidecar emitter — written next to every PMTiles archive at export time
- Immutable manifest versioning — `manifest/v<YYYY-MM-DD>.json` on every refresh; `latest.json` is an alias
- Point-in-time snapshots — keep last 36 monthly manifests online; archive older to cold storage
- Pydantic → TS schema generation script with CI drift check
- Visual QA gate (see §7)

**Out of scope for `platform/`.** No customer-facing concerns inside `platform/*` — no auth, no billing, no tier gating, no Clerk/Stripe imports. That boundary is enforced in code review and is one of the reasons platform packages stay iterable. See `docs/MONOREPO.md`.

---

## 6. Data sources & licensing matrix (US v1)

| Source | Layer | License | v1 tier | Notes |
|---|---|---|---|---|
| EIA-860M | Power plants, capacity, fuel | Public domain | Free | Monthly refresh |
| HIFLD | Transmission lines, substations, gas pipelines | Public domain | Free (basic) / Pro (full attributes) | Verify each layer's current license string at ingest |
| FRA NARN | Rail right-of-way | Public domain | Pro overlay | |
| FHWA NHS | Highway centerlines | Public domain | Pro overlay | |
| BLM/USFS Section 368 | Federal energy corridors | Public domain | Pro overlay | |
| USACE NWN | Navigable waterways | Public domain | Pro overlay | |
| AFDC | EV charging stations | Public domain | Free | |
| IM3/PNNL/DOE | Data center atlas | ODbL (OSM-derived) | Pro | Render only, no raw export |
| Epoch AI | Frontier data centers | CC-BY 4.0 | Pro | Attribution per render |
| WRI Aqueduct 4.0 | Water risk overlay | CC-BY 4.0 | Pro | |
| OSM Power layer | International power infra (US slice only at v1) | ODbL | Pro | Render only, no raw export |
| OurGridFuture | Planned transmission projects | Citation required | Pro | **Open question:** confirm commercial use in writing before launch |
| Protomaps Basemaps | Basemap | CC-BY 4.0 | All tiers | Self-hosted PMTiles |

**Deferred to v2 with active license review**
- Global Energy Monitor (CC-BY 4.0 — commercial OK, but their commercial API is the right way to ingest at scale; out of scope for US-only v1)
- TeleGeography submarine cables (CC-BY-SA — only via paid commercial license)

**License hygiene rules (non-negotiable).**
- The data pipeline writes a `license.json` next to every PMTiles archive with: source, retrieval timestamp, license string, citation text, attribution requirements.
- The frontend reads `license.json` and renders required attribution at the zoom levels each license demands.
- The public `/attribution` page is generated from these files at build time. Never hand-edited.
- No raw GeoJSON downloads of ODbL-derived layers. Period. Tile rendering only.

---

## 7. Data quality is the product

This is the section that matters most. The original brief was missing it.

A layer is not "done" because the pipeline runs end-to-end and emits a PMTiles archive. It is done when the rendered map *looks right*: correct cartography, sensible density at each zoom, no overlapping geometries, voltages styled consistently, attribution legible, conflation visually defensible against the upstream sources. Pipeline-runs-clean is necessary. It is not sufficient.

**Failure modes we have already lived through.**
- Geometries clustering into illegible blobs at low zoom
- Voltage classes binned wrong, so a 138 kV line and a 500 kV line render the same color
- Substation points falling on the wrong side of a state border because of CRS confusion
- Attribution text overlapping the map at the zoom levels the license requires it
- Conflation merging two physically separate transmission lines into one
- Sparse or empty regions where coverage was assumed national

**The QA gate.** Before any tile is promoted from `platform/data/`'s build output to the public R2 prefix:

1. **Density statistics** — feature count per layer per zoom bracket; alert on >25% drift from the previous release.
2. **Coverage check** — every state has a non-zero feature count for layers that should be national; flag empty regions.
3. **Visual regression** — render N reference viewports (national, ERCOT, PJM, CAISO, NYISO, MISO South, dense urban, sparse rural) at multiple zooms; pixel-diff against the previous release; manual review on >2% delta.
4. **Attribution presence** — every license-required attribution string is present and readable at the zoom levels its license demands.
5. **Conflation diff** — for layers built from multiple sources, emit a human-readable report of conflicts, merges, and drops; require manual sign-off when row count of unresolved conflicts crosses a threshold.
6. **License check** — every PMTiles archive has a matching `license.json` sidecar; reject the build if any are missing or have changed without human review.

The QA gate is part of the `platform/data/` build — runs in CI on every refresh, blocks promotion. Stats, diff reports, regression screenshots are committed as build artifacts so we can audit what we shipped six months later.

**Cartography as code.** Map style.json, paint specs, and layer definitions live in `shared/map/`, are version-controlled, and have unit tests for the deterministic parts (color classification functions, voltage bins, feature filters). When a stylesheet change lands, the visual regression in the QA gate catches it before customers do.

This is the work the original brief called "boring infrastructure choices." It is not boring. It is the product.

---

## 8. Tile pipeline

**Build per layer** using [tippecanoe](https://github.com/felt/tippecanoe) → `.mbtiles` → [pmtiles convert](https://github.com/protomaps/PMTiles) → `.pmtiles`.

This is already implemented in `platform/data/.../exporters/to_pmtiles.py` with per-layer tippecanoe configs (`_TIPPECANOE_FLAGS`). A transmission line at z6 is one polyline; at z14 it's a thousand — don't share config across layers.

**Basemap.**
- Pull Protomaps Basemaps US-only build (~10 GB) into R2 at `/basemap/protomaps-us-v<date>.pmtiles`.
- Refresh quarterly. Monthly is overkill for basemap data.
- Use Protomaps' published MapLibre style.json as a starting point. Fork it into `shared/map/styles/dark.json`. Treat it as code, not config.

**Tile budget.**
- Free-tier layers (plants, basic transmission, AFDC): bundled into a single combined PMTiles for fewer initial Range requests.
- Pro-tier layers: separate PMTiles per layer for granular auth gating.

---

## 9. Frontend (`web/`)

**Routes**
```
/                       → marketing landing
/map                    → free-tier interactive map
/app/map                → authed map (Pro features unlocked)
/app/views              → saved views
/app/settings/billing   → Stripe Customer Portal embed
/app/settings/team      → org & seats (visible from v2)
/about
/attribution            → generated from license.json files
/privacy
/terms
/admin                  → role-gated internal admin
/api/*                  → server endpoints (see §4)
```

**Map component.**
- One Svelte 5 component: `<MapLibreMap>` in `web/src/lib/map/MapLibreMap.svelte`, consuming `shared/map/`.
- Map instance held in `$state`. Layer toggles drive `$effect` blocks that call `map.setLayoutProperty(...)`.
- Dynamic import MapLibre in `onMount` (browser-only; SSR-safe).
- Don't reach for a wrapper library. Direct MapLibre access is cleaner in Svelte than fighting a React-ported abstraction.

**State.**
- URL is the source of truth for shareable view state (`?z=7&lat=...&lng=...&layers=plants,tx&filters=...`). Use SvelteKit's `$page.url` + `goto({ replaceState: true, noScroll: true })`.
- User auth state from Clerk via `$page.data.session`.
- Tier-gated UI hidden via PostHog feature flags + server-checked on every paid action.

**Performance budget (enforced in CI via `size-limit`).**
- Initial route JS: < 250 KB gzipped (Svelte gives us headroom)
- First map paint: < 1.5s on cable
- TTI: < 2.5s
- p95 tile fetch (cached): < 100ms
- p95 tile fetch (cold): < 400ms

**SvelteKit + Clerk integration notes.**
- Use `@clerk/sveltekit`. Acknowledge it lags `@clerk/nextjs`. Budget a week of integration friction.
- `hooks.server.ts` handles Clerk session loading into `event.locals.auth`.
- Org-aware middleware lives in `web/src/hooks.server.ts`. Block paid routes server-side; never trust client.

**Schema contracts.**
- `shared/schema/` is the only source of `GridFeature`, `Manifest`, and `License` types. Don't redeclare them in `web/`.
- `shared/api/` is the only place `/api/*` request/response shapes are defined. Both `+page.server.ts` and `+server.ts` import from there.

---

## 10. Tier gating

**Tiers**
| Tier | Price (placeholder) | Layers | Features |
|---|---|---|---|
| Free | $0 | Plants, basic TX, AFDC | Pan/zoom, share view URL |
| Pro | $19/mo or $190/yr | All layers, planned upgrades, water risk | Saved views, PNG/CSV export, point-in-time pin |
| Enterprise | Custom | All + API | SSO, audit log, dedicated CSM (v2) |

**Enforcement (defense in depth).**
1. UI hides locked layers behind a paywall modal (cosmetic).
2. `/api/tile-token` refuses to mint JWTs for layers the user's tier doesn't include (semantic).
3. `services/tile-worker/` validates JWT before each tile Range request (cryptographic).
4. PostHog feature flag controls tier rollout / experiments.

A user inspecting the bundle sees nothing premium. There is no "unlocked by editing localStorage" trick available.

---

## 11. Customer surface

**Billing.**
- Stripe Checkout for new subs, Customer Portal for self-serve management.
- Webhook at `/api/stripe/webhook` updates Clerk user metadata with current tier + period end.
- Use Stripe Tax for sales tax handling. Skip Avalara at v1.

**Org/seat model (groundwork at v1, surfaced at v2).**
- Use Clerk Organizations from day one even if UI is single-user.
- Subscription belongs to org, not user. Saves a painful migration later.

**Saved views.**
- Postgres table: `saved_views(id, org_id, user_id, name, view_state_json, dataset_version, created_at)`.
- View state includes camera, layers, filters, optional pinned dataset version.
- Free tier: 3 saved views. Pro: unlimited.

**Exports.**
- PNG: render server-side using a headless browser worker (Browserless or Playwright on a Vercel function with longer timeout). Watermark with attribution per source license.
- CSV: of filtered features only. Stamp every row with `source`, `source_version`, `license_id`. Cap row count per tier.
- Rate-limited via Upstash Redis (Pro: 100 exports/day).

**Presence counter** — defer past v1. Cute but not core.

---

## 12. Observability & ops

**Sentry.**
- Frontend: Performance Monitoring on; Session Replay on for paid users only (consent flow), redact form fields.
- Backend: traces on every `+server.ts` endpoint.
- Source maps uploaded in CI.
- Explicit alerts: error rate > 1%, p95 LCP > 3s, tile-token mint failures.

**PostHog.**
- Track: map opened, layer toggled, view saved, export run, paywall shown, paywall converted.
- Feature flags: every new feature behind a flag for the first 30 days.
- Funnels: free → pro conversion, pro → churn.

**Logging.**
- Vercel logs streamed to Logflare or Axiom (cheaper than Datadog at this stage).
- Structured JSON, one schema across endpoints.
- Per-request correlation ID in headers, surfaced in Sentry tags.

**Status page.**
- Statuspage.io or Instatus on `status.<domain>`.
- Auto-incidents from Sentry alerts.

**SLA targets** (commit only after we've measured a month).
- 99.9% uptime app
- 99.95% tile delivery (R2 + Worker)
- < 4 hour incident response during business hours at v1

**On-call.**
- One-person rotation at v1. Pager via PagerDuty free tier. Quiet hours respected.

---

## 13. Legal & compliance scaffolding

**Before first paying customer.**
- LLC or C-corp formed
- Terms of Service with strong **no-warranty / no-liability / not-for-engineering-or-financial-decisions** disclaimer
- Privacy Policy (GDPR, CCPA, CPRA covered)
- DPA template ready for B2B requests
- Subprocessor list public: Vercel, Clerk, Stripe, Cloudflare, Sentry, PostHog, Neon, Upstash, Logflare/Axiom
- Cookie consent banner only if running ad/marketing pixels (skip them at v1; PostHog and Vercel Analytics are first-party)
- Per-source attribution displayed in-map at zoom levels each license requires
- `/attribution` page enumerating every dataset, version, license, citation, retrieval date

**Defensive posture.**
- Public datasets only at v1. Don't drift toward CIP-regulated data (utility SCADA, real-time generation telemetry) without a separate compliance review.
- All map outputs (PNG exports, embeds) carry attribution stamps generated from `license.json`. Make this a pipeline test.

---

## 14. Security

- All routes default-deny; explicit allowlist for public.
- CSP on every HTML response. `connect-src` allowlists `tiles.<domain>`, Clerk, Stripe, Sentry, PostHog only.
- Tile-signing JWT: ES256, 5-minute TTL, includes user ID + tier + layer-set hash. Worker rejects on any mismatch.
- Stripe webhook signature verified on every call.
- Clerk session validated server-side on every paid endpoint.
- Rate limit every public endpoint via Upstash sliding-window.
- Dependencies pinned, Renovate for weekly bumps, CI runs `npm audit` and fails on highs.
- Secrets in Vercel + Cloudflare env vars only. No `.env.local` checked in. `.env.example` documents required vars.
- All `/api/*` request and response shapes live in `shared/api/`. The contract is type-checked on both sides; no hand-rolled JSON parsing.

---

## 15. Repo layout

The full layout philosophy and decision tree live in [`docs/MONOREPO.md`](docs/MONOREPO.md). Brief snapshot:

```
wayne/
├── web/             SvelteKit — marketing + customer + admin
├── shared/          TS code with 2+ consumers (schema, map, ui, api)
├── services/        non-SvelteKit backend deployables
│   └── tile-worker/ CF Worker for paid-tile JWT gating
├── platform/        Wayne data + solver + agent stack
│   ├── data/        ingest → dbt → exporters → R2
│   ├── julia/       PowerSystems.jl studies
│   ├── tools/       Python tool surface
│   ├── mcp/         MCP transport
│   ├── orchestrator/ agent loop
│   ├── atlas/       (internal) agent dev viewer
│   └── app/         (internal, optional) FastAPI dev server
├── infra/           Terraform: R2, Workers, DNS, secrets
└── docs/            engineering docs (MONOREPO.md, ARCHITECTURE.md, ...)
```

When this brief and `docs/MONOREPO.md` disagree, MONOREPO.md wins; update this brief in the same PR.

---

## 16. Phases

**Phase 0 — Structural foundation (Week 1)**
- Migrate `gridagent-*` → `platform/*` (mechanical: paths, `[tool.uv.sources]`, dbt project root, CI workflow paths, top-level `_*_smoke.py` scripts).
- Set up pnpm workspaces; scaffold `web/`, `shared/{schema,map,ui,api}/`, `services/tile-worker/`.
- Pydantic → TS schema generation script; commit generated `shared/schema/` and add CI drift check.
- Entity, ToS, Privacy, DPA template; license matrix doc lifted to `docs/DATA_LICENSING.md`.
- Vercel project, Cloudflare account, R2 buckets, DNS, custom domain on R2.
- Pick the codename and run a trademark search.

**Phase 1 — Map shell + free tier data + QA gate (Weeks 2–6)**
- SvelteKit app skeleton, `<MapLibreMap>` consuming `shared/map/`, Protomaps basemap on R2.
- Extend `platform/data/` ingest for EIA-860M, AFDC; verify HIFLD basic.
- `license.json` sidecar emitter; immutable manifest versioning.
- **Visual QA gate** wired into `platform/data/` CI (§7). Block tile promotion on failure.
- `/attribution`, `/about`, `/privacy`, `/terms` generated from license sidecars.
- Free tier shipped, no auth, no billing.
- Hard target: < 1.5s first map paint, < 250 KB JS gzipped.

**Phase 2 — Auth, billing, Pro tier (Weeks 7–10)**
- SvelteKit + Clerk integration spike in week 1; bail to Better Auth if friction is worse than budget.
- Stripe Checkout + Portal.
- `services/tile-worker/` JWT gating, minted by `web/` `/api/tile-token`.
- Pro layers: full HIFLD, IM3 data centers, Epoch AI, WRI, OSM power, OurGridFuture (after license confirmation).
- Saved views, PNG/CSV export with attribution stamps.
- Sentry, PostHog wired.

**Phase 3 — Polish & launch (Weeks 11–14)**
- SLA measurement, status page, runbook.
- Beta with 10 design partners.
- Pricing page, marketing site, public launch.

**Phase 4 — Enterprise foundations + agent seam (post-launch, v2)**
- SSO/SAML via Clerk.
- API access with per-customer rate limits and audit log.
- Point-in-time API queries.
- **Agent seam:** surface `platform/orchestrator/` runs as a Pro feature ("explore an N-1 study from this substation"). Existing `overlay_export.py` produces the GeoJSON; web wraps it as a Pro flow.
- Submarine cables (TeleGeography commercial license).
- International expansion (GEM, OSM global).

---

## 17. Open questions / risks

1. **OurGridFuture commercial terms** — must be confirmed in writing before relying on it for a paid feature. Owner: legal/founder. Block on this for Phase 2.
2. **HIFLD per-layer license drift** — DHS occasionally restricts layers. The pipeline must check and fail loudly. Don't ingest a layer whose license string changed without human review.
3. **Vercel egress at scale** — model bandwidth at 10× current public-good site traffic before signing annual commit. If it crosses ~$500/mo, move static assets to R2 with custom domain, keep only SvelteKit on Vercel.
4. **SvelteKit + Clerk friction** — first integration sprint is the highest-risk dev work in Phase 2. Spike in week 1 of Phase 2 before committing to the timeline. Have Better Auth ready as a fallback.
5. **Conflation correctness** — HIFLD vs OSM transmission overlap is a real engineering problem. Plan a dedicated week in Phase 2 specifically for conflation rules + a human-readable diff report. This is the single feature most likely to slip and the most likely source of "looks like crap" failures.
6. **Schema generation drift** — Pydantic → TS contract is load-bearing. If the generation script flakes, types silently lie. Treat the CI drift check as priority-zero.
7. **Visual QA gate cost** — pixel diffs and reference-viewport renders take CI time and storage. Budget for the build minutes; don't let a slow QA gate be the excuse to skip it.
8. **Insurance** — E&O / cyber liability before first paying enterprise customer.
9. **Naming + brand** — pick a name and trademark search before Phase 1 ends.

---

## 18. Headline budget

- **Engineering:** solo + AI agents through MVP. Re-evaluate hiring after Phase 3 based on Pro tier traction.
- **Infra at launch (rough monthly):**
  - Vercel Pro: $20
  - Cloudflare R2: < $5 (storage), $0 egress
  - Cloudflare Workers: free tier covers v1
  - Clerk: $25 + per-MAU above free
  - Stripe: % of revenue
  - Sentry: $26 (Team)
  - PostHog: $0 free tier at our scale
  - Neon: $19 (Launch)
  - Upstash: free tier
  - Logflare/Axiom: $20
  - Statuspage: $0–29
  - **Total infra ≈ $150/mo at launch**, scaling primarily with Clerk MAU and Vercel egress.

---

The defensive bet has not changed but the framing has: this product is **80% data-quality discipline and 20% boring infrastructure choices**. The 20% buys us a fast iteration loop. The 80% — clean cartography, sound conflation, audit-grade lineage — is what nobody else is willing to pay the cost to copy. Spend the engineering budget there.
