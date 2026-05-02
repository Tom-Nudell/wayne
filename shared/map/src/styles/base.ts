// MapLibre StyleSpecification for the Wayne base map.
//
// Composes the Protomaps light theme as a basemap with Wayne's
// energy-infrastructure layers (transmission, substations, plants, gas
// pipelines, queue projects) inserted between basemap fills and place
// labels — so the data sits on top of the geography but the labels
// stay readable.
//
// Tile sources use VITE_TILE_BASE so the same code runs against:
//   - dev:  /tiles (web/static/tiles, populated by web/scripts/link-tiles.sh)
//   - prod: https://tiles.<domain>/layers (Cloudflare Worker → R2)

import { layers, namedTheme } from 'protomaps-themes-base';

import { wayneLayers, wayneSources } from '../layers/wayne.js';
import { PALETTE } from '../palette.js';

const BASEMAP_TILES_URL = 'pmtiles://https://demo-bucket.protomaps.com/v4.pmtiles';

const BASEMAP_GLYPHS_URL =
  'https://protomaps.github.io/basemaps-assets/fonts/{fontstack}/{range}.pbf';

const ATTRIBUTION =
  '<a href="https://protomaps.com">Protomaps</a> © <a href="https://openstreetmap.org">OpenStreetMap</a>';

const TILE_BASE: string =
  (import.meta as ImportMeta & { env?: Record<string, string | undefined> }).env?.VITE_TILE_BASE ??
  '/tiles';

// Override the theme's background color so the canvas reads as bone
// during tile load instead of the theme default. The named theme
// already includes a `background` layer.
const theme = { ...namedTheme('light'), background: PALETTE.bone };
const themeLayers = layers('protomaps', theme);

// Insert Wayne layers under place labels so labels stay readable on top.
// Symbol layers in the Protomaps theme are the labels; keep those last.
const labelLayers = themeLayers.filter((l) => l.type === 'symbol');
const baseLayers = themeLayers.filter((l) => l.type !== 'symbol');

export const baseStyle = {
  version: 8 as const,
  glyphs: BASEMAP_GLYPHS_URL,
  sources: {
    protomaps: {
      type: 'vector' as const,
      url: BASEMAP_TILES_URL,
      attribution: ATTRIBUTION
    },
    ...wayneSources({ tileBase: TILE_BASE })
  },
  layers: [...baseLayers, ...wayneLayers, ...labelLayers]
};
