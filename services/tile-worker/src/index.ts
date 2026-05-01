// Wayne tile-worker.
//
// Validates a short-TTL JWT (minted by web/ /api/tile-token) before issuing
// a Range request to R2 for paid-tier PMTiles. Free-tier tiles are public
// on R2 directly — they should never reach this worker.
//
// Defense-in-depth (brief §10):
//   1. UI hides locked layers (cosmetic)
//   2. /api/tile-token refuses to mint JWTs for tiers a user lacks (semantic)
//   3. THIS WORKER validates the JWT before each Range request (cryptographic)
//
// Phase 2 fills in the JWT verification + R2 fetch. This stub returns 501
// so route wiring can be tested end-to-end before the real auth lands.

import type { TileTokenClaims } from '@wayne/api';

interface Env {
  // R2 binding — wired in wrangler.toml when Phase 0 cloud is stood up.
  TILES?: R2Bucket;
  JWT_PUBLIC_KEY?: string;
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    const match = url.pathname.match(/^\/layers\/([^/]+)\/(\d+)\/(\d+)\/(\d+)\.pbf$/);
    if (!match) {
      return new Response('Not found', { status: 404 });
    }

    const token = request.headers.get('Authorization')?.replace(/^Bearer\s+/i, '');
    if (!token) {
      return new Response('Missing token', { status: 401 });
    }

    // TODO Phase 2: ES256 verify against env.JWT_PUBLIC_KEY, check exp,
    //                check layer in claims.layer_set_hash, check tier.
    const claims = await verifyTokenStub(token, env);
    if (claims === null) {
      return new Response('Invalid token', { status: 401 });
    }

    return new Response(
      JSON.stringify({
        ok: false,
        reason: 'tile-worker stub — JWT verification + R2 Range fetch land in Phase 2',
        layer: match[1],
        z: match[2],
        x: match[3],
        y: match[4]
      }),
      { status: 501, headers: { 'content-type': 'application/json' } }
    );
  }
} satisfies ExportedHandler<Env>;

async function verifyTokenStub(_token: string, _env: Env): Promise<TileTokenClaims | null> {
  // Phase 2 replaces this with real ES256 verification.
  return null;
}
