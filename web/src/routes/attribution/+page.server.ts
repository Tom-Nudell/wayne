/**
 * Attribution page data loader.
 *
 * Reads *.license.json sidecars from the tile bundle directory and returns
 * a structured list for the page to render. The bundle directory is:
 *
 *   1. $WAYNE_TILE_DIR env var (set in Vercel for production)
 *   2. static/tiles/ relative to the project root (local dev convention —
 *      `gridagent-data bundle --atlas-public platform/atlas/public` copies
 *      sidecars there; symlink or copy web/static/tiles → platform/atlas/public/tiles)
 *
 * If no sidecars are found the page renders an "attribution data not yet
 * generated" message rather than an empty table.
 */

import { readdir, readFile } from 'node:fs/promises';
import { join } from 'node:path';
import type { PageServerLoad } from './$types';

export interface LicenseEntry {
  spdx: string;
  name: string;
  url: string;
  citation: string;
  attribution_required: boolean;
  feature_count: number;
}

export interface LayerAttribution {
  layer: string;
  kind: string;
  feature_count: number;
  generated_at: string;
  licenses: LicenseEntry[];
}

function tileDir(): string {
  if (process.env.WAYNE_TILE_DIR) return process.env.WAYNE_TILE_DIR;
  // Resolve from the web package root (two levels up from src/routes/attribution)
  return join(new URL(import.meta.url).pathname, '../../../../static/tiles');
}

export const load: PageServerLoad = async () => {
  const layers: LayerAttribution[] = [];
  let dataAvailable = false;

  try {
    const dir = tileDir();
    const files = await readdir(dir);
    const sidecars = files.filter((f) => f.endsWith('.license.json'));

    if (sidecars.length > 0) {
      dataAvailable = true;
      for (const file of sidecars.sort()) {
        try {
          const raw = await readFile(join(dir, file), 'utf-8');
          const doc = JSON.parse(raw) as LayerAttribution;
          layers.push(doc);
        } catch {
          // Skip malformed sidecar; don't crash the page.
        }
      }
    }
  } catch {
    // Directory doesn't exist or isn't readable — show the placeholder.
  }

  // Sort: attribution-required layers first, then alphabetical.
  layers.sort((a, b) => {
    const aReq = a.licenses.some((l) => l.attribution_required);
    const bReq = b.licenses.some((l) => l.attribution_required);
    if (aReq !== bReq) return aReq ? -1 : 1;
    return a.layer.localeCompare(b.layer);
  });

  return { layers, dataAvailable };
};
