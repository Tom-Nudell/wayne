// POST /api/tile-token
//
// Mints a short-TTL JWT the frontend attaches to paid-tier tile requests.
// Validated by services/tile-worker/ before each Range read against R2.
//
// Phase 2 implementation:
//   1. Validate Clerk session from event.locals.auth
//   2. Check user's tier against the requested layer set
//   3. Sign ES256 JWT with 5-minute TTL, payload = TileTokenClaims
//      (sub, tier, layer_set_hash, exp, iat)
//
// Until then, this endpoint is a 501 stub. The request shape is still
// imported from @wayne/api so the contract stays honest.

import { error } from '@sveltejs/kit';

import type { TileTokenRequest } from '@wayne/api';

import type { RequestHandler } from './$types';

export const POST: RequestHandler = async ({ request }) => {
  const body = (await request.json()) as TileTokenRequest;
  void body;

  return error(501, 'tile-token endpoint not yet implemented (Phase 2: Clerk + ES256 JWT)');
};
