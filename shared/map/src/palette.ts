// Mycelium palette — calm earth tones for the base network; saturated alarm
// colors reserved for scenario overlays so they read against the quiet base.
//
// Forked from platform/atlas/src/theme.ts. When platform/atlas is consolidated
// onto this package, that file becomes a re-export of this one.

export const PALETTE = {
  bone: '#f3eee5',
  loam900: '#1c1812',
  loam500: '#9b8d77',
  moss: '#6f8a52',
  heartwood: '#8b5a2b',
  spore: '#c9b896',

  // Reserved alarm colors — only ever used for scenario overlays.
  overload: '#c0392b',
  mitigation: '#2e7d4f',
} as const;

export type PaletteKey = keyof typeof PALETTE;
