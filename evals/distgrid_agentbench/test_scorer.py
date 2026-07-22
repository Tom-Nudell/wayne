"""Scorer unit tests — pytest-compatible, but runnable with plain python3."""

from __future__ import annotations

from scorer import analyze, args_match, hallucinated_tools


def test_exact_match_is_success_and_precise():
    wf = [{"name": "load_transmission_network", "arguments": {}},
          {"name": "get_transmission_bus_voltage", "arguments": {"bus_id": 14}}]
    success, reason, precision = analyze(wf, wf)
    assert success and precision == 1.0 and reason == ""


def test_numeric_string_args_match():
    assert args_match({"bus_id": "14"}, {"bus_id": 14})
    assert args_match({"name": " Rochester "}, {"name": "rochester"})
    assert not args_match({"bus_id": 15}, {"bus_id": 14})
    assert not args_match({}, {"bus_id": 14})


def test_extra_agent_args_tolerated():
    assert args_match({"bus_id": 14, "verbose": True}, {"bus_id": 14})


def test_extra_steps_kill_precision_not_success():
    ref = [{"name": "a", "arguments": {}}]
    agent = [{"name": "setup", "arguments": {}}, {"name": "a", "arguments": {}}]
    success, _, precision = analyze(agent, ref)
    assert success and precision == 0.0


def test_missing_step_fails():
    ref = [{"name": "a", "arguments": {}}, {"name": "b", "arguments": {}}]
    agent = [{"name": "a", "arguments": {}}]
    success, reason, precision = analyze(agent, ref)
    assert not success and "b" in reason and precision == 0.0


def test_order_matters():
    ref = [{"name": "a", "arguments": {}}, {"name": "b", "arguments": {}}]
    agent = [{"name": "b", "arguments": {}}, {"name": "a", "arguments": {}}]
    success, _, _ = analyze(agent, ref)
    assert not success


def test_empty_ref_trivially_succeeds():
    success, _, precision = analyze([], [])
    assert success and precision == 1.0


def test_hallucinated_tools_detected():
    wf = [{"name": "real_tool", "arguments": {}}, {"name": "fake_tool", "arguments": {}}]
    assert hallucinated_tools(wf, {"real_tool"}) == ["fake_tool"]


if __name__ == "__main__":
    import sys
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ok   {name}")
            except AssertionError as exc:
                failures += 1
                print(f"  FAIL {name}: {exc}")
    sys.exit(1 if failures else 0)
