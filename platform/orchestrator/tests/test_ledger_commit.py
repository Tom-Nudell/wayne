"""Entry ⇔ commit tests: which episodes become ledger entries, and how."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gridagent_orchestrator.ledger_commit import commit_episode, entry_from_episode


@pytest.fixture(autouse=True)
def isolated_data_root(tmp_path, monkeypatch):
    monkeypatch.setenv("GRIDAGENT_DATA_ROOT", str(tmp_path))
    return tmp_path


def _write_episode(tmp_path: Path, records: list[dict]) -> Path:
    log = tmp_path / "episode_test.jsonl"
    log.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    return log


_START = {"event": "start", "episode_id": "abc123", "goal": "test goal", "ts": 1.0}
_FINISH = {"event": "finish", "summary": "did the thing", "ts": 2.0}


def _step(step, tool, arguments=None, value=None, signal=None, decision="advance"):
    return {
        "event": "step", "step": step, "tool": tool,
        "arguments": arguments or {}, "value": value or {},
        "signal": signal or {}, "decision": decision, "attempt": 1, "ts": 1.5,
    }


def test_study_episode_commits(tmp_path):
    log = _write_episode(
        tmp_path,
        [
            _START,
            _step(1, "list_data_snapshots", value={"snapshots": [{"id": "snap_x"}]}),
            _step(2, "run_injection_study",
                  arguments={"bus_id": "309", "p_mw": 250.0, "scenario_id": None},
                  signal={"feasible": True, "n_new_overloads": 3}),
            _FINISH,
        ],
    )
    entry = entry_from_episode(
        log,
        workflow_name="injection_study",
        workflow_inputs={"bus_id": "309", "p_mw": 250.0},
    )
    assert entry is not None
    assert entry["question"]["intent"] == "injection_study"
    # Inputs are pinned so revalidation can re-execute the entry verbatim.
    assert entry["method"]["inputs"] == {"bus_id": "309", "p_mw": 250.0}
    assert entry["subject"]["subsystem"]["buses"] == ["309"]
    # Scenario-less injection synthesizes its delta as the model-state change.
    assert entry["model_state"]["change_table"] == {"add_injection": {"309": 250.0}}
    assert entry["model_state"]["snapshot_id"] == "snap_x"
    assert entry["method"]["type"] == "workflow"
    assert entry["method"]["spec_sha256"]  # spec file exists and hashed
    assert entry["results"]["summary"] == "did the thing"
    assert entry["trace"]["episode_id"] == "abc123"

    entry_id = commit_episode(log, workflow_name="injection_study")
    assert entry_id


def test_retrieval_only_episode_does_not_commit(tmp_path):
    log = _write_episode(
        tmp_path,
        [
            _START,
            _step(1, "list_data_snapshots", value={"snapshots": [{"id": "snap_x"}]}),
            _step(2, "query_ledger", signal={"n_matches": 1}),
            _FINISH,
        ],
    )
    assert entry_from_episode(log) is None
    assert commit_episode(log) is None


def test_retried_study_commits_last_advance_only(tmp_path):
    log = _write_episode(
        tmp_path,
        [
            _START,
            _step(1, "run_power_flow", arguments={"scenario_id": "s1"},
                  signal={"converged": False}, decision="retry"),
            _step(2, "run_power_flow", arguments={"scenario_id": "s1"},
                  signal={"converged": True}, decision="advance"),
            _FINISH,
        ],
    )
    entry = entry_from_episode(log)
    assert entry is not None
    studies = entry["results"]["studies"]
    assert len(studies) == 1
    assert studies[0]["signal"] == {"converged": True}


def test_agent_method_when_no_workflow(tmp_path):
    log = _write_episode(
        tmp_path,
        [
            _START,
            _step(1, "create_scenario",
                  arguments={"name": "n", "change_table": {"scale_load": 1.2}},
                  value={"snapshot_id": "snap_y", "change_table": {"scale_load": 1.2}}),
            _step(2, "run_n1_contingency", arguments={"scenario_id": "s1"},
                  signal={"n_overloads": 4}),
            _FINISH,
        ],
    )
    entry = entry_from_episode(log)
    assert entry is not None
    assert entry["method"]["type"] == "agent"
    assert entry["question"]["intent"] == "n1_contingency"
    assert entry["model_state"]["snapshot_id"] == "snap_y"
    assert entry["model_state"]["change_table"] == {"scale_load": 1.2}
    assert entry["subject"]["subsystem"]["kind"] == "system"
