// GET /api/manifest
//
// Returns the current dataset manifest the frontend uses to know which
// layers exist and where their tiles + license sidecars live.
//
// Phase 1: fetch from R2 /manifest/latest.json (cached at the edge).
// Until then, an empty manifest keeps the wiring honest — the route
// type-checks against @wayne/api and the frontend can render with zero
// layers without the call failing.

import { json } from '@sveltejs/kit';

import type { ManifestResponse } from '@wayne/api';

import type { RequestHandler } from './$types';

export const GET: RequestHandler = async () => {
  const response: ManifestResponse = {
    manifest: {
      version: 'stub-0',
      generated_at: new Date().toISOString(),
      layers: []
    }
  };

  return json(response, {
    headers: {
      // Manifest is small and changes only on data refresh; let the CDN
      // hold it for a minute. Will tighten with versioned URLs in Phase 1.
      'cache-control': 'public, max-age=60, s-maxage=60'
    }
  });
};
