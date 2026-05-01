# @wayne/api

Typed contracts for the `/api/*` endpoints in `web/`. Single source for request and response shapes.

Both `+page.server.ts` and `+server.ts` in `web/` import from here. `services/tile-worker/` also imports the JWT claims shape so the minter (`web/`) and validator (`tile-worker/`) cannot drift.

Schema types (`Manifest`, `GridFeature`, etc.) come from [`@wayne/schema`](../schema). This package owns *transport* shapes only — what goes over HTTP between client, server, and worker.
