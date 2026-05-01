// Design tokens. Single source for spacing, radius, type scale, motion.
// Components in web/ should not hard-code these values — import from here.

export const SPACING = {
  xs: '0.25rem',
  sm: '0.5rem',
  md: '1rem',
  lg: '1.5rem',
  xl: '2.5rem',
  xxl: '4rem',
} as const;

export const RADIUS = {
  sm: '4px',
  md: '8px',
  lg: '14px',
  pill: '999px',
} as const;

export const TYPE_SCALE = {
  body: '0.95rem',
  bodySmall: '0.85rem',
  h1: '2.25rem',
  h2: '1.65rem',
  h3: '1.25rem',
  caption: '0.75rem',
} as const;

export const MOTION = {
  fast: '120ms',
  base: '220ms',
  slow: '420ms',
  ease: 'cubic-bezier(0.2, 0, 0, 1)',
} as const;
