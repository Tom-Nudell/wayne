# web

SvelteKit app — Wayne's commercial US energy infrastructure map. Marketing, customer product, and admin all live here as routes; one deploy, one auth session, one CSP. See `grid-map-engineering-brief.md` at the repo root for the full spec.

## Develop

```bash
# from repo root
pnpm install
pnpm dev
# → http://localhost:5173
```

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
