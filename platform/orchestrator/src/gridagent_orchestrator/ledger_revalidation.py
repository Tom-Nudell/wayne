"""Staleness → lazy revalidation (study-ledger brief §6).

Every entry already pins its dependencies at commit time: the snapshot
manifest hash (model state), the workflow spec hash (method), and the tool
versions. This module compares those pins against the current world:

* ``refresh_staleness()`` — the cheap flag flip, no compute beyond hashing.
  Newly divergent entries get a stale status event (append-only overlay;
  the entry line never mutates). Run lazily wherever the ledger is about
  to be consulted — both episode paths call it at start.
* ``revalidate_entry()`` — the write path. Re-executes a stale workflow
  entry with its recorded inputs; the re-run commits a **new** entry
  through the normal entry ⇔ commit path, and the two get linked by
  ``supersedes`` / ``superseded_by`` status events. Whether the
  *conclusion* changed (not just digits) rides on the supersession event —
  the learning outcome signal of brief §7.

Only workflow-method entries re-run mechanically in v1: an agent episode's
method is the planner itself, so revalidating one means a fresh agent run —
that stays a deliberate human/agent action, not a ledger mechanism.
"""

from __future__ import annotations

import argparse
import json
from typing import Any, Callable

from gridagent_tools.ledger import (
    load_entries,
    manifest_sha256,
    mark_stale,
    mark_superseded,
)

from .ledger_commit import _bundle_root, _spec_sha256, _tool_versions

# v1 default for "digits vs conclusion" (threshold explicitly open in brief
# §6): numeric signal drift within 1% relative is solver noise, not a
# changed conclusion; any flag/status flip always is.
_REL_TOL = 0.01


def staleness_reasons(entry: dict[str, Any]) -> list[str]:
    """Compare an entry's pinned dependencies against the current world.

    Unpinned dependencies (None at commit time) can't be compared and never
    flag — absence of evidence is not divergence.
    """
    reasons: list[str] = []
    model_state = entry.get("model_state") or {}
    snapshot_id = model_state.get("snapshot_id")
    pinned_manifest = model_state.get("snapshot_manifest_sha256")
    if snapshot_id and pinned_manifest:
        current = manifest_sha256(_bundle_root() / str(snapshot_id))
        if current is None:
            reasons.append(f"snapshot {snapshot_id} no longer present")
        elif current != pinned_manifest:
            reasons.append(f"snapshot {snapshot_id} manifest changed")

    method = entry.get("method") or {}
    name = method.get("name")
    if method.get("type") == "workflow" and name and method.get("spec_sha256"):
        current = _spec_sha256(str(name))
        if current is None:
            reasons.append(f"workflow spec {name} no longer found")
        elif current != method["spec_sha256"]:
            reasons.append(f"workflow spec {name} changed")

    current_versions = _tool_versions()
    for pkg, pinned in (method.get("tool_versions") or {}).items():
        now = current_versions.get(pkg)
        if pinned and now and now != pinned:
            reasons.append(f"{pkg} {pinned} → {now}")
    return reasons


def refresh_staleness() -> dict[str, list[str]]:
    """Flag-flip pass: mark newly divergent entries stale.

    Already-stale and superseded entries are settled — re-marking them
    would only grow the event log. Returns {entry_id: reasons} for the
    newly flagged.
    """
    newly: dict[str, list[str]] = {}
    for entry in load_entries():
        status = entry.get("status") or {}
        if status.get("stale") or status.get("superseded_by"):
            continue
        reasons = staleness_reasons(entry)
        if reasons:
            entry_id = str(entry["entry_id"])
            mark_stale(entry_id, reasons)
            newly[entry_id] = reasons
    return newly


