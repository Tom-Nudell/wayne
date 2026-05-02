// MapLibre StyleSpecification for the Wayne base map.
//
// Today: a mycelium-toned canvas — proves MapLibre is wired without a
// network dependency on tiles. Lets the map shell, controls, popovers,
// and overlay code all be developed against a real Map instance.
//
// Phase 1 swap (one place): add a 'protomaps' source pointing at our
// R2-hosted PMTiles archive (`pmtiles://${TILE_BASE}/basemap/...`) and
// the corresponding vector layers underneath the existing background.
// The forked Protomaps style.json moves in next to this file.

import { PALETTE } from '../palette.js';

export const baseStyle = {
  version: 8 as const,
  sources: {},
  layers: [
    {
      id: 'background',
      type: 'background' as const,
      paint: { 'background-color': PALETTE.bone }
    }
  ]
};
