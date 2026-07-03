"""run.py orchestration tests: workflow episodes, escalation handover, CLI guards.

The agent itself is stubbed (`_drive_agent`) — these tests pin the wiring
around it: episode records, summaries, escalation prompts, overlay-event
emission, and CLI argument validation.
"""

from __future__ import annotations

import json
import sys

import pytest
from gridagent_tools import TOOL_REGISTRY
from gridagent_tools.result import ToolResult

import gridagent_orchestrator.run as run_mod
from gridagent_orchestrator.episode import Episode
from gridagent_orchestrator.run import _export_overlays, run_workflow_episode


SNAPSHOT_VALUE = {"snapshots": [{"id": "snapshot_test", "counts": None}], "root": "x"}
RANKING = [
    {"outage": "br_9", "monitored": "br_3", "post_flow_mw": 240.0, "rating_mva": 100.0, "loading_pct": 240.0},
]


def _stub(monkeypatch, name, fn):
    monkeypatch.setattr(TOOL_REGISTRY[name], "fn", fn)


@pytest.fixture
def stubbed_tools(monkeypatch):
    _stub(
        monkeypatch,
        "list_data_snapshots",
        lambda: ToolResult(
            tool="list_data_snapshots",
            value=SNAPSHOT_VALUE,
            signal={"count": 1, "root_exists": True},
        ),
    )
    _stub(
        monkeypatch,
        "query_grid",
        lambda **kw: ToolResult(
            tool="query_grid",
            value={"table": kw["table"], "snapshot_id": kw["snapshot_id"], "rows": [{}]},
            signal={"row_count": 1, "truncated": False},
        ),
    )
    _stub(
        monkeypatch,
        "create_scenario",
        lambda **kw: ToolResult(
            tool="create_scenario",
            value={"scenario_id": "scn123", "name": kw["name"], "snapshot_id": kw["snapshot_id"], "change_table": kw["change_table"]},
            signal={"scenario_id": "scn123", "n_changes": 0},
        ),
    )
    _stub(
        monkeypatch,
        "run_n1_contingency",
        lambda **kw: ToolResult(
            tool="run_n1_contingency",
            value={"n_screened": 12, "ranking": RANKING, "ranking_total": 1, "islanding_outages": []},
            signal={"n_overloads": 1, "n_screened": 12, "n_islanding": 0, "monotone": True, "worst_loading_pct": 240.0},
        ),
    )


@pytest.fixture
def episode_root(tmp_path, monkeypatch):
    monkeypatch.setenv("GRIDAGENT_EPISODE_ROOT", str(tmp_path))
    return tmp_path


def _records(episode):
    return [json.loads(line) for line in episode.log_path.read_text().splitlines()]


def test_workflow_episode_completed_renders_summary(stubbed_tools, episode_root, monkeypatch):
    def fail_if_called(*a, **kw):
        raise AssertionError("agent must not run on the happy path")

    monkeypatch.setattr(run_mod, "_drive_agent", fail_if_called)
    episode = run_workflow_episode("n1_contingency", {"scenario_name": "test"})
    records = _records(episode)
    assert records[-1]["event"] == "finish"
    assert "1 overload(s)" in records[-1]["summary"]
    assert "br_3 at 240% loading" in records[-1]["summary"]


def test_workflow_episode_aborted_finishes_with_abort_summary(
    stubbed_tools, episode_root, monkeypatch
):
    _stub(
        monkeypatch,
        "run_n1_contingency",
        lambda **kw: ToolResult(
            tool="run_n1_contingency",
            value={"n_screened": 1, "ranking": [], "ranking_total": 0, "islanding_outages": []},
            signal={"n_overloads": 0, "n_screened": 1, "n_islanding": 0, "monotone": False, "worst_loading_pct": 0.0},
        ),
    )
    monkeypatch.setattr(run_mod, "_drive_agent", lambda *a, **kw: pytest.fail("no agent on abort"))
    episode = run_workflow_episode("n1_contingency", None)
    finish = _records(episode)[-1]
    assert finish["event"] == "finish"
    assert "Aborted at workflow node 'n1'" in finish["summary"]


def test_workflow_episode_escalates_with_port_context(stubbed_tools, episode_root, monkeypatch):
    def boom(**kw):
        raise FileNotFoundError("scenario root gone")

    _stub(monkeypatch, "create_scenario", boom)

    captured = {}

    def fake_agent(episode, prompt, **kw):
        captured["prompt"] = prompt
        episode.finish(summary="agent finished it")

    monkeypatch.setattr(run_mod, "_drive_agent", fake_agent)
    episode = run_workflow_episode("n1_contingency", None)

    records = _records(episode)
    events = [r["event"] for r in records]
    assert "escalate" in events
    esc = next(r for r in records if r["event"] == "escalate")
    assert esc["node"] == "scenario"
    # The handover prompt carries reusable port values, not just signals —
    # the agent needs the snapshot id to continue without re-orienting.
    assert "snapshot_test" in captured["prompt"]
    assert "do NOT repeat" in captured["prompt"]
    assert records[-1]["summary"] == "agent finished it"


def test_export_overlays_suppresses_event_when_empty(tmp_path, monkeypatch):
    import gridagent_orchestrator.overlay_export as oe

    episode = Episode.new(goal="g", root=tmp_path)
    monkeypatch.setattr(oe, "write_episode_overlays", lambda log, d: (0, episode.episode_id))
    events: list[dict] = []
    _export_overlays(episode, tmp_path, emit=lambda m: None, on_event=events.append)
    assert events == []  # no overlay event → no 404 URL handed to the client

    monkeypatch.setattr(oe, "write_episode_overlays", lambda log, d: (3, episode.episode_id))
    _export_overlays(episode, tmp_path, emit=lambda m: None, on_event=events.append)
    assert [e["event"] for e in events] == ["overlay"]
    assert events[0]["feature_count"] == 3


@pytest.mark.parametrize(
    "inputs_arg",
    ["{not json", "[1, 2]", '"just a string"'],
)
def test_cli_rejects_bad_inputs(monkeypatch, inputs_arg):
    monkeypatch.setattr(
        sys, "argv", ["prog", "--workflow", "n1_contingency", "--inputs", inputs_arg]
    )
    with pytest.raises(SystemExit) as exc:
        run_mod.main()
    assert exc.value.code == 2  # argparse usage error, not a raw traceback


def test_cli_rejects_inputs_without_workflow(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["prog", "--goal", "x", "--inputs", "{}"])
    with pytest.raises(SystemExit) as exc:
        run_mod.main()
    assert exc.value.code == 2
