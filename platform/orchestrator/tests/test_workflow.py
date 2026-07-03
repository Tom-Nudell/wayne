"""Workflow engine tests: spec validation, binding resolution, runner decisions.

Tool functions are stubbed by swapping ``fn`` on the real ``TOOL_REGISTRY``
entries, so spec validation runs against the real tool names and ports while
execution stays hermetic (no data root, no pandapower).
"""

from __future__ import annotations

import json

import pytest
from gridagent_tools import TOOL_REGISTRY
from gridagent_tools.result import ToolResult

from gridagent_orchestrator.episode import Episode
from gridagent_orchestrator.verifier import Verifier
from gridagent_orchestrator.workflow import (
    WorkflowError,
    load_workflow,
    parse_workflow,
    render_goal,
    render_summary,
    resolve_inputs,
    run_workflow,
)


SNAPSHOT_VALUE = {"snapshots": [{"id": "snapshot_test", "counts": None}], "root": "x"}
RANKING = [
    {"outage": "br_9", "monitored": "br_3", "post_flow_mw": 240.0, "rating_mva": 100.0, "loading_pct": 240.0},
    {"outage": "br_2", "monitored": "br_7", "post_flow_mw": 130.0, "rating_mva": 100.0, "loading_pct": 130.0},
]


def _stub(monkeypatch, name: str, fn) -> None:
    monkeypatch.setattr(TOOL_REGISTRY[name], "fn", fn)


def _stub_happy_path(monkeypatch) -> None:
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
            signal={"scenario_id": "scn123", "n_changes": len(kw["change_table"])},
        ),
    )
    _stub(
        monkeypatch,
        "run_n1_contingency",
        lambda **kw: ToolResult(
            tool="run_n1_contingency",
            value={"n_screened": 12, "ranking": RANKING, "ranking_total": 2, "islanding_outages": []},
            signal={"n_overloads": 2, "n_screened": 12, "n_islanding": 0, "monotone": True, "worst_loading_pct": 240.0},
        ),
    )


@pytest.fixture
def episode(tmp_path):
    return Episode.new(goal="test", root=tmp_path)


def test_n1_spec_loads_and_validates():
    spec = load_workflow("n1_contingency")
    assert [n.id for n in spec.nodes] == ["snapshot", "branches", "scenario", "n1"]
    assert spec.inputs["scenario_name"]["default"] == "N-1 baseline"


def test_unknown_workflow_lists_available():
    with pytest.raises(WorkflowError, match="n1_contingency"):
        load_workflow("does_not_exist")


def test_load_workflow_rejects_traversal_names():
    for name in ("../evil", "a/b", "..", "evil.yaml", "name with space"):
        with pytest.raises(WorkflowError, match="Invalid workflow name"):
            load_workflow(name)


def test_workflow_root_env_dir_is_searched(tmp_path, monkeypatch):
    (tmp_path / "user_flow.yaml").write_text(
        "workflow: user_flow\ndescription: x\nnodes:\n  - id: snapshot\n    tool: list_data_snapshots\n"
    )
    monkeypatch.setenv("GRIDAGENT_WORKFLOW_ROOT", str(tmp_path))
    spec = load_workflow("user_flow")
    assert spec.name == "user_flow"


def test_happy_path_completes_with_zero_model_calls(monkeypatch, episode):
    _stub_happy_path(monkeypatch)
    spec = load_workflow("n1_contingency")
    inputs = resolve_inputs(spec, {"scenario_name": "unit test"})
    outcome = run_workflow(spec, inputs, verifier=Verifier.default(), episode=episode)

    assert outcome.status == "completed"
    assert [s.node for s in episode.steps] == ["snapshot", "branches", "scenario", "n1"]
    assert all(s.decision.value == "advance" for s in episode.steps)
    # Bindings flowed: scenario was created on the snapshot the first node found.
    assert episode.steps[2].arguments["snapshot_id"] == "snapshot_test"
    assert episode.steps[2].arguments["name"] == "unit test"
    assert episode.steps[3].arguments["scenario_id"] == "scn123"

    summary = render_summary(spec, inputs, outcome.context)
    assert "2 overload(s)" in summary
    assert "br_3 at 240% loading when br_9 is out" in summary

    # The log starts with start + workflow records, then steps.
    records = [json.loads(line) for line in episode.log_path.read_text().splitlines()]
    assert records[0]["event"] == "start"
    assert records[1]["event"] == "workflow"
    assert [n["id"] for n in records[1]["nodes"]] == ["snapshot", "branches", "scenario", "n1"]


