# tile-worker

Cloudflare Worker that gates paid-tier PMTiles via short-TTL JWTs.

Free-tier tiles are public on R2 and bypass this worker entirely. Pro/Enterprise tiles route through here: the worker validates the JWT minted by `web/` `/api/tile-token`, checks the layer-set hash and tier, then issues a Range request to R2.

## Develop

```bash
# from repo root
pnpm install
pnpm --filter @wayne/tile-worker dev
```

## Configure

Bindings live in `wrangler.toml`. Real R2 + JWT public key get wired in Phase 0 cloud foundations; secrets via `wrangler secret put`.

## Status

Stub. JWT verification + R2 Range fetch land in Phase 2 of the engineering brief. Today the worker returns 501 with the matched route so end-to-end wiring (DNS → custom domain → worker route) can be tested before the auth lands.
