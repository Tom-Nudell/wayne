// AUTO-GENERATED from platform/data/src/gridagent_data/schema/models.py
// DO NOT EDIT BY HAND. Regenerate with:
//
//   python -m gridagent_data.schema.generate_ts \
//       --out shared/schema/src/index.ts
//
// CI fails the build if this file disagrees with the Python source.
//
// See docs/MONOREPO.md ("Cross-language seam") for rationale.


export type FeatureKind =
  | 'plant'
  | 'unit'
  | 'substation'
  | 'transmission_line'
  | 'data_center'
  | 'gas_pipeline'
  | 'distribution_feeder'
  | 'queue_project';

export type Tier =
  | 'free'
  | 'pro'
  | 'enterprise';


export interface GridFeatureProperties {
  readonly id: string;
  readonly kind: FeatureKind;
  readonly name?: string | null;
  readonly sources: readonly string[];
  readonly licenses: readonly string[];
}

export interface ManifestLayer {
  readonly id: string;
  readonly kind: FeatureKind;
  readonly tile_url: string;
  readonly license_url: string;
  readonly tier: Tier;
}

export interface Manifest {
  readonly version: string;
  readonly generated_at: string;
  readonly layers: readonly ManifestLayer[];
}

export interface LicenseSidecar {
  readonly source: string;
  readonly retrieved_at: string;
  readonly license: string;
  readonly citation: string;
  readonly attribution_required_at_zoom?: number | null;
}
