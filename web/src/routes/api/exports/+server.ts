// POST /api/exports
//
// Enqueues a PNG or CSV export job; returns the ExportJob with an id the
// client polls until status === 'done'.
//
// Phase 2 implementation:
//   - PNG: render via headless browser (Browserless or Playwright on a
//     longer-timeout Vercel function); watermark with attribution
//     stamps generated from license.json sidecars
//   - CSV: of filtered features only; stamp each row with source,
//     source_version, license_id; cap row count per tier
//   - Rate limit via Upstash Redis (Pro: 100/day)

import { error } from '@sveltejs/kit';

import type { RequestHandler } from './$types';

export const POST: RequestHandler = async () => {
  return error(501, 'exports endpoint not yet implemented (Phase 2: PNG/CSV worker + rate limit)');
};