def test_goal_renders_from_inputs():
    spec = load_workflow("n1_contingency")
    goal = render_goal(spec, resolve_inputs(spec, {"scenario_name": "Plant X"}))
    assert "Plant X" in goal


def test_summary_survives_empty_ranking(monkeypatch, episode):
    _stub_happy_path(monkeypatch)
    _stub(
        monkeypatch,
        "run_n1_contingency",
        lambda **kw: ToolResult(
            tool="run_n1_contingency",
            value={"n_screened": 12, "ranking": [], "ranking_total": 0, "islanding_outages": []},
            signal={"n_overloads": 0, "n_screened": 12, "n_islanding": 0, "monotone": True, "worst_loading_pct": 0.0},
        ),
    )
    spec = load_workflow("n1_contingency")
    inputs = resolve_inputs(spec, None)
    outcome = run_workflow(spec, inputs, verifier=Verifier.default(), episode=episode)
    assert outcome.status == "completed"
    summary = render_summary(spec, inputs, outcome.context)
    assert "0 overload(s)" in summary
    assert "n/a" in summary  # worst.* falls back instead of crashing


def test_tool_exception_escalates_with_replan_step(monkeypatch, episode):
    _stub_happy_path(monkeypatch)
    def boom(**kw):
        raise FileNotFoundError("no scenario root")
    _stub(monkeypatch, "create_scenario", boom)

    spec = load_workflow("n1_contingency")
    outcome = run_workflow(
        spec, resolve_inputs(spec, None), verifier=Verifier.default(), episode=episode
    )
    assert outcome.status == "escalate"
    assert outcome.failed_node == "scenario"
    assert "no scenario root" in outcome.reason
    # Earlier results are preserved as escalation context for the agent.
    assert set(outcome.context) == {"snapshot", "branches"}
    assert episode.steps[-1].decision.value == "replan"
    assert episode.steps[-1].node == "scenario"


def test_verifier_abort_aborts(monkeypatch, episode):
    _stub_happy_path(monkeypatch)
    _stub(
        monkeypatch,
        "run_n1_contingency",
        lambda **kw: ToolResult(
            tool="run_n1_contingency",
            value={"n_screened": 1, "ranking": [], "ranking_total": 0, "islanding_outages": []},
            signal={"n_overloads": 0, "n_screened": 1, "n_islanding": 0, "monotone": False, "worst_loading_pct": 0.0},
        ),
    )
    spec = load_workflow("n1_contingency")
    outcome = run_workflow(
        spec, resolve_inputs(spec, None), verifier=Verifier.default(), episode=episode
    )
    assert outcome.status == "aborted"
    assert outcome.failed_node == "n1"


def test_retry_rule_reruns_then_escalates(monkeypatch, episode):
    """_power_flow_rule: RETRY on attempt 1, REPLAN from attempt 2 — the
    workflow re-runs once, then hands over."""
    calls = {"n": 0}

    def never_converges(**kw):
        calls["n"] += 1
        return ToolResult(
            tool="run_power_flow",
            value={"converged": False},
            signal={"converged": False},
        )

    _stub(monkeypatch, "run_power_flow", never_converges)
    _stub(
        monkeypatch,
        "create_scenario",
        lambda **kw: ToolResult(
            tool="create_scenario",
            value={"scenario_id": "s1"},
            signal={"scenario_id": "s1", "n_changes": 0},
        ),
    )
    spec = parse_workflow(
        """
workflow: pf_test
description: power flow only
inputs: {}
nodes:
  - id: scenario
    tool: create_scenario
    bind: {name: pf, change_table: {}}
  - id: pf
    tool: run_power_flow
    bind: {scenario_id: $scenario.scenario_id}
"""
    )
    outcome = run_workflow(spec, {}, verifier=Verifier.default(), episode=episode)
    assert calls["n"] == 2  # attempt 1 RETRY → attempt 2 REPLAN
    assert outcome.status == "escalate"
    assert outcome.failed_node == "pf"
    attempts = [s.attempt for s in episode.steps if s.node == "pf"]
    assert attempts == [1, 2]


def test_validation_rejects_unknown_tool():
    with pytest.raises(WorkflowError, match="unknown tool"):
        parse_workflow(
            "workflow: bad\ndescription: x\nnodes:\n  - id: a\n    tool: not_a_tool\n"
        )


