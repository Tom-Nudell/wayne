// Wayne energy-infrastructure layers (gold_atlas) for MapLibre.
//
// Sources are PMTiles archives produced by platform/data's `to_pmtiles`
// exporter. Source-layer names match the tippecanoe `-l` flag in
// `platform/data/.../exporters/to_pmtiles.py` (`_TIPPECANOE_FLAGS`).
//
// Aesthetic: the grid as a living mycelial network — calm earth tones,
// branching hyphae for transmission, fruiting bodies for plants. Alarm
// colors are reserved for scenario overlays.

import type { LayerSpecification, SourceSpecification } from 'maplibre-gl';

import { PALETTE } from '../palette.js';

export interface WayneSourceConfig {
  /** Base URL for PMTiles archives (e.g. `/tiles` in dev, R2 URL in prod). */
  readonly tileBase: string;
}

export function wayneSources(
  cfg: WayneSourceConfig
): Record<string, SourceSpecification> {
  const t = (name: string): SourceSpecification => ({
    type: 'vector',
    url: `pmtiles://${cfg.tileBase}/${name}.pmtiles`
  });
  return {
    'wayne-transmission-lines': t('transmission_lines'),
    'wayne-substations': t('substations'),
    'wayne-plants': t('plants'),
    'wayne-gas-pipelines': t('gas_pipelines'),
    'wayne-queue-projects': t('queue_projects')
  };
}

// Hyphae paint — voltage maps to a warm earth gradient (moss → heartwood)
// rather than engineering primaries. Higher voltage = older, woodier hyphae.
const HYPHAE_PAINT: LayerSpecification['paint'] = {
  'line-color': [
    'interpolate',
    ['linear'],
    ['coalesce', ['get', 'voltage_kv'], 0],
    0,
    PALETTE.loam500,
    115,
    PALETTE.hypha115,
    230,
    PALETTE.hypha230,
    345,
    PALETTE.hypha345,
    500,
    PALETTE.hypha500,
    765,
    PALETTE.hypha765
  ],
  'line-width': [
    'interpolate',
    ['exponential', 1.4],
    ['zoom'],
    3,
    0.4,
    8,
    1.6,
    12,
    3.4
  ],
  'line-opacity': 0.85
};

export const wayneLayers: LayerSpecification[] = [
  // Hyphae: transmission as the branching network of a living mat.
  {
    id: 'wayne-transmission-lines',
    type: 'line',
    source: 'wayne-transmission-lines',
    'source-layer': 'transmission_lines',
    layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: HYPHAE_PAINT
  },
  // Subtle gas pipelines — visible but quiet against transmission.
  {
    id: 'wayne-gas-pipelines',
    type: 'line',
    source: 'wayne-gas-pipelines',
    'source-layer': 'gas_pipelines',
    layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: {
      'line-color': PALETTE.loam500,
      'line-width': [
        'interpolate',
        ['exponential', 1.3],
        ['zoom'],
        4,
        0.3,
        8,
        1.0,
        12,
        2.2
      ],
      'line-opacity': 0.55,
      'line-dasharray': [3, 2]
    }
  },
  // Nodes where hyphae braid: substations as small spore points.
  {
    id: 'wayne-substations',
    type: 'circle',
    source: 'wayne-substations',
    'source-layer': 'substations',
    paint: {
      'circle-radius': ['interpolate', ['linear'], ['zoom'], 4, 1.2, 10, 3.6],
      'circle-color': PALETTE.bone,
      'circle-stroke-color': PALETTE.loam900,
      'circle-stroke-width': 0.6,
      'circle-opacity': 0.9
    }
  },
  // Fruiting bodies: generation plants, sized by capacity, colored by fuel family.
  {
    id: 'wayne-plants',
    type: 'circle',
    source: 'wayne-plants',
    'source-layer': 'plants',
    paint: {
      'circle-radius': [
        'interpolate',
        ['linear'],
        ['coalesce', ['get', 'capacity_mw'], 0],
        0,
        2,
        500,
        6,
        2000,
        11,
        5000,
        16
      ],
      'circle-color': [
        'match',
        ['get', 'fuel'],
        'solar',
        PALETTE.fuelSolar,
        'wind',
        PALETTE.fuelWind,
        'natural_gas',
        PALETTE.fuelGas,
        'coal',
        PALETTE.fuelCoal,
        'nuclear',
        PALETTE.fuelNuclear,
        'hydro',
        PALETTE.fuelHydro,
        PALETTE.fuelOther
      ],
      'circle-stroke-color': PALETTE.loam900,
      'circle-stroke-width': 0.5,
      'circle-opacity': 0.85
    }
  },
  // Pinpoints for interconnection-queue projects (mitigation green so
  // they're visible against the calm base; not an alarm color in this
  // context — the layer is opt-in).
  {
    id: 'wayne-queue-projects',
    type: 'circle',
    source: 'wayne-queue-projects',
    'source-layer': 'queue_projects',
    paint: {
      'circle-radius': [
        'interpolate',
        ['linear'],
        ['zoom'],
        4,
        1.2,
        9,
        3.0,
        12,
        5.2
      ],
      'circle-color': PALETTE.mitigation,
      'circle-stroke-color': PALETTE.loam900,
      'circle-stroke-width': 0.5,
      'circle-opacity': 0.8
    }
  }
];

/** IDs of the Wayne layers in z-order (bottom → top). */
export const wayneLayerIds = wayneLayers.map((l) => l.id);
