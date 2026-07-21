"""Entry ⇔ commit: build a ledger entry from a finished episode.

Implements brief §3's mechanical rule on the orchestrator side. An episode
commits exactly when it ran at least one study tool (``run_*``); episodes
that only queried data or the ledger are retrieval, not studies, and write
nothing. Sub-steps stay inside the entry as its trace reference — the
episode JSONL remains the step-level record.
"""

from __future__ import annotations

import hashlib
import json
import os
from importlib import metadata
from pathlib import Path
from typing import Any

from gridagent_tools.ledger import commit_entry, manifest_sha256

from .workflow import workflow_dirs

_STUDY_PREFIX = "run_"


def _bundle_root() -> Path:
    return Path(os.environ.get("GRIDAGENT_DATA_ROOT", "data_root")) / "bundle"


def _newest_snapshot_id(bundle_root: Path) -> str | None:
    candidates = sorted(
        (
            p.name
            for p in bundle_root.iterdir()
            if p.is_dir() and p.name.startswith("snapshot_") and (p / "buses.parquet").exists()
        ),
        reverse=True,
    ) if bundle_root.is_dir() else []
    return candidates[0] if candidates else None


def _spec_sha256(workflow_name: str) -> str | None:
    for d in workflow_dirs():
        path = d / f"{workflow_name}.yaml"
        if path.exists():
            return hashlib.sha256(path.read_bytes()).hexdigest()
    return None


def _tool_versions() -> dict[str, str | None]:
    versions: dict[str, str | None] = {}
    for pkg in ("gridagent-tools", "gridagent-orchestrator", "pandapower", "powerio"):
        try:
            versions[pkg] = metadata.version(pkg)
        except metadata.PackageNotFoundError:
            versions[pkg] = None
    return versions


def _subsystem(study_steps: list[dict[str, Any]]) -> dict[str, Any]:
    """Coarse v1 element scope: unions of touched buses/branches; a study
    with no locational argument is system-wide."""
    buses: set[str] = set()
    branches: set[str] = set()
    system_wide = False
    for step in study_steps:
        args = step.get("arguments") or {}
        if step.get("tool") == "run_injection_study":
            buses.add(str(args.get("bus_id")))
        elif step.get("tool") == "run_n1_contingency" and args.get("monitored"):
            branches.update(str(b) for b in args["monitored"])
        else:
            system_wide = True
        change = (args.get("change_table") or {}) if isinstance(args.get("change_table"), dict) else {}
        buses.update(str(b) for b in (change.get("add_injection") or {}))
    return {
        "kind": "system" if system_wide else "elements",
        "buses": sorted(b for b in buses if b and b != "None"),
        "branches": sorted(branches),
    }


def _model_state(records: list[dict[str, Any]], study_steps: list[dict[str, Any]]) -> dict[str, Any]:
    snapshot_id: str | None = None
    change_table: dict[str, Any] = {}
    for rec in records:
        if rec.get("event") != "step":
            continue
        if rec.get("tool") == "create_scenario":
            value = rec.get("value") or {}
            snapshot_id = value.get("snapshot_id") or snapshot_id
            if isinstance(value.get("change_table"), dict):
                change_table = value["change_table"]
        if rec.get("tool") == "list_data_snapshots" and snapshot_id is None:
            snaps = (rec.get("value") or {}).get("snapshots") or []
            if snaps:
                snapshot_id = snaps[0].get("id")
    # Injection studies without a scenario perturb the baseline directly —
    # their delta is the effective change table.
    for step in study_steps:
        if step.get("tool") == "run_injection_study":
            args = step.get("arguments") or {}
            if not args.get("scenario_id") and args.get("bus_id") is not None:
                injections = dict(change_table.get("add_injection") or {})
                injections[str(args["bus_id"])] = args.get("p_mw")
                change_table = {**change_table, "add_injection": injections}
    bundle = _bundle_root()
    if snapshot_id is None:
        snapshot_id = _newest_snapshot_id(bundle)
    sha = manifest_sha256(bundle / snapshot_id) if snapshot_id else None
    return {
        "snapshot_id": snapshot_id,
        "snapshot_manifest_sha256": sha,
        "change_table": change_table,
    }


def entry_from_episode(
    episode_log: Path,
    *,
    workflow_name: str | None = None,
    workflow_inputs: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Build a ledger entry from an episode log, or None if nothing commits.

    ``workflow_name`` marks the fixed-workflow path; free-form agent runs
    pass None and are recorded as method type "agent". ``workflow_inputs``
    (the resolved inputs) are pinned on the method so the entry can be
    re-executed verbatim — the revalidation write path needs them.
    """
    records = [json.loads(line) for line in episode_log.read_text().splitlines() if line.strip()]
    start = next((r for r in records if r.get("event") == "start"), None)
    if start is None:
        return None
    steps = [r for r in records if r.get("event") == "step"]
    # Last ADVANCEd attempt per study tool: retried steps shouldn't commit twice.
    study_steps: dict[str, dict[str, Any]] = {}
    for rec in steps:
        tool = str(rec.get("tool", ""))
        if tool.startswith(_STUDY_PREFIX) and rec.get("decision") == "advance":
            study_steps[tool] = rec
    if not study_steps:
        return None  # retrieval-only episode: cites the record, never enters it

    finish = next((r for r in reversed(records) if r.get("event") == "finish"), None)
    ordered = sorted(study_steps.values(), key=lambda r: r.get("step", 0))
    intent = workflow_name or str(ordered[-1].get("tool", "")).removeprefix(_STUDY_PREFIX)

    method: dict[str, Any] = {
        "type": "workflow" if workflow_name else "agent",
        "name": workflow_name,
        "spec_sha256": _spec_sha256(workflow_name) if workflow_name else None,
        "inputs": dict(workflow_inputs) if workflow_name and workflow_inputs else None,
        "model": None if workflow_name else os.environ.get("GRIDAGENT_LLM_MODEL", "gemma4:e12b"),
        "tool_versions": _tool_versions(),
    }

    return {
        "subject": {"subsystem": _subsystem(ordered)},
        "question": {"intent": intent, "text": str(start.get("goal", ""))},
        "model_state": _model_state(records, ordered),
        "method": method,
        "results": {
            "studies": [
                {
                    "tool": s.get("tool"),
                    "arguments": s.get("arguments"),
                    "signal": s.get("signal"),
                }
                for s in ordered
            ],
            "summary": str((finish or {}).get("summary", "")),
        },
        "trace": {
            "episode_id": start.get("episode_id"),
            "episode_log": str(episode_log),
        },
    }


def commit_episode(
    episode_log: Path,
    *,
    workflow_name: str | None = None,
    workflow_inputs: dict[str, Any] | None = None,
) -> str | None:
    """Entry ⇔ commit for one episode. Returns entry_id, or None."""
    entry = entry_from_episode(
        episode_log, workflow_name=workflow_name, workflow_inputs=workflow_inputs
    )
    if entry is None:
        return None
    return commit_entry(entry)
