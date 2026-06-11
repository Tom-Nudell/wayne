// Mycelium / forest-floor palette.
//
// The grid is rendered as a living branching network, not an engineering
// diagram. Hues stay in the brown / moss / lichen family; saturation is
// deliberately low. Voltage and fuel are encoded by *hue*, never by alarm
// red — alarm colors are reserved for scenario overlays (overloads,
// mitigations) so the eye can find them against the calm base map.
//
// Single source for both web/ (the commercial map) and platform/atlas/
// (the internal agent dev viewer). When platform/atlas is consolidated
// onto this package, theme.ts there becomes a re-export of this file.

export const PALETTE = {
  // Loam / bark base for chrome and panels
  loam900: '#1c1812',
  loam700: '#3b3228',
  loam500: '#6b5d4a',
  bone: '#f3ede0',
  paper: '#faf6ec',

  // Mycelium textures — used by basemap & overlays
  moss: '#6f8a52',
  heartwood: '#8b5a2b',
  spore: '#c9b896',

  // Hyphae — voltage-graded, all in the warm-cool earth band
  hypha115: '#7a8d6a', // moss
  hypha230: '#9ab27a', // young leaf
  hypha345: '#c8a86a', // ochre
  hypha500: '#a8703f', // rust bark
  hypha765: '#6b3a26', // heartwood

  // Fruiting bodies — fuel families, gentle but distinguishable
  fuelSolar: '#d8b25b',
  fuelWind: '#8aa9a3',
  fuelGas: '#b97a4d',
  fuelCoal: '#2b2620',
  fuelNuclear: '#9a8fb5',
  fuelHydro: '#5b7a93',
  fuelOther: '#8a7d68',

  // Reserved for scenario overlays — the only saturated colors on the map
  overload: '#c0392b',
  mitigation: '#3aa17a'
} as const;

export type PaletteKey = keyof typeof PALETTE;
