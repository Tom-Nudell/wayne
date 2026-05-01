// Brand constants. Codename + display strings used across web/ and any
// generated assets (PNG export watermarks, /attribution page, OG images).
//
// Codename is TBD per the engineering brief; do not commit a placeholder
// that ends up in user-visible copy. When the codename lands, update this
// file and grep for old references.

export const BRAND = {
  // Internal repo + platform name. Public product gets its own codename
  // when the trademark search clears.
  internal: 'Wayne',
  productName: null as string | null,
  productTagline: null as string | null,
  domain: null as string | null,
} as const;
