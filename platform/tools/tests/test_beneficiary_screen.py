"""Beneficiary-load screen core tests: pure-numpy, no solver dependency.

These pin down the sign convention and the well-posedness of the BA
reference (invariance to the arbitrary PTDF slack) with hand-built cases,
independent of any pandapower snapshot.
"""

from __future__ import annotations

import numpy as np
import pytest

from gridagent_tools.beneficiary_screen import (
    ba_referenced_factors,
    dispatch_flow_change,
    otdf_from_ptdf_lodf,
    screen_beneficiary_loads,
    transfer_limits,
)


def test_otdf_and_ba_reference_match_hand_computed_case() -> None:
    # 2 monitored/contingency branches, 3 buses.
    ptdf = np.array(
        [
            [0.2, -0.5, 0.3],
            [-0.1, 0.4, -0.3],
        ]
    )
    lodf = np.array(
        [
            [0.0, 0.6],
            [0.8, 0.0],
        ]
    )
    otdf = otdf_from_ptdf_lodf(ptdf, lodf)
    expected_otdf = np.empty((2, 2, 3))
    for m in range(2):
        for c in range(2):
            expected_otdf[m, c, :] = ptdf[m, :] + lodf[m, c] * ptdf[c, :]
    np.testing.assert_allclose(otdf, expected_otdf)

    alpha = np.array([0.5, 0.25, 0.25])
    d = ba_referenced_factors(otdf, alpha)
    expected_d = np.empty_like(expected_otdf)
    for m in range(2):
        for c in range(2):
            expected_d[m, c, :] = expected_otdf[m, c, :] - np.dot(expected_otdf[m, c, :], alpha)
    np.testing.assert_allclose(d, expected_d)


def test_otdf_replaces_non_finite_lodf_with_zero() -> None:
    ptdf = np.array([[1.0, 2.0], [3.0, 4.0]])
    lodf = np.array([[0.0, np.nan], [np.inf, 0.0]])
    otdf = otdf_from_ptdf_lodf(ptdf, lodf)
    # Non-finite entries act as if lodf were 0 there: a[m,c,:] == ptdf[m,:].
    np.testing.assert_allclose(otdf[0, 1, :], ptdf[0, :])
    np.testing.assert_allclose(otdf[1, 0, :], ptdf[1, :])


def test_ba_reference_invariant_to_ptdf_slack_choice() -> None:
    """The BA reference must not depend on which bus the input PTDF used as slack.

    Shifting every PTDF row by an arbitrary constant across the bus axis is
    exactly what happens when the base PTDF is built against a different
    (arbitrary) reference bus. Because alpha sums to 1, that shift cancels
    out of d[q,b] = a[q,b] - sum_b' a[q,b'] * alpha[b'] identically. This is
    the property that makes the whole method well-posed.
    """
    rng = np.random.default_rng(0)
    ptdf = rng.normal(size=(4, 5))
    lodf = rng.normal(size=(4, 4))
    np.fill_diagonal(lodf, 0.0)
    alpha = np.array([0.1, 0.2, 0.3, 0.15, 0.25])
    assert alpha.sum() == pytest.approx(1.0)

    otdf = otdf_from_ptdf_lodf(ptdf, lodf)
    d = ba_referenced_factors(otdf, alpha)

    # Shift every row of ptdf by an arbitrary per-row constant k[m].
    k = rng.normal(size=ptdf.shape[0])
    shifted_ptdf = ptdf + k[:, None]
    shifted_otdf = otdf_from_ptdf_lodf(shifted_ptdf, lodf)
    shifted_d = ba_referenced_factors(shifted_otdf, alpha)

    np.testing.assert_allclose(d, shifted_d, atol=1e-10)


def test_injection_and_load_are_equal_and_opposite() -> None:
    ptdf = np.array([[0.3, -0.2, -0.1], [0.1, 0.1, -0.2]])
    lodf = np.array([[0.0, 0.5], [0.4, 0.0]])
    alpha = np.array([0.5, 0.3, 0.2])
    d = ba_referenced_factors(otdf_from_ptdf_lodf(ptdf, lodf), alpha)

    injection_bus = 1
    injection_change = dispatch_flow_change(d, np.array([injection_bus]), np.array([10.0]))
    load_factor = -d[:, :, injection_bus]
    load_change = -load_factor * 10.0  # +MW load at the same bus, same magnitude.

    np.testing.assert_allclose(injection_change, load_change)


