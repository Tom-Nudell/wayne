// Typed contracts for /api/* endpoints in web/.
//
// Both +page.server.ts and +server.ts in web/ import request/response
// shapes from here. services/tile-worker/ also imports the tile-token
// shape so the JWT payload stays in sync between minter and validator.
//
// Endpoints (per brief §4):
//   GET  /api/manifest      -> ManifestResponse
//   POST /api/tile-token    -> TileTokenResponse
//   GET  /api/saved-views   -> SavedView[]
//   POST /api/saved-views   -> SavedView
//   POST /api/exports       -> ExportJob
//   POST /api/stripe/webhook (Stripe-typed; not declared here)

import type { Manifest } from '@wayne/schema';

export interface ManifestResponse {
  readonly manifest: Manifest;
}

export interface TileTokenRequest {
  readonly layers: readonly string[];
}

export interface TileTokenResponse {
  readonly token: string;
  readonly expires_at: string;
}

// Decoded JWT payload — shared between web/ (minter) and
// services/tile-worker/ (validator). Keep field names tight.
export interface TileTokenClaims {
  readonly sub: string;
  readonly tier: 'free' | 'pro' | 'enterprise';
  readonly layer_set_hash: string;
  readonly exp: number;
  readonly iat: number;
}

export interface SavedView {
  readonly id: string;
  readonly org_id: string;
  readonly user_id: string;
  readonly name: string;
  readonly view_state: SavedViewState;
  readonly dataset_version: string | null;
  readonly created_at: string;
}

export interface SavedViewState {
  readonly camera: { readonly z: number; readonly lat: number; readonly lng: number };
  readonly layers: readonly string[];
  readonly filters?: Readonly<Record<string, unknown>>;
}

export interface ExportJob {
  readonly id: string;
  readonly format: 'png' | 'csv';
  readonly status: 'queued' | 'rendering' | 'done' | 'failed';
  readonly result_url: string | null;
}
