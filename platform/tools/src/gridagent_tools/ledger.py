"""The study ledger: Wayne's system of record for grid analysis.

Implements the object-knowledge store from ``wayne-study-ledger-brief.md``
(v2). One **entry** per committed study — the entry ⇔ commit rule: completed
workflow runs and finished agent episodes that ran at least one study tool
commit; previews, drags, and retrieval-only episodes never do.

v1 substrate (deliberately replaceable; brief §10 keeps engines open):
``$GRIDAGENT_DATA_ROOT/ledger/entries.jsonl`` — append-only, one JSON entry
per line. O_APPEND keeps concurrent writers safe, and duckdb's
``read_json_auto`` makes the file SQL-queryable without a database server.
Entries are immutable once written; supersession and staleness are new
lines + flags, never edits (brief §6).

Entry shape (see brief §3):

    entry_id, committed_at
    subject:      {snapshot_id, subsystem: {kind, buses, branches}}
    question:     {intent, text}
    model_state:  {snapshot_id, snapshot_manifest_sha256, change_table}
    method:       {type: workflow|agent, name, spec_sha256, model,
                   tool_versions}
    results:      {studies: [{tool, arguments, signal}], summary}
    trace:        {episode_id, episode_log}
    status:       {stale, supersedes, superseded_by}
    governance:   {owner, tenant, visibility, licenses}   # reserved, brief §9

``model_id`` (content-hash identity, brief §2) is deliberately absent in
v1 — snapshots are the only model kind yet, identified by snapshot_id +
manifest hash. The field arrives with the model store facet.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .registry import register
from .result import ToolResult


def _ledger_root() -> Path:
    root = Path(os.environ.get("GRIDAGENT_DATA_ROOT", "data_root")) / "ledger"
    root.mkdir(parents=True, exist_ok=True)
    return root


def entries_path() -> Path:
    return _ledger_root() / "entries.jsonl"


_REQUIRED_KEYS = {"subject", "question", "model_state", "method", "results", "trace"}


def commit_entry(entry: dict[str, Any]) -> str:
    """Append one entry to the ledger. Returns the entry_id.

    Fills ``entry_id`` / ``committed_at`` / default ``status`` and
    ``governance`` blocks; refuses entries missing required parts rather
    than recording an unusable row.
    """
    missing = _REQUIRED_KEYS - set(entry)
    if missing:
        raise ValueError(f"ledger entry missing required parts: {sorted(missing)}")
    entry = dict(entry)
    entry.setdefault("entry_id", uuid.uuid4().hex[:16])
    entry.setdefault(
        "committed_at", datetime.now(tz=timezone.utc).isoformat(timespec="seconds")
    )
    entry.setdefault("status", {"stale": False, "supersedes": None, "superseded_by": None})
    entry.setdefault(
        "governance", {"owner": "", "tenant": "", "visibility": "private", "licenses": []}
    )
    line = json.dumps(entry, sort_keys=True, default=str)
    # O_APPEND: single-syscall line writes stay atomic across the concurrent
    # orchestrator subprocesses the web bridge spawns.
    fd = os.open(entries_path(), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        os.write(fd, (line + "\n").encode())
    finally:
        os.close(fd)
    return str(entry["entry_id"])


def load_entries() -> list[dict[str, Any]]:
    path = entries_path()
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def manifest_sha256(snapshot_root: Path) -> str | None:
    """Hash the snapshot's manifest — the v1 model-state fingerprint."""
    manifest = Path(snapshot_root) / "manifest.json"
    if not manifest.exists():
        return None
    return hashlib.sha256(manifest.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# Query — the object-knowledge retrieval surface (v1: filters + keywords;
# the embedding upgrade rides the same entry shape later).
# ---------------------------------------------------------------------------


def _intent_matches(wanted: str, actual: str) -> bool:
    """Forgiving intent match: models phrase intents loosely ("adding
    generation") while entries carry slugs ("injection_study"). Normalize
    and accept substring overlap either way."""
    w = wanted.lower().replace("-", "_").replace(" ", "_")
    a = actual.lower()
    return w == a or w in a or a in w


def _matches(entry: dict[str, Any], *, intent, bus_id, branch_id, snapshot_id, text) -> bool:
    if intent and not _intent_matches(str(intent), str(entry.get("question", {}).get("intent", ""))):
        return False
    if snapshot_id and entry.get("model_state", {}).get("snapshot_id") != snapshot_id:
        return False
    subsystem = entry.get("subject", {}).get("subsystem", {})
    if bus_id and str(bus_id) not in [str(b) for b in subsystem.get("buses") or []]:
        if subsystem.get("kind") != "system":
            return False
    if branch_id and str(branch_id) not in [str(b) for b in subsystem.get("branches") or []]:
        if subsystem.get("kind") != "system":
            return False
    if text:
        blob = json.dumps(entry, default=str).lower()
        if not all(tok in blob for tok in str(text).lower().split()):
            return False
    return True


def _summarize(entry: dict[str, Any]) -> dict[str, Any]:
    studies = entry.get("results", {}).get("studies", [])
    return {
        "entry_id": entry.get("entry_id"),
        "committed_at": entry.get("committed_at"),
        "intent": entry.get("question", {}).get("intent"),
        "question": entry.get("question", {}).get("text", "")[:160],
        "snapshot_id": entry.get("model_state", {}).get("snapshot_id"),
        "subsystem": entry.get("subject", {}).get("subsystem"),
        "method": {
            k: entry.get("method", {}).get(k) for k in ("type", "name", "model")
        },
        "signals": [{"tool": s.get("tool"), **(s.get("signal") or {})} for s in studies],
        "summary": (entry.get("results", {}).get("summary") or "")[:240],
        "stale": entry.get("status", {}).get("stale", False),
        "superseded_by": entry.get("status", {}).get("superseded_by"),
    }


@register(
    name="query_ledger",
    description=(
        "Search the study ledger (system of record): has a study like this "
        "been run before, and what did it conclude? Filter by intent, bus, "
        "branch, snapshot, or free-text keywords."
    ),
    schema={
        "type": "object",
        "properties": {
            "intent": {
                "type": "string",
                "description": (
                    "Study type slug: n1_contingency, dc_opf, injection_study, "
                    "production_cost, or power_flow. Treated as a soft filter — "
                    "if it eliminates everything, the other filters still apply."
                ),
            },
            "bus_id": {"type": "string"},
            "branch_id": {"type": "string"},
            "snapshot_id": {"type": "string"},
            "text": {"type": "string", "description": "Keywords matched anywhere in the entry."},
            "include_stale": {"type": "boolean", "default": False},
            "limit": {"type": "integer", "default": 10},
        },
        "additionalProperties": False,
    },
)
def query_ledger(
    intent: str | None = None,
    bus_id: str | None = None,
    branch_id: str | None = None,
    snapshot_id: str | None = None,
    text: str | None = None,
    include_stale: bool = False,
    limit: int = 10,
) -> ToolResult:
    entries = load_entries()

    def filtered(with_intent: str | None) -> list[dict[str, Any]]:
        return [
            e
            for e in entries
            if _matches(
                e, intent=with_intent, bus_id=bus_id, branch_id=branch_id,
                snapshot_id=snapshot_id, text=text,
            )
            and (include_stale or not e.get("status", {}).get("stale", False))
        ]

    hits = filtered(intent)
    intent_relaxed = False
    # Intent is a soft filter: a loosely-phrased intent should widen to the
    # subject/text matches, not hide them behind vocabulary mismatch.
    if not hits and intent and (bus_id or branch_id or snapshot_id or text):
        hits = filtered(None)
        intent_relaxed = bool(hits)

    hits.sort(key=lambda e: str(e.get("committed_at", "")), reverse=True)
    matches = [_summarize(e) for e in hits[: max(1, int(limit))]]
    return ToolResult(
        tool="query_ledger",
        value={
            "matches": matches,
            "n_total_entries": len(entries),
            "intent_relaxed": intent_relaxed,
        },
        signal={"n_matches": len(hits), "n_returned": len(matches)},
    )
