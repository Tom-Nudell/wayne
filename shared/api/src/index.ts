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

import type { Manifest } from "@wayne/schema";

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
  readonly tier: "free" | "pro" | "enterprise";
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
  readonly camera: {
    readonly z: number;
    readonly lat: number;
    readonly lng: number;
  };
  readonly layers: readonly string[];
  readonly filters?: Readonly<Record<string, unknown>>;
}

export interface ExportJob {
  readonly id: string;
  readonly format: "png" | "csv";
  readonly status: "queued" | "rendering" | "done" | "failed";
  readonly result_url: string | null;
}

// ---------------------------------------------------------------------------
// POST /api/study — dev-flagged testability bridge to platform/orchestrator
// (brief §16 Testability track). Not a customer surface: the route 404s
// unless PUBLIC_WAYNE_AGENT=1. Response is application/x-ndjson: one
// StudyEvent per line, streamed as the agent runs.
// ---------------------------------------------------------------------------

/** Fixed workflows the map can launch directly (see orchestrator workflows/). */
export type StudyKind = "n1_contingency" | "dc_opf";

export interface StudyRequest {
  /** Free-form study goal. Mutually exclusive with fromFeature. */
  readonly goal?: string;
  /**
   * Map-click shorthand: run a fixed workflow. The feature labels the
   * scenario; the study itself is grid-wide (locational scoping is
   * Phase 2 parameter-extraction work — see wayne-workflows-brief.md §8 Q4).
   */
  readonly fromFeature?: StudyFeatureRef;
  /** Which fixed workflow to run for fromFeature. Default: n1_contingency. */
  readonly study?: StudyKind;
}

export interface StudyFeatureRef {
  readonly kind: string;
  readonly feature_id: string;
  readonly name?: string;
  readonly lng?: number;
  readonly lat?: number;
}

// One line of the study stream. Mirrors the orchestrator's episode JSONL
// (gridagent_orchestrator.episode) plus the 'overlay' record run.py emits
// and an 'error' record the bridge adds when the subprocess dies.
// 'workflow' / 'escalate' come from the fixed-workflow runner
// (gridagent_orchestrator.workflow): the full node plan is announced up
// front, and 'escalate' marks the hand-over to the planner when a node
// fails verification.
export type StudyEvent =
  | {
      readonly event: "start";
      readonly episode_id: string;
      readonly goal: string;
      readonly ts: number;
    }
  | {
      readonly event: "workflow";
      readonly workflow: string;
      readonly nodes: ReadonlyArray<{
        readonly id: string;
        readonly tool: string;
      }>;
      readonly ts: number;
    }
  | {
      readonly event: "step";
      readonly step: number;
      readonly tool: string;
      readonly arguments: Readonly<Record<string, unknown>>;
      readonly value: unknown;
      readonly signal: Readonly<Record<string, unknown>>;
      readonly decision: "advance" | "retry" | "replan" | "abort";
      readonly attempt: number;
      /** Workflow node ID; null/absent on planner-chosen (agent) steps. */
      readonly node?: string | null;
      readonly ts: number;
    }
  | {
      readonly event: "escalate";
      readonly node: string;
      readonly reason: string;
      readonly ts: number;
    }
  | {
      readonly event: "overlay";
      readonly episode_id: string;
      readonly feature_count: number;
      /** URL path of the primary overlay GeoJSON (first written). */
      readonly overlay_url: string;
      /** Every overlay URL this episode produced (n1_contingency.geojson,
       * dc_opf.geojson, …). overlay_url is always overlay_urls[0]. */
      readonly overlay_urls?: ReadonlyArray<string>;
    }
  | { readonly event: "finish"; readonly summary: string; readonly ts: number }
  | { readonly event: "error"; readonly message: string };
