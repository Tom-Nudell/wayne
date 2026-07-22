"""Staleness detection + the lazy revalidation write path (brief §6)."""

from __future__ import annotations

import json

import pytest
from gridagent_tools import ledger

from gridagent_orchestrator.ledger_commit import _spec_sha256, _tool_versions
from gridagent_orchestrator.ledger_revalidation import (
    conclusions_differ,
    refresh_staleness,
    revalidate_entry,
    staleness_reasons,
)


@pytest.fixture(autouse=True)
def isolated_data_root(tmp_path, monkeypatch):
    monkeypatch.setenv("GRIDAGENT_DATA_ROOT", str(tmp_path))
    return tmp_path


@pytest.fixture()
def snapshot(isolated_data_root):
    root = isolated_data_root / "bundle" / "snapshot_x"
    root.mkdir(parents=True)
    (root / "manifest.json").write_text(json.dumps({"tables": ["buses"]}))
    return root


def _entry(snapshot_root, **overrides):
    """An entry whose pinned dependencies all match the current world."""
    base = {
        "subject": {"subsystem": {"kind": "elements", "buses": ["309"], "branches": []}},
        "question": {"intent": "injection_study", "text": "250 MW at bus 309"},
        "model_state": {
            "snapshot_id": snapshot_root.name,
            "snapshot_manifest_sha256": ledger.manifest_sha256(snapshot_root),
            "change_table": {"add_injection": {"309": 250.0}},
        },
        "method": {
            "type": "workflow",
            "name": "injection_study",
            "spec_sha256": _spec_sha256("injection_study"),
            "inputs": {"bus_id": "309", "p_mw": 250.0},
            "model": None,
            "tool_versions": _tool_versions(),
        },
        "results": {
            "studies": [
                {"tool": "run_injection_study", "arguments": {},
                 "signal": {"feasible": True, "n_new_overloads": 3}}
            ],
            "summary": "ok",
        },
        "trace": {"episode_id": "e1", "episode_log": "/tmp/e1.jsonl"},
    }
    base.update(overrides)
    return base


def test_fresh_entry_has_no_staleness_reasons(snapshot):
    assert staleness_reasons(_entry(snapshot)) == []
    ledger.commit_entry(_entry(snapshot))
    assert refresh_staleness() == {}


def test_manifest_change_flags_stale(snapshot):
    entry_id = ledger.commit_entry(_entry(snapshot))
    (snapshot / "manifest.json").write_text(json.dumps({"tables": ["buses", "lines"]}))

    newly = refresh_staleness()
    assert newly == {entry_id: ["snapshot snapshot_x manifest changed"]}
    (loaded,) = ledger.load_entries()
    assert loaded["status"]["stale"] is True
    # Second pass is a no-op: settled entries don't re-flag.
    assert refresh_staleness() == {}


def test_spec_and_tool_version_changes_flag_stale(snapshot):
    entry = _entry(snapshot)
    entry["method"]["spec_sha256"] = "0" * 64
    entry["method"]["tool_versions"] = {
        **entry["method"]["tool_versions"],
        "gridagent-tools": "0.0.0-old",
    }
    reasons = staleness_reasons(entry)
    assert "workflow spec injection_study changed" in reasons
    assert any(r.startswith("gridagent-tools 0.0.0-old → ") for r in reasons)


def test_unpinned_dependencies_never_flag(snapshot):
    entry = _entry(snapshot)
    entry["model_state"]["snapshot_manifest_sha256"] = None
    entry["method"]["spec_sha256"] = None
    entry["method"]["tool_versions"] = {"powerio": None}
    assert staleness_reasons(entry) == []


def test_revalidate_writes_superseding_entry(snapshot):
    old_id = ledger.commit_entry(_entry(snapshot))

    def runner(workflow_name, inputs):
        assert workflow_name == "injection_study"
        assert inputs == {"bus_id": "309", "p_mw": 250.0}
        return ledger.commit_entry(_entry(snapshot))

    result = revalidate_entry(old_id, runner=runner)
    assert result["supersedes"] == old_id
    assert result["conclusion_changed"] is False

    by_id = {e["entry_id"]: e for e in ledger.load_entries()}
    assert by_id[old_id]["status"]["superseded_by"] == result["entry_id"]
    assert by_id[result["entry_id"]]["status"]["supersedes"] == old_id

    # A superseded entry refuses a second revalidation.
    with pytest.raises(ValueError, match="already superseded"):
        revalidate_entry(old_id, runner=runner)


def test_revalidate_reports_changed_conclusion(snapshot):
    old_id = ledger.commit_entry(_entry(snapshot))
    flipped = _entry(snapshot)
    flipped["results"]["studies"][0]["signal"] = {"feasible": False, "n_new_overloads": 9}

    result = revalidate_entry(old_id, runner=lambda *_: ledger.commit_entry(flipped))
    assert result["conclusion_changed"] is True
    by_id = {e["entry_id"]: e for e in ledger.load_entries()}
    assert by_id[old_id]["status"]["conclusion_changed"] is True


def test_revalidate_refuses_agent_entries(snapshot):
    entry = _entry(snapshot)
    entry["method"] = {"type": "agent", "name": None, "model": "gemma4:e12b"}
    entry_id = ledger.commit_entry(entry)
    with pytest.raises(ValueError, match="only workflow entries"):
        revalidate_entry(entry_id)


def test_conclusions_differ_tolerates_solver_noise():
    old = [{"tool": "run_dc_opf", "signal": {"objective": 100.0, "converged": True}}]
    within = [{"tool": "run_dc_opf", "signal": {"objective": 100.5, "converged": True}}]
    beyond = [{"tool": "run_dc_opf", "signal": {"objective": 105.0, "converged": True}}]
    flag = [{"tool": "run_dc_opf", "signal": {"objective": 100.0, "converged": False}}]
    assert conclusions_differ(old, within) is False
    assert conclusions_differ(old, beyond) is True
    assert conclusions_differ(old, flag) is True


def test_revalidate_refuses_entry_without_pinned_inputs(snapshot):
    # Direct commit_episode callers can produce workflow entries with
    # method.inputs=None — re-running those with workflow defaults would
    # silently study something else (trn audit finding).
    entry = _entry(snapshot)
    entry["method"]["inputs"] = None
    entry_id = ledger.commit_entry(entry)
    with pytest.raises(ValueError, match="no pinned method.inputs"):
        revalidate_entry(entry_id, runner=lambda name, inputs: "should_not_run")
