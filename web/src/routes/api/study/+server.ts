// POST /api/study — dev-flagged bridge to the Wayne orchestrator.
//
// Testability track (brief §16): spawns `gridagent_orchestrator.run
// --stream-events`, relays each episode event to the browser as one NDJSON
// line, and rewrites the final overlay location to a URL under /overlays/.
// NDJSON over a streamed POST body (not EventSource/SSE) because EventSource
// cannot POST and the fetch-reader on the client is fewer moving parts.
//
// Never a customer surface: 404 unless PUBLIC_WAYNE_AGENT=1, and nothing in
// the customer bundle references this route. Productizing this contract
// (auth, tiers, queueing, rate limits) is Phase 4's agent seam.

import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import path from 'node:path';

import { error } from '@sveltejs/kit';
import { env } from '$env/dynamic/public';
import { env as privateEnv } from '$env/dynamic/private';

import type { StudyEvent, StudyRequest } from '@wayne/api';

import type { RequestHandler } from './$types';

// Repo root: the dev server runs with cwd=web/. Allow an explicit override
// for non-standard layouts.
function repoRoot(): string {
  if (privateEnv.WAYNE_REPO_ROOT) return privateEnv.WAYNE_REPO_ROOT;
  const cwd = process.cwd();
  return path.basename(cwd) === 'web' ? path.dirname(cwd) : cwd;
}

function orchestratorPython(root: string): string {
  if (privateEnv.WAYNE_ORCHESTRATOR_PYTHON) return privateEnv.WAYNE_ORCHESTRATOR_PYTHON;
  return path.join(root, 'platform', 'orchestrator', '.venv', 'bin', 'python');
}

// CLI arguments for the run. The canonical map-click N-1 runs the learned
// n1_contingency workflow — fixed steps, zero planner round-trips (see
// wayne-workflows-brief.md §4). Free-form goals still take the agent path.
function studyArgs(body: StudyRequest, overlayDir: string): string[] | null {
  const common = ['-m', 'gridagent_orchestrator.run', '--stream-events'];
  // The body is an unvalidated cast — coerce defensively so a malformed
  // request can't 500 the route or persist junk into scenario names.
  if (typeof body.goal === 'string' && body.goal.trim()) {
    return [...common, '--goal', body.goal.trim(), '--atlas-overlay-dir', overlayDir];
  }
  const f = body.fromFeature;
  if (!f || typeof f !== 'object' || typeof f.feature_id !== 'string') return null;
  const name = typeof f.name === 'string' ? f.name : '';
  const kind = typeof f.kind === 'string' ? f.kind : 'feature';
  const label = name ? `${name} (${f.feature_id})` : f.feature_id;
  const inputs = { scenario_name: `N-1 near ${kind} ${label}` };
  return [
    ...common,
    '--workflow',
    'n1_contingency',
    '--inputs',
    JSON.stringify(inputs),
    '--atlas-overlay-dir',
    overlayDir
  ];
}

export const POST: RequestHandler = async ({ request }) => {
  if (env.PUBLIC_WAYNE_AGENT !== '1') {
    throw error(404, 'Not found');
  }

  let body: StudyRequest;
  try {
    body = (await request.json()) as StudyRequest;
  } catch {
    throw error(400, 'request body must be JSON');
  }

  const root = repoRoot();
  const python = orchestratorPython(root);
  if (!existsSync(python)) {
    throw error(503, `orchestrator python not found at ${python} — create the venv first`);
  }

  // Overlays land in web/static so the dev server serves them at /overlays/.
  const overlayDir = path.join(root, 'web', 'static', 'overlays');

  const args = studyArgs(body, overlayDir);
  if (!args) {
    throw error(400, 'goal or fromFeature required');
  }

  const child = spawn(
    python,
    args,
    {
      cwd: root,
      env: {
        ...process.env,
        GRIDAGENT_DATA_ROOT: privateEnv.GRIDAGENT_DATA_ROOT ?? path.join(root, 'data_root'),
        GRIDAGENT_SCENARIO_ROOT:
          privateEnv.GRIDAGENT_SCENARIO_ROOT ?? path.join(root, 'data_root', 'scenarios'),
        GRIDAGENT_EPISODE_ROOT:
          privateEnv.GRIDAGENT_EPISODE_ROOT ?? path.join(root, 'data_root', 'episodes')
      },
      stdio: ['ignore', 'pipe', 'pipe']
    }
  );

  const encoder = new TextEncoder();

  // Once the client disconnects (cancel) or the stream closes, the child's
  // remaining 'data'/'close' events must not touch the controller — an
  // enqueue on a closed controller throws an uncaught ERR_INVALID_STATE
  // that takes the whole server process down.
  let closed = false;

  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      let buffer = '';
      let stderrTail = '';

      const send = (event: StudyEvent) => {
        if (closed) return;
        try {
          controller.enqueue(encoder.encode(JSON.stringify(event) + '\n'));
        } catch {
          closed = true;
        }
      };

      child.stdout.on('data', (chunk: Buffer) => {
        buffer += chunk.toString('utf8');
        let nl: number;
        while ((nl = buffer.indexOf('\n')) >= 0) {
          const line = buffer.slice(0, nl).trim();
          buffer = buffer.slice(nl + 1);
          if (!line) continue;
          try {
            const record = JSON.parse(line) as Record<string, unknown>;
            if (record.event === 'overlay') {
              // Rewrite the on-disk overlay dir to the URL the static
              // server exposes it at.
              const episodeId = String(record.episode_id ?? '');
              send({
                event: 'overlay',
                episode_id: episodeId,
                feature_count: Number(record.feature_count ?? 0),
                overlay_url: `/overlays/${episodeId}/n1_contingency.geojson`
              });
            } else {
              send(record as unknown as StudyEvent);
            }
          } catch {
            // Non-JSON noise on stdout (should not happen in
            // --stream-events mode); surface rather than hide.
            send({ event: 'error', message: `unparseable orchestrator output: ${line}` });
          }
        }
      });

      child.stderr.on('data', (chunk: Buffer) => {
        // Keep the last few KB for the error report; stderr carries the
        // human side notes in --stream-events mode.
        stderrTail = (stderrTail + chunk.toString('utf8')).slice(-4096);
      });

      const finish = () => {
        if (closed) return;
        closed = true;
        try {
          controller.close();
        } catch {
          // Already closed by cancel(); nothing to do.
        }
      };

      child.on('close', (code, signal) => {
        if (code !== 0) {
          send({
            event: 'error',
            message: `orchestrator exited with ${code === null ? `signal ${signal}` : `code ${code}`}: ${stderrTail.trim()}`
          });
        }
        finish();
      });

      child.on('error', (err) => {
        send({ event: 'error', message: `failed to spawn orchestrator: ${err.message}` });
        finish();
      });
    },
    cancel() {
      closed = true;
      child.kill('SIGTERM');
    }
  });

  return new Response(stream, {
    headers: {
      'content-type': 'application/x-ndjson; charset=utf-8',
      'cache-control': 'no-store',
      // Disable proxy buffering so events reach the browser as they happen.
      'x-accel-buffering': 'no'
    }
  });
};
