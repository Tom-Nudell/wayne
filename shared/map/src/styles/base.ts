// MapLibre StyleSpecification for the Wayne base map.
//
// Sources Protomaps' public demo PMTiles for local dev. Real
// production setup (Phase 1) hosts our own copy of the Protomaps US
// build on R2; the only line that changes is BASEMAP_TILES_URL.
//
// The forked Protomaps light theme provides land, water, transit,
// boundaries, and places out of the box. Our energy-infrastructure
// layers stack on top via shared/map/src/layers/ in Phase 1.

import { layers, namedTheme } from 'protomaps-themes-base';

import { PALETTE } from '../palette.js';

// Phase 1 swap: replace with our R2-hosted PMTiles archive, e.g.
// `pmtiles://https://tiles.<our-domain>/basemap/protomaps-us-v<date>.pmtiles`.
const BASEMAP_TILES_URL = 'pmtiles://https://demo-bucket.protomaps.com/v4.pmtiles';

const BASEMAP_GLYPHS_URL =
  'https://protomaps.github.io/basemaps-assets/fonts/{fontstack}/{range}.pbf';

const ATTRIBUTION =
  '<a href="https://protomaps.com">Protomaps</a> © <a href="https://openstreetmap.org">OpenStreetMap</a>';

// Override the theme's background color so the canvas reads as bone
// during tile load instead of the theme default. The named theme
// already includes a `background` layer, so we don't add our own —
// duplicate layer ids fail style validation.
const theme = { ...namedTheme('light'), background: PALETTE.bone };

export const baseStyle = {
  version: 8 as const,
  glyphs: BASEMAP_GLYPHS_URL,
  sources: {
    protomaps: {
      type: 'vector' as const,
      url: BASEMAP_TILES_URL,
      attribution: ATTRIBUTION
    }
  },
  layers: layers('protomaps', theme)
};
