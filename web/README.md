# web

SvelteKit app — Wayne's commercial US energy infrastructure map. Marketing, customer product, and admin all live here as routes; one deploy, one auth session, one CSP. See `grid-map-engineering-brief.md` at the repo root for the full spec.

## Develop

```bash
# from repo root
pnpm install

# Symlink platform/data's existing PMTiles bundle into web/static/tiles/
# so the dev server serves them at /tiles/*.pmtiles. One-time setup;
# rerun whenever the bundle is regenerated.
pnpm --filter @wayne/web link-tiles

pnpm dev
# → http://localhost:5173
```

In production the same `/tiles/*` URLs route through the Cloudflare Worker (see brief §4) which validates the JWT and Range-fetches from R2. Local dev bypasses the worker — free tiles are public and signed-tier work hasn't shipped.

## Routes

```
/                       marketing landing
/map                    free-tier interactive map (Phase 1)
/app/map                authed map, Pro features unlocked (Phase 2)
/app/views              saved views (Phase 2)
/app/settings/billing   Stripe Customer Portal embed (Phase 2)
/about
/attribution            generated from license.json sidecars
/privacy
/terms
/admin                  role-gated internal admin
/api/*                  server endpoints (manifest, tile-token, exports, stripe/webhook)
```

## Workspace dependencies

- `@wayne/schema` — types from `platform/data` (Pydantic source of truth)
- `@wayne/map` — MapLibre style + paint specs + palette
- `@wayne/ui` — design tokens, brand
- `@wayne/api` — typed contracts for `/api/*`

When you find yourself reaching for the same component or helper across `web/` and `platform/atlas/` (or a future second web surface), promote it into `shared/<area>/`.