def test_zero_net_action_produces_no_flow_change() -> None:
    ptdf = np.array([[0.3, -0.2, -0.1], [0.1, 0.1, -0.2]])
    lodf = np.array([[0.0, 0.5], [0.4, 0.0]])
    alpha = np.array([0.5, 0.3, 0.2])
    d = ba_referenced_factors(otdf_from_ptdf_lodf(ptdf, lodf), alpha)

    # +10 MW and -10 MW at the same bus net to zero action.
    change = dispatch_flow_change(d, np.array([0, 0]), np.array([10.0, -10.0]))
    np.testing.assert_allclose(change, np.zeros_like(change), atol=1e-12)


def test_transfer_limits_directionality_and_epsilon() -> None:
    base_flow = np.array([[50.0, -50.0, 10.0]])
    load_factor = np.array([[2.0, -2.0, 1e-10]])
    limit_mw = np.array([[100.0]])
    valid = np.ones_like(base_flow, dtype=bool)

    limits = transfer_limits(base_flow, load_factor, limit_mw, valid)

    # Positive branch: (upper - flow) / load_factor = (100 - 50) / 2 = 25.
    assert limits[0, 0] == pytest.approx(25.0)
    # Negative branch: (flow + upper) / (-load_factor) = (-50 + 100) / 2 = 25.
    assert limits[0, 1] == pytest.approx(25.0)
    # |load_factor| <= 1e-9 cannot bind: +inf.
    assert limits[0, 2] == np.inf


def test_transfer_limits_invalid_pairs_are_infinite() -> None:
    base_flow = np.array([[50.0]])
    load_factor = np.array([[2.0]])
    limit_mw = np.array([[100.0]])
    valid = np.array([[False]])

    limits = transfer_limits(base_flow, load_factor, limit_mw, valid)
    assert limits[0, 0] == np.inf


def test_screen_beneficiary_loads_ranks_by_unlocked_capacity() -> None:
    # Two POIs (bus columns 2 and 3), one ADER action at bus 0.
    # referenced_factors shape (M=2, C=2, B=4).
    referenced_factors = np.zeros((2, 2, 4))
    # POI at column 2 is coupled to the ADER action (column 0) with opposite
    # sign on branch 0 only, so the action relieves its binding constraint.
    referenced_factors[0, 0, 0] = 1.0
    referenced_factors[0, 0, 2] = 1.0
    # POI at column 3 is decoupled from the ADER action: no unlock.
    referenced_factors[0, 1, 3] = 1.0
    referenced_factors[1, 0, 3] = 1.0

    base_contingency_flow = np.array([[90.0, 0.0], [0.0, 90.0]])
    limit_mw = np.array([[100.0], [100.0]])
    valid = np.ones((2, 2), dtype=bool)

    results = screen_beneficiary_loads(
        referenced_factors,
        base_contingency_flow,
        limit_mw,
        valid,
        action_bus_columns=np.array([0]),
        action_mw=np.array([50.0]),
        poi_bus_columns=[2, 3],
        constraints_per_poi=4,
    )

    assert len(results) == 2
    ranked_poi_indices = [r.poi_index for r in results]
    assert ranked_poi_indices[0] == 0  # column-2 POI unlocks capacity, ranks first.
    assert results[0].rank == 1
    assert results[1].rank == 2
    assert results[0].unlocked_capacity_mw > results[1].unlocked_capacity_mw
    assert results[1].unlocked_capacity_mw == pytest.approx(0.0)


def test_screen_beneficiary_loads_respects_constraints_per_poi() -> None:
    n = 6
    referenced_factors = np.zeros((n, n, 2))
    referenced_factors[:, :, 0] = 0.3  # ADER action bus
    referenced_factors[:, :, 1] = 1.0  # POI bus
    base_contingency_flow = np.full((n, n), 10.0)
    limit_mw = np.full((n, 1), 100.0)
    valid = ~np.eye(n, dtype=bool)

    results = screen_beneficiary_loads(
        referenced_factors,
        base_contingency_flow,
        limit_mw,
        valid,
        action_bus_columns=np.array([0]),
        action_mw=np.array([10.0]),
        poi_bus_columns=[1],
        constraints_per_poi=3,
    )

    assert len(results[0].constraints) == 3
    ranks = [c.rank for c in results[0].constraints]
    assert ranks == [1, 2, 3]
