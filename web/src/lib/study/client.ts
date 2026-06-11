// Streaming client for POST /api/study (dev-flagged testability bridge).
//
// Reads the NDJSON response incrementally and invokes onEvent per line —
// the browser twin of the orchestrator CLI's --stream-events mode.

import type { StudyEvent, StudyRequest } from '@wayne/api';

export async function runStudy(
  body: StudyRequest,
  onEvent: (event: StudyEvent) => void,
  signal?: AbortSignal
): Promise<void> {
  const res = await fetch('/api/study', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
    signal
  });

  if (!res.ok || !res.body) {
    onEvent({ event: 'error', message: `study request failed: HTTP ${res.status}` });
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let nl: number;
    while ((nl = buffer.indexOf('\n')) >= 0) {
      const line = buffer.slice(0, nl).trim();
      buffer = buffer.slice(nl + 1);
      if (!line) continue;
      try {
        onEvent(JSON.parse(line) as StudyEvent);
      } catch {
        onEvent({ event: 'error', message: `unparseable study event: ${line}` });
      }
    }
  }
}
