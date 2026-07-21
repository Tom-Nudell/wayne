"""Injection/withdrawal study tests: change-table primitive + diff tool.

Same skip posture as the tellegen backend tests: pieces that need the
tellegen binary or powerio skip cleanly when absent.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from gridagent_tools.backends import BackendUnavailable
from gridagent_tools.backends.pandapower import _apply_injections
from gridagent_tools.snapshot import Snapshot

_REPO = Path(__file__).resolve().parents[3]
_SNAPSHOT = _REPO / "data_root" / "bundle" / "snapshot_20260415_rts_gmlc"


@pytest.fixture(scope="module")
def snapshot() -> Snapshot:
    if not (_SNAPSHOT / "buses.parquet").exists():
        pytest.skip(f"no snapshot bundle at {_SNAPSHOT}")
    return Snapshot.at(_SNAPSHOT)


def test_apply_injections_adds_must_take_gen_and_load(snapshot: Snapshot) -> None:
    gens, loads = _apply_injections(
        snapshot.generators(),
        snapshot.loads(),
        {"add_injection": {"101": 150.0, "202": -80.0}},
    )
    inj = gens[gens["generator_id"] == "injection_101"]
    assert len(inj) == 1
    row = inj.iloc[0]
    # Must-take: pmin == pmax == MW, so no OPF can dispatch it away.
    assert row.p_min_mw == row.p_max_mw == 150.0
    assert row.fuel == "injection"

    wd = loads[loads["load_id"] == "withdrawal_202"]
    assert len(wd) == 1
    assert wd.iloc[0].p_mw == 80.0


def test_matpower_bridge_carries_injection(snapshot: Snapshot) -> None:
    from gridagent_tools.backends.tellegen import snapshot_to_matpower

    base, base_maps = snapshot_to_matpower(snapshot, {"change_table": {}})
    case, maps = snapshot_to_matpower(
        snapshot, {"change_table": {"add_injection": {"101": 150.0}}}
    )
    assert "injection_101" in maps["gen_ids"]
    assert len(maps["gen_ids"]) == len(base_maps["gen_ids"]) + 1
    # Zero marginal cost row exists for the injection (model-2 linear).
    assert case.count("\t0.0000\t0;") >= 1


def test_scenario_tool_accepts_add_injection(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GRIDAGENT_SCENARIO_ROOT", str(tmp_path))
    from gridagent_tools.scenario_tools import create_scenario

    out = create_scenario("inj test", {"add_injection": {"101": 100.0}})
    assert out.signal["n_changes"] == 1
    with pytest.raises(ValueError, match="Unknown change-table"):
        create_scenario("bad", {"add_injecton": {}})


@pytest.mark.parametrize("p_mw", [300.0, -150.0])
def test_run_injection_study_diffs_base(snapshot: Snapshot, monkeypatch, p_mw: float) -> None:
    from gridagent_tools.backends.tellegen import _tellegen_bin

    pytest.importorskip("powerio")
    pytest.importorskip("pandapower")
    try:
        _tellegen_bin()
    except BackendUnavailable as exc:
        pytest.skip(str(exc))

    monkeypatch.setenv("GRIDAGENT_DATA_ROOT", str(_REPO / "data_root"))
    from gridagent_tools.study_tools import run_injection_study

    out = run_injection_study(bus_id="212", p_mw=p_mw)
    sig, val = out.signal, out.value
    assert sig["feasible"] is True
    assert val["direction"] == ("injection" if p_mw > 0 else "withdrawal")
    # Free must-take injection lowers system cost; added load raises it.
    if p_mw > 0:
        assert sig["delta_objective"] < 0
    else:
        assert sig["delta_objective"] > 0
    assert isinstance(sig["n_new_overloads"], int)
    assert isinstance(sig["n_relieved_overloads"], int)
    # Diff report carries the base and modified LMP at the bus.
    assert val["lmp_at_bus_base"] is not None
    assert val["lmp_at_bus_modified"] is not None


def test_run_injection_study_validates_inputs(snapshot: Snapshot, monkeypatch) -> None:
    monkeypatch.setenv("GRIDAGENT_DATA_ROOT", str(_REPO / "data_root"))
    from gridagent_tools.study_tools import run_injection_study

    with pytest.raises(ValueError, match="not in snapshot"):
        run_injection_study(bus_id="no_such_bus", p_mw=100.0)
    with pytest.raises(ValueError, match="nonzero"):
        run_injection_study(bus_id="212", p_mw=0.0)
