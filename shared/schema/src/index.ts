// Generated TS types from the Python source of truth in platform/data.
//
// This file will be replaced by the Pydantic -> TS generation script
// (Phase 0 of grid-map-engineering-brief.md). Until that lands, this is
// a hand-stub of the contracts the rest of the workspace will need.
// Treat this file as a placeholder — do not extend it by hand once the
// generator is in place; CI will fail on drift.

export type FeatureKind =
  | 'plant'
  | 'unit'
  | 'substation'
  | 'transmission_line'
  | 'data_center'
  | 'gas_pipeline'
  | 'distribution_feeder'
  | 'queue_project';

export interface GridFeatureProperties {
  readonly id: string;
  readonly kind: FeatureKind;
  readonly name?: string;
  readonly sources: readonly string[];
  readonly licenses: readonly string[];
}

export interface Manifest {
  readonly version: string;
  readonly generated_at: string;
  readonly layers: readonly ManifestLayer[];
}

export interface ManifestLayer {
  readonly id: string;
  readonly kind: FeatureKind;
  readonly tile_url: string;
  readonly license_url: string;
  readonly tier: 'free' | 'pro' | 'enterprise';
}

export interface LicenseSidecar {
  readonly source: string;
  readonly retrieved_at: string;
  readonly license: string;
  readonly citation: string;
  readonly attribution_required_at_zoom?: number;
}
