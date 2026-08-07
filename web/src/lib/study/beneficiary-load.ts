import type { Feature, FeatureCollection, LineString, Point } from 'geojson';

export interface BeneficiaryConstraint {
  id: string;
  rank: number;
  monitored_branch_id: string;
  outage_branch_id: string;
  monitored_coordinates: [[number, number], [number, number]];
  outage_coordinates: [[number, number], [number, number]];
  emergency_limit_mw: number;
  base_flow_mw: number;
  managed_flow_mw: number;
  ader_flow_change_mw: number;
  poi_load_factor: number;
  base_transfer_limit_mw: number;
  managed_transfer_limit_mw: number;
}

export interface PoiScreenBinding {
  monitored_branch_id: string;
  outage_branch_id: string;
  transfer_limit_mw: number;
  flow_mw: number;
  limit_mw: number;
  load_factor: number;
}

export interface PoiScreenAderRelief {
  bus_id: string;
  relief_mw: number;
}

export interface PoiScreen {
  rank: number;
  headroom_mw: number;
  next_capacity_mw: number | null;
  potential_capacity_mw: number;
  potential_unlock_mw: number;
  recourse_capacity_mw: number;
  binding: PoiScreenBinding;
  potential_binding: PoiScreenBinding;
  co_binding_count: number;
  ader_relief_mw: PoiScreenAderRelief[];
}

export interface BeneficiaryPoi {
  bus_id: string;
  name: string;
  coordinates: [number, number];
  existing_load_mw: number;
  base_capacity_mw: number;
  managed_capacity_mw: number;
  unlocked_capacity_mw: number;
  rank: number;
  constraints: BeneficiaryConstraint[];
  screen?: PoiScreen;
}

export interface AderNode {
  bus_id: string;
  name: string;
  coordinates: [number, number];
  min_dispatch_mw: number;
  max_dispatch_mw: number;
  dispatch_mw: number;
}

export interface BeneficiaryLoadStudy {
  metadata: {
    study: string;
    snapshot: string;
    model: string;
    balance_policy: string;
    emergency_rating_multiplier: number;
    islanding_outages_excluded: number;
    screened_constraint_pairs: number;
    ader_net_dispatch_mw: number;
    ba_reference_dispatch_mw: number;
    screen_method?: string;
    screen_ader_bounds_mw?: number;
    screen_includes_intact?: boolean;
    screen_note?: string;
  };
  ader_nodes: AderNode[];
  pois: BeneficiaryPoi[];
}

export interface ConstraintProjection extends BeneficiaryConstraint {
  projected_flow_mw: number;
  counterfactual_flow_mw: number;
  projected_loading_pct: number;
  counterfactual_loading_pct: number;
  transfer_gain_mw: number;
}

export function projectConstraint(
  constraint: BeneficiaryConstraint,
  marginalLoadMw: number
): ConstraintProjection {
  const loadFlow = constraint.poi_load_factor * marginalLoadMw;
  const projectedFlow = constraint.managed_flow_mw + loadFlow;
  const counterfactualFlow = constraint.base_flow_mw + loadFlow;
  return {
    ...constraint,
    projected_flow_mw: projectedFlow,
    counterfactual_flow_mw: counterfactualFlow,
    projected_loading_pct: (100 * Math.abs(projectedFlow)) / constraint.emergency_limit_mw,
    counterfactual_loading_pct:
      (100 * Math.abs(counterfactualFlow)) / constraint.emergency_limit_mw,
    transfer_gain_mw: constraint.managed_transfer_limit_mw - constraint.base_transfer_limit_mw
  };
}

export function buildBeneficiaryOverlay(
  study: BeneficiaryLoadStudy,
  selectedPoiId: string,
  marginalLoadMw: number
): FeatureCollection {
  const features: Array<Feature<Point | LineString>> = [];
  const selected = study.pois.find((poi) => poi.bus_id === selectedPoiId) ?? study.pois[0]!;

  for (const node of study.ader_nodes) {
    features.push({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: node.coordinates },
      properties: {
        kind: 'ader',
        bus_id: node.bus_id,
        name: node.name,
        dispatch_mw: node.dispatch_mw,
        direction: node.dispatch_mw >= 0 ? 'injection' : 'withdrawal'
      }
    });
  }

  for (const poi of study.pois) {
    features.push({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: poi.coordinates },
      properties: {
        kind: 'beneficiary-poi',
        bus_id: poi.bus_id,
        name: poi.name,
        rank: poi.rank,
        selected: poi.bus_id === selected.bus_id,
        unlocked_capacity_mw: poi.unlocked_capacity_mw,
        managed_capacity_mw: poi.managed_capacity_mw
      }
    });
  }

  for (const constraint of selected.constraints) {
    const projection = projectConstraint(constraint, marginalLoadMw);
    features.push({
      type: 'Feature',
      geometry: { type: 'LineString', coordinates: constraint.outage_coordinates },
      properties: {
        kind: 'beneficiary-outage',
        constraint_id: constraint.id,
        rank: constraint.rank,
        branch_id: constraint.outage_branch_id
      }
    });
    features.push({
      type: 'Feature',
      geometry: { type: 'LineString', coordinates: constraint.monitored_coordinates },
      properties: {
        kind: 'beneficiary-constraint',
        constraint_id: constraint.id,
        rank: constraint.rank,
        branch_id: constraint.monitored_branch_id,
        outage_branch_id: constraint.outage_branch_id,
        projected_loading_pct: projection.projected_loading_pct,
        counterfactual_loading_pct: projection.counterfactual_loading_pct,
        transfer_gain_mw: projection.transfer_gain_mw
      }
    });
  }

  return { type: 'FeatureCollection', features };
}
