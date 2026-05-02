// MapLibre style.json, paint specs, layer registry, popovers.
//
// This package owns cartography. It is consumed by web/ (the commercial
// map) and platform/atlas/ (the internal agent dev viewer). Both render
// from the same paint specs so they cannot diverge visually.

export { PALETTE } from './palette.js';
export type { PaletteKey } from './palette.js';
export { baseStyle } from './styles/base.js';
