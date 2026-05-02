// /api/saved-views
//
// GET — list saved views for the current org (Free: cap at 3, Pro: unlimited)
// POST — create a saved view
//
// Phase 2 implementation:
//   GET:  SELECT * FROM saved_views WHERE org_id = ? ORDER BY created_at DESC
//   POST: INSERT INTO saved_views (..., view_state_json, dataset_version)
//         with tier-based row-count cap enforced server-side.

import { error, json } from '@sveltejs/kit';

import type { SavedView } from '@wayne/api';

import type { RequestHandler } from './$types';

export const GET: RequestHandler = async () => {
  // Phase 2: query Postgres scoped to event.locals.auth.org_id.
  const views: SavedView[] = [];
  return json(views);
};

export const POST: RequestHandler = async () => {
  return error(
    501,
    'saved-views POST not yet implemented (Phase 2: Postgres + tier cap)'
  );
};