def test_validation_rejects_unknown_port():
    with pytest.raises(WorkflowError, match="no port"):
        parse_workflow(
            """
workflow: bad
description: x
nodes:
  - id: snapshot
    tool: list_data_snapshots
  - id: q
    tool: query_grid
    bind: {table: branches, snapshot_id: $snapshot.nope}
"""
        )


def test_validation_rejects_forward_reference():
    with pytest.raises(WorkflowError, match="later or unknown node"):
        parse_workflow(
            """
workflow: bad
description: x
nodes:
  - id: q
    tool: query_grid
    bind: {table: branches, snapshot_id: $snapshot.latest}
  - id: snapshot
    tool: list_data_snapshots
"""
        )


def test_empty_snapshots_aborts_instead_of_escalating(monkeypatch, episode):
    """An empty data root is operational, not fixable by the agent — the
    new list_data_snapshots verifier rule must ABORT, not burn LLM requests."""
    _stub_happy_path(monkeypatch)
    _stub(
        monkeypatch,
        "list_data_snapshots",
        lambda: ToolResult(
            tool="list_data_snapshots",
            value={"snapshots": [], "root": "x"},
            signal={"count": 0, "root_exists": False},
        ),
    )
    spec = load_workflow("n1_contingency")
    outcome = run_workflow(
        spec, resolve_inputs(spec, None), verifier=Verifier.default(), episode=episode
    )
    assert outcome.status == "aborted"
    assert outcome.failed_node == "snapshot"


def test_runtime_binding_failure_escalates(monkeypatch, episode):
    """A signal that passes the verifier but a value missing the bound path
    (signal says count=1, value.snapshots is empty) must escalate at the
    consuming node with prior context preserved — not crash."""
    _stub_happy_path(monkeypatch)
    _stub(
        monkeypatch,
        "list_data_snapshots",
        lambda: ToolResult(
            tool="list_data_snapshots",
            value={"snapshots": [], "root": "x"},
            signal={"count": 1, "root_exists": True},  # lies about the value shape
        ),
    )
    spec = load_workflow("n1_contingency")
    outcome = run_workflow(
        spec, resolve_inputs(spec, None), verifier=Verifier.default(), episode=episode
    )
    assert outcome.status == "escalate"
    assert outcome.failed_node == "branches"
    assert "binding failed" in outcome.reason
    assert set(outcome.context) == {"snapshot"}


def test_retries_exhausted_backstop(monkeypatch, episode):
    """A rule that returns RETRY forever must be bounded by _MAX_NODE_ATTEMPTS."""
    from gridagent_orchestrator.verifier import Decision
    from gridagent_orchestrator.workflow import _MAX_NODE_ATTEMPTS

    calls = {"n": 0}

    def flaky(**kw):
        calls["n"] += 1
        return ToolResult(tool="list_data_snapshots", value={"snapshots": []}, signal={})

    _stub(monkeypatch, "list_data_snapshots", flaky)
    always_retry = Verifier(rules={"list_data_snapshots": lambda s, a: Decision.RETRY})
    spec = parse_workflow(
        "workflow: retry_test\ndescription: x\nnodes:\n  - id: snapshot\n    tool: list_data_snapshots\n"
    )
    outcome = run_workflow(spec, {}, verifier=always_retry, episode=episode)
    assert calls["n"] == _MAX_NODE_ATTEMPTS
    assert outcome.status == "escalate"
    assert "retries exhausted" in outcome.reason


def test_resolved_ports_extracts_reusable_ids(monkeypatch):
    from gridagent_orchestrator.workflow import resolved_ports

    spec = load_workflow("n1_contingency")
    ports = resolved_ports(
        spec, "snapshot", {"value": SNAPSHOT_VALUE, "signal": {"count": 1}}
    )
    assert ports["latest"] == "snapshot_test"
    assert ports["count"] == 1


def test_inputs_reject_unknown_and_missing_required():
    spec = load_workflow("n1_contingency")
    with pytest.raises(WorkflowError, match="unknown inputs"):
        resolve_inputs(spec, {"typo_name": "x"})

    required = parse_workflow(
        """
workflow: req
description: x
inputs:
  must_have:
    required: true
nodes:
  - id: snapshot
    tool: list_data_snapshots
"""
    )
    with pytest.raises(WorkflowError, match="must_have"):
        resolve_inputs(required, {})


def test_default_inputs_are_copied_not_shared():
    spec = load_workflow("n1_contingency")
    a = resolve_inputs(spec, None)
    b = resolve_inputs(spec, None)
    a["change_table"]["scale_load"] = 1.5
    assert b["change_table"] == {}  # no aliasing between runs
