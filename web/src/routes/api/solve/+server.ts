// POST /api/solve — dev-flagged live what-if DC OPF (testability track).
//
// Powers the map's demand slider: {deltas: {bus_id: MW}} → fresh LMPs in
// ~10 ms via the tellegen CLI (network JSON on stdin, request as argv).
// The snapshot→network-JSON bridge runs once per server process (python,
// ~1s) and is cached; every solve after that is a single tellegen spawn.
//
// This is deliberately the same solve contract as @tellegen/engine in the
// browser — when that package publishes to npm (it 404s today), the
// client can swap fetch('/api/solve') for engine.solveJson() unchanged.
// Never a customer surface: 404 unless PUBLIC_WAYNE_AGENT=1.

import { spawn } from 'node:child_process';
import { existsSync, readdirSync } from 'node:fs';
import path from 'node:path';

import { error, json } from '@sveltejs/kit';
import { env } from '$env/dynamic/public';
import { env as privateEnv } from '$env/dynamic/private';

import type { RequestHandler } from './$types';

const MAX_DELTA_MW = 1000;
const MAX_EDITS = 8;

function repoRoot(): string {
  if (privateEnv.WAYNE_REPO_ROOT) return privateEnv.WAYNE_REPO_ROOT;
  const cwd = process.cwd();
  return path.basename(cwd) === 'web' ? path.dirname(cwd) : cwd;
}

function orchestratorPython(root: string): string {
  if (privateEnv.WAYNE_ORCHESTRATOR_PYTHON) return privateEnv.WAYNE_ORCHESTRATOR_PYTHON;
  return path.join(root, 'platform', 'orchestrator', '.venv', 'bin', 'python');
}

function tellegenBin(): string {
  if (privateEnv.GRIDAGENT_TELLEGEN_BIN) return privateEnv.GRIDAGENT_TELLEGEN_BIN;
  // Same resolution as the python backend: PATH, then the standard
  // `cargo install` location (dev-server process trees often lack it on PATH).
  const cargoBin = path.join(process.env.HOME ?? '', '.cargo', 'bin', 'tellegen');
  return existsSync(cargoBin) ? cargoBin : 'tellegen';
}

function newestSnapshot(root: string): string | null {
  const bundle = path.join(root, 'data_root', 'bundle');
  if (!existsSync(bundle)) return null;
  const candidates = readdirSync(bundle)
    .filter((n) => n.startsWith('snapshot_'))
    .filter((n) => existsSync(path.join(bundle, n, 'buses.parquet')))
    .sort()
    .reverse();
  const newest = candidates[0];
  return newest ? path.join(bundle, newest) : null;
}

interface CaseBundle {
  network: string;
  bus_ids: string[];
}

// One bridge run per server process; the snapshot is immutable on disk.
let casePromise: Promise<CaseBundle> | null = null;

function runOnce(cmd: string, args: string[], stdin?: string): Promise<string> {
  return new Promise((resolve, reject) => {
    const child = spawn(cmd, args, { stdio: ['pipe', 'pipe', 'pipe'] });
    let out = '';
    let err = '';
    child.stdout.on('data', (c: Buffer) => (out += c.toString('utf8')));
    child.stderr.on('data', (c: Buffer) => (err += c.toString('utf8')));
    child.on('error', reject);
    child.on('close', (code) => {
      if (code === 0) resolve(out);
      else reject(new Error(`${cmd} exited ${code}: ${err.slice(-500)}`));
    });
    if (stdin != null) child.stdin.write(stdin);
    child.stdin.end();
  });
}

function loadCase(root: string): Promise<CaseBundle> {
  if (casePromise) return casePromise;
  const python = orchestratorPython(root);
  const snapshot = newestSnapshot(root);
  if (!existsSync(python)) throw error(503, `orchestrator python not found at ${python}`);
  if (!snapshot) throw error(503, 'no snapshot bundle with buses.parquet found');
  const script = [
    'import json, sys',
    'from gridagent_tools.snapshot import Snapshot',
    'from gridagent_tools.backends.tellegen import snapshot_to_network_json',
    `snap = Snapshot.at(${JSON.stringify(snapshot)})`,
    "nj, maps, warnings = snapshot_to_network_json(snap, {'change_table': {}})",
    "print(json.dumps({'network': nj, 'bus_ids': maps['bus_ids']}))"
  ].join('\n');
  casePromise = runOnce(python, ['-c', script])
    .then((out) => JSON.parse(out) as CaseBundle)
    .catch((err_) => {
      casePromise = null; // allow retry after a transient failure
      throw err_;
    });
  return casePromise;
}

export const POST: RequestHandler = async ({ request }) => {
  if (env.PUBLIC_WAYNE_AGENT !== '1') {
    throw error(404, 'Not found');
  }

  let body: { deltas?: Record<string, unknown> };
  try {
    body = (await request.json()) as { deltas?: Record<string, unknown> };
  } catch {
    throw error(400, 'request body must be JSON');
  }

  const root = repoRoot();
  const caseBundle = await loadCase(root);

  // Validate + translate bus_id → MATPOWER bus number (bridge row order).
  const deltas: Record<string, number> = {};
  const entries = Object.entries(body.deltas ?? {});
  if (entries.length > MAX_EDITS) throw error(400, `at most ${MAX_EDITS} deltas`);
  for (const [busId, raw] of entries) {
    const mw = Number(raw);
    if (!Number.isFinite(mw)) throw error(400, `delta for ${busId} is not a number`);
    if (Math.abs(mw) > MAX_DELTA_MW) throw error(400, `|delta| capped at ${MAX_DELTA_MW} MW`);
    if (mw === 0) continue;
    const idx = caseBundle.bus_ids.indexOf(busId);
    if (idx < 0) throw error(422, `unknown bus_id ${busId}`);
    deltas[String(idx + 1)] = mw;
  }

  const solveRequest = JSON.stringify({ formulation: 'dcopf', edits: { deltas } });
  let stdout: string;
  try {
    stdout = await runOnce(tellegenBin(), [solveRequest], caseBundle.network);
  } catch (e) {
    throw error(503, `solve failed: ${e instanceof Error ? e.message : String(e)}`);
  }

  const resp = JSON.parse(stdout) as {
    status: string;
    objective?: number;
    lmp?: Array<{ bus: number; value: number }>;
    flows?: Array<{ branch: number; loading: number }>;
  };

  return json({
    status: resp.status,
    objective_usd_per_hour: resp.objective ?? null,
    lmp: (resp.lmp ?? []).map((b) => ({
      bus_id: caseBundle.bus_ids[b.bus - 1] ?? String(b.bus),
      lmp_usd_per_mwh: b.value
    })),
    n_binding: (resp.flows ?? []).filter((f) => f.loading >= 0.9999).length
  });
};
