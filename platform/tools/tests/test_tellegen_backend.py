"""Tellegen backend tests.

Skip cleanly when the optional pieces are missing: the ``tellegen`` binary
(GRIDAGENT_TELLEGEN_BIN or PATH), the ``powerio`` package, or the RTS-GMLC
snapshot bundle.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from gridagent_tools.backends import BackendUnavailable, get_backend
from gridagent_tools.backends.tellegen import snapshot_to_matpower
from gridagent_tools.snapshot import Snapshot

_REPO = Path(__file__).resolve().parents[3]
_SNAPSHOT = _REPO / "data_root" / "bundle" / "snapshot_20260415_rts_gmlc"

powerio = pytest.importorskip("powerio")


@pytest.fixture(scope="module")
def snapshot() -> Snapshot:
    if not (_SNAPSHOT / "buses.parquet").exists():
        pytest.skip(f"no snapshot bundle at {_SNAPSHOT}")
    return Snapshot.at(_SNAPSHOT)


@pytest.fixture(scope="module")
def tellegen_backend():
    from gridagent_tools.backends.tellegen import _tellegen_bin

    try:
        _tellegen_bin()
    except BackendUnavailable as exc:
        pytest.skip(str(exc))
    return get_backend("tellegen")


def test_matpower_bridge_shape(snapshot: Snapshot) -> None:
    case, maps = snapshot_to_matpower(snapshot, {"change_table": {}})
    assert case.startswith("function mpc")
    assert len(maps["bus_ids"]) == len(snapshot.buses())
    # Only in-service branches are emitted.
    live = snapshot.branches()
    assert len(maps["branch_ids"]) == int(live["in_service"].astype(bool).sum())
    # powerio parses it without error and keeps every bus.
    conv = powerio.convert_str(case, "powerio-json", "matpower")
    net = powerio.from_json(conv.text)
    assert len(net.buses) == len(maps["bus_ids"])


def test_matpower_bridge_applies_change_table(snapshot: Snapshot) -> None:
    base, base_maps = snapshot_to_matpower(snapshot, {"change_table": {}})
    dropped_branch = base_maps["branch_ids"][0]
    case, maps = snapshot_to_matpower(
        snapshot, {"change_table": {"out_of_service_branches": [dropped_branch]}}
    )
    assert dropped_branch not in maps["branch_ids"]
    assert len(maps["branch_ids"]) == len(base_maps["branch_ids"]) - 1


def test_dc_opf_solves_and_rekeys(snapshot: Snapshot, tellegen_backend) -> None:
    out = tellegen_backend.dc_opf(snapshot, {"change_table": {}})
    assert out["signal"]["solver_status"] == "OPTIMAL"
    assert out["signal"]["objective"] > 0

    bus_ids = set(snapshot.buses()["bus_id"].astype(str))
    gen_ids = set(snapshot.generators()["generator_id"].astype(str))
    assert {r["bus_id"] for r in out["value"]["lmp"]} == bus_ids
    assert {r["generator_id"] for r in out["value"]["dispatch"]} <= gen_ids
    # Dispatch balances aggregate demand (DC, lossless).
    total_gen = sum(r["p_mw"] for r in out["value"]["dispatch"])
    total_load = float(snapshot.loads()["p_mw"].sum())
    assert abs(total_gen - total_load) < 1.0


def test_power_flow_converges_at_moderate_load(snapshot: Snapshot, tellegen_backend) -> None:
    out = tellegen_backend.power_flow(snapshot, {"change_table": {"scale_load": 0.8}})
    assert set(out["signal"]) == {"converged", "max_mismatch_mw"}
    assert out["signal"]["converged"] is True
    assert out["signal"]["max_mismatch_mw"] < 1e-3


def test_power_flow_base_case_reports_cleanly(snapshot: Snapshot, tellegen_backend) -> None:
    """RTS-GMLC base case has a ~105° angle spread; tellegen's flat-start NR
    does not converge there today (pandapower's DC-init NR does). The backend
    must surface that as a clean signal, not an exception. If this starts
    converging after a tellegen upgrade, tighten it to assert converged."""
    out = tellegen_backend.power_flow(snapshot, {"change_table": {}})
    assert set(out["signal"]) == {"converged", "max_mismatch_mw"}
    assert isinstance(out["signal"]["converged"], bool)
    if not out["signal"]["converged"]:
        assert "error" in out["value"]


def test_n1_and_production_cost_unavailable(snapshot: Snapshot) -> None:
    backend = get_backend("tellegen")
    with pytest.raises(BackendUnavailable):
        backend.n1_contingency(snapshot, {})
    with pytest.raises(BackendUnavailable):
        backend.production_cost(snapshot, {})


def test_pandapower_dc_opf_parity_shape(snapshot: Snapshot) -> None:
    pytest.importorskip("pandapower")
    out = get_backend("pandapower").dc_opf(snapshot, {"change_table": {}})
    assert out["signal"]["solver_status"] == "OPTIMAL"
    assert {"objective", "lmp_min", "lmp_max", "lmp_spread", "n_binding"} <= set(out["signal"])