def conclusions_differ(
    old_studies: list[dict[str, Any]],
    new_studies: list[dict[str, Any]],
    rel_tol: float = _REL_TOL,
) -> bool:
    """v1 conclusion diff over study signals, paired by tool."""
    old_signals = {s.get("tool"): s.get("signal") or {} for s in old_studies}
    new_signals = {s.get("tool"): s.get("signal") or {} for s in new_studies}
    if set(old_signals) != set(new_signals):
        return True
    for tool, old in old_signals.items():
        new = new_signals[tool]
        for key in set(old) | set(new):
            a, b = old.get(key), new.get(key)
            if (
                isinstance(a, (int, float))
                and isinstance(b, (int, float))
                and not isinstance(a, bool)
                and not isinstance(b, bool)
            ):
                scale = max(abs(a), abs(b))
                if scale > 0 and abs(a - b) / scale > rel_tol:
                    return True
            elif a != b:
                return True
    return False


# (workflow_name, inputs) -> entry_id of the committed re-run, or None.
Runner = Callable[[str, dict[str, Any]], str | None]


def _default_runner(workflow_name: str, inputs: dict[str, Any]) -> str | None:
    from .run import run_workflow_episode

    captured: dict[str, str] = {}

    def on_event(record: dict[str, Any]) -> None:
        if record.get("event") == "ledger" and record.get("entry_id"):
            captured["entry_id"] = str(record["entry_id"])

    run_workflow_episode(workflow_name, inputs, on_event=on_event, emit=lambda _: None)
    return captured.get("entry_id")


def revalidate_entry(entry_id: str, *, runner: Runner | None = None) -> dict[str, Any]:
    """Re-execute one entry's study; link old ⇢ new; report the diff.

    The re-run commits through the normal entry ⇔ commit path, so the new
    entry pins today's dependencies. Raises rather than guessing when the
    entry is unknown, already superseded, or not mechanically re-runnable.
    """
    by_id = {str(e.get("entry_id")): e for e in load_entries()}
    old = by_id.get(str(entry_id))
    if old is None:
        raise ValueError(f"no ledger entry {entry_id!r}")
    superseded_by = (old.get("status") or {}).get("superseded_by")
    if superseded_by:
        raise ValueError(
            f"entry {entry_id} is already superseded by {superseded_by}; "
            "revalidate that entry instead"
        )
    method = old.get("method") or {}
    if method.get("type") != "workflow" or not method.get("name"):
        raise ValueError(
            f"entry {entry_id} has method type {method.get('type')!r}: only "
            "workflow entries re-run mechanically in v1"
        )
    if method.get("inputs") is None:
        # Entries committed without workflow_inputs (direct commit_episode
        # callers) have no re-run recipe. Re-running with workflow defaults
        # would silently study something else — refuse instead.
        raise ValueError(
            f"entry {entry_id} has no pinned method.inputs: not mechanically "
            "re-runnable; re-run the study deliberately and supersede by hand"
        )

    run = runner or _default_runner
    new_id = run(str(method["name"]), dict(method["inputs"]))
    if not new_id:
        raise RuntimeError(
            f"revalidation run for {entry_id} finished without committing an entry"
        )
    new = {str(e.get("entry_id")): e for e in load_entries()}.get(str(new_id))
    if new is None:
        raise RuntimeError(f"revalidation committed {new_id} but it is not readable")

    changed = conclusions_differ(
        (old.get("results") or {}).get("studies") or [],
        (new.get("results") or {}).get("studies") or [],
    )
    mark_superseded(str(entry_id), str(new_id), conclusion_changed=changed)
    return {
        "entry_id": str(new_id),
        "supersedes": str(entry_id),
        "conclusion_changed": changed,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="gridagent-ledger",
        description="Ledger maintenance: staleness refresh and revalidation.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("refresh", help="Flag entries whose dependencies changed.")
    reval = sub.add_parser(
        "revalidate", help="Re-run one stale entry; write the superseding entry."
    )
    reval.add_argument("entry_id")
    args = parser.parse_args()

    if args.command == "refresh":
        print(json.dumps({"newly_stale": refresh_staleness()}, indent=2))
    else:
        print(json.dumps(revalidate_entry(args.entry_id), indent=2))


if __name__ == "__main__":
    main()
