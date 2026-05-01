/**
 * DuckDB-WASM data layer for the atlas.
 *
 * The data bundle (``bundle.duckdb``) is loaded via HTTP range requests
 * — DuckDB-WASM reads only the pages it needs, so a 100 MB bundle
 * doesn't cost the user 100 MB of download just to browse the map.
 *
 * We keep this module intentionally thin: one lazy DB handle, one
 * ``query`` helper, and one domain-shaped helper per table the UI
 * actually binds to. New panels add a helper here rather than open a
 * separate connection.
 */
import * as duckdb from "@duckdb/duckdb-wasm";

const BUNDLE_URL =
  (import.meta.env.VITE_BUNDLE_URL as string | undefined) ?? "/bundle.duckdb";

let dbPromise: Promise<duckdb.AsyncDuckDB> | null = null;

/**
 * Lazily boot DuckDB-WASM and attach the bundle as read-only.
 *
 * We pick the ``mvp`` bundle deliberately: the ``eh`` bundle needs
 * cross-origin isolation headers we don't want to require of the
 * static host. If a deployment has those headers it can bump the
 * bundle selection here without touching callers.
 */
async function getDb(): Promise<duckdb.AsyncDuckDB> {
  if (dbPromise) return dbPromise;
  dbPromise = (async () => {
    const bundles = duckdb.getJsDelivrBundles();
    const bundle = await duckdb.selectBundle(bundles);
    const workerUrl = URL.createObjectURL(
      new Blob([`importScripts("${bundle.mainWorker!}");`], {
        type: "text/javascript",
      }),
    );
    const worker = new Worker(workerUrl);
    const logger = new duckdb.ConsoleLogger(duckdb.LogLevel.WARNING);
    const db = new duckdb.AsyncDuckDB(logger, worker);
    await db.instantiate(bundle.mainModule, bundle.pthreadWorker);
    URL.revokeObjectURL(workerUrl);
    // ATTACH via HTTP so DuckDB-WASM uses range requests on the bundle.
    const conn = await db.connect();
    try {
      await conn.query(`ATTACH '${BUNDLE_URL}' AS bundle (READ_ONLY)`);
      await conn.query(`USE bundle`);
    } finally {
      await conn.close();
    }
    return db;
  })();
  return dbPromise;
}

/** Run a SQL query against the attached bundle and return typed rows. */
export async function query<T = Record<string, unknown>>(sql: string): Promise<T[]> {
  const db = await getDb();
  const conn = await db.connect();
  try {
    const result = await conn.query(sql);
    return result.toArray().map((row) => row.toJSON() as T);
  } finally {
    await conn.close();
  }
}

// ---------------------------------------------------------------------------
// Domain helpers. One per table the UI actually binds to.
// ---------------------------------------------------------------------------

export interface HourlyLmp {
  ts: string;
  node: string;
  lmp: number;
  lat: number | null;
  lon: number | null;
}

/**
 * Hourly LMPs for a given ISO and [start, end) window, joined to node
 * lat/lon via the ``buses`` table. Returns an empty array when the
 * market mart is stubbed — the heatmap layer tolerates that and just
 * renders nothing, which is the right behaviour before GridStatus has
 * been ingested.
 */
export async function fetchLmpWindow(
  iso: string,
  startIso: string,
  endIso: string,
): Promise<HourlyLmp[]> {
  return query<HourlyLmp>(`
    SELECT
      lmp.ts::VARCHAR AS ts,
      lmp.node AS node,
      lmp.lmp AS lmp,
      bus.lat AS lat,
      bus.lon AS lon
    FROM lmp_hourly lmp
    LEFT JOIN buses bus ON bus.bus_id = lmp.node
    WHERE lmp.iso = '${iso.replace(/'/g, "''")}'
      AND lmp.ts >= TIMESTAMP '${startIso}'
      AND lmp.ts <  TIMESTAMP '${endIso}'
  `);
}

/** Interconnection queue snapshot — pinned to the latest ingest. */
export async function fetchQueueSnapshot(iso?: string): Promise<Record<string, unknown>[]> {
  const where = iso ? `WHERE iso = '${iso.replace(/'/g, "''")}'` : "";
  return query(`SELECT * FROM queue_snapshot ${where}`);
}
