"""Ledger core tests: commit, immutable append, query semantics."""

from __future__ import annotations

import json

import pytest

from gridagent_tools import ledger


@pytest.fixture(autouse=True)
def isolated_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("GRIDAGENT_DATA_ROOT", str(tmp_path))
    return tmp_path


def _entry(**overrides):
    base = {
        "subject": {"subsystem": {"kind": "elements", "buses": ["309"], "branches": []}},
        "question": {"intent": "injection_study", "text": "250 MW at bus 309"},
        "model_state": {"snapshot_id": "snap_a", "snapshot_manifest_sha256": "x", "change_table": {}},
        "method": {"type": "workflow", "name": "injection_study"},
        "results": {"studies": [{"tool": "run_injection_study", "signal": {"feasible": True}}], "summary": "ok"},
        "trace": {"episode_id": "e1", "episode_log": "/tmp/e1.jsonl"},
    }
    base.update(overrides)
    return base


def test_commit_fills_defaults_and_appends(isolated_ledger):
    entry_id = ledger.commit_entry(_entry())
    lines = ledger.entries_path().read_text().splitlines()
    assert len(lines) == 1
    stored = json.loads(lines[0])
    assert stored["entry_id"] == entry_id
    assert stored["status"] == {"stale": False, "supersedes": None, "superseded_by": None}
    assert stored["governance"]["visibility"] == "private"

    ledger.commit_entry(_entry())
    assert len(ledger.entries_path().read_text().splitlines()) == 2  # append-only


def test_commit_rejects_incomplete_entries(isolated_ledger):
    with pytest.raises(ValueError, match="missing required parts"):
        ledger.commit_entry({"subject": {}, "question": {}})


def test_query_by_bus_and_intent(isolated_ledger):
    ledger.commit_entry(_entry())
    ledger.commit_entry(
        _entry(
            subject={"subsystem": {"kind": "system", "buses": [], "branches": []}},
            question={"intent": "dc_opf", "text": "price surface"},
        )
    )

    out = ledger.query_ledger(bus_id="309")
    # System-wide studies match any element; the bus-scoped entry matches too.
    assert out.signal["n_matches"] == 2

    out = ledger.query_ledger(intent="injection_study", bus_id="309")
    assert out.signal["n_matches"] == 1
    assert out.value["matches"][0]["intent"] == "injection_study"


def test_intent_is_a_soft_filter(isolated_ledger):
    ledger.commit_entry(_entry())
    # Loose model phrasing must not hide subject matches (the live failure
    # this guards: gemma passed intent="adding generation").
    out = ledger.query_ledger(intent="adding generation", bus_id="309")
    assert out.signal["n_matches"] == 1
    assert out.value["intent_relaxed"] is True
    # Substring phrasing matches without relaxation.
    out = ledger.query_ledger(intent="injection", bus_id="309")
    assert out.value["intent_relaxed"] is False
    assert out.signal["n_matches"] == 1


def test_stale_entries_hidden_by_default(isolated_ledger):
    stale = _entry()
    stale["status"] = {"stale": True, "supersedes": None, "superseded_by": "e2"}
    ledger.commit_entry(stale)
    assert ledger.query_ledger(bus_id="309").signal["n_matches"] == 0
    assert ledger.query_ledger(bus_id="309", include_stale=True).signal["n_matches"] == 1


def test_query_ledger_registered_as_tool():
    from gridagent_tools import TOOL_REGISTRY

    assert "query_ledger" in TOOL_REGISTRY
