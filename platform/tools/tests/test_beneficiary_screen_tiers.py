"""Tests for the tiered beneficiary-load screening funnel.

Tier 0 (headroom / next_capacity), Tier 1 (screen_poi_potential -- the
certified optimistic bound used for ranking), and Tier 2
(poi_recourse_capacity -- the exact DC-achievable LP value) are pinned
down here with small hand-built cases, independent of the pre-existing
fixed-dispatch tests in test_beneficiary_screen.py.
"""

from __future__ import annotations

import numpy as np
import pytest

from gridagent_tools.beneficiary_screen import (
    append_intact_contingency,
    poi_recourse_capacity,
    recourse_dispatch_for_contingency,
    screen_beneficiary_loads,
    screen_poi_potential,
)


def test_ordering_invariant_holds_across_poi_potential_results() -> None:
    """For every POI: headroom <= potential, unlock >= 0, next >= headroom."""
    rng = np.random.default_rng(7)
    referenced_factors = rng.uniform(-1.0, 1.0, size=(3, 2, 5))
    base_contingency_flow = rng.uniform(-30.0, 30.0, size=(3, 2))
    limit_mw = rng.uniform(80.0, 120.0, size=(3, 1))
    valid = np.ones((3, 2), dtype=bool)
    ader_bus_columns = np.array([0, 1])
    u = rng.uniform(5.0, 20.0, size=2)
    w = rng.uniform(5.0, 20.0, size=2)

    results = screen_poi_potential(
        referenced_factors,
        base_contingency_flow,
        limit_mw,
        valid,
        ader_bus_columns=ader_bus_columns,
        ader_injection_max_mw=u,
        ader_withdrawal_max_mw=w,
        poi_bus_columns=[2, 3, 4],
    )

    assert len(results) == 3
    for r in results:
        assert r.headroom_mw <= r.potential_capacity_mw + 1e-9
        assert r.potential_unlock_mw >= -1e-9
        assert r.next_capacity_mw >= r.headroom_mw - 1e-9


def test_do_nothing_floor_beats_a_worsening_fixed_dispatch() -> None:
    """A fixed dispatch can make a POI worse; the screen never does.

    Single monitored/contingency pair, B=3 (bus0=ADER, bus1=POI A,
    bus2=POI B). d[ader]=+1, d[A]=-1, d[B]=+1, so g_A=+1, g_B=-1: a +30 MW
    injection at the ADER node relieves POI B but tightens POI A.
    """
    referenced_factors = np.array([[[1.0, -1.0, 1.0]]])  # (M=1, C=1, B=3)
    base_contingency_flow = np.array([[50.0]])
    limit_mw = np.array([[100.0]])
    valid = np.array([[True]])

    # Fixed shared dispatch: +30 MW at the ADER bus.
    fixed_results = screen_beneficiary_loads(
        referenced_factors,
        base_contingency_flow,
        limit_mw,
        valid,
        action_bus_columns=np.array([0]),
        action_mw=np.array([30.0]),
        poi_bus_columns=[1, 2],
    )
    poi_a = next(r for r in fixed_results if r.poi_index == 0)
    # g_A = +1: base T = (100-50)/1 = 50; managed flow = 50+30=80,
    # managed T = (100-80)/1 = 20. Unlocked = 20-50 = -30 (worse).
    assert poi_a.unlocked_capacity_mw == pytest.approx(-30.0)

    # The screen: same case, ADER box wide enough to cover the +/-30 swing.
    potential_results = screen_poi_potential(
        referenced_factors,
        base_contingency_flow,
        limit_mw,
        valid,
        ader_bus_columns=np.array([0]),
        ader_injection_max_mw=np.array([30.0]),
        ader_withdrawal_max_mw=np.array([30.0]),
        poi_bus_columns=[1, 2],
    )
    poi_a_potential = next(r for r in potential_results if r.poi_index == 0)
    assert poi_a_potential.headroom_mw == pytest.approx(50.0)
    # Best-case dispatch for POI A alone is x=-30 (the OPPOSITE direction
    # from the fixed dispatch that hurt it): cdir = -sign(g)*d_ader =
    # -(+1)*1.0 = -1.0; r = max(cdir*u, -cdir*w) = max(-30, 30) = 30;
    # potential = 50 + 30/1 = 80.
    assert poi_a_potential.potential_capacity_mw == pytest.approx(80.0)
    assert poi_a_potential.potential_unlock_mw >= 0.0
    assert poi_a_potential.potential_unlock_mw == pytest.approx(30.0)


def test_envelope_bound_matches_hand_computed_arithmetic() -> None:
    """Single pair, single ADER node: r and t_bound match by hand.

    d_ader = 0.4, d_poi = -0.6 -> g = 0.6 (positive branch).
    base_flow=20, limit=50 -> t0 = (50-20)/0.6 = 50.0.
    u=10, w=4: s=sign(g)=+1, cdir = -1*0.4 = -0.4.
    r = max(cdir*u, -cdir*w) = max(-0.4*10, 0.4*4) = max(-4.0, 1.6) = 1.6.
    t_bound = t0 + r/|g| = 50.0 + 1.6/0.6 = 50 + 8/3 = 52.666...
    """
    referenced_factors = np.array([[[0.4, -0.6]]])  # (M=1, C=1, B=2)
    base_contingency_flow = np.array([[20.0]])
    limit_mw = np.array([[50.0]])
    valid = np.array([[True]])

    results = screen_poi_potential(
        referenced_factors,
        base_contingency_flow,
        limit_mw,
        valid,
        ader_bus_columns=np.array([0]),
        ader_injection_max_mw=np.array([10.0]),
        ader_withdrawal_max_mw=np.array([4.0]),
        poi_bus_columns=[1],
    )
    r = results[0]
    assert r.headroom_mw == pytest.approx(50.0)
    assert r.ader_relief_mw == pytest.approx((1.6,))
    assert r.potential_capacity_mw == pytest.approx(50.0 + 1.6 / 0.6)
    assert r.potential_unlock_mw == pytest.approx(1.6 / 0.6)


def test_pre_violated_loading_direction_pair_bounds_match_lp() -> None:
    """A pair already violated in the POI's own LOADING direction must not
    collapse the Tier-1 bound below Tier-2's achievable value (the second
    real-data regression, from a 6,717-bus Texas synthetic case).

    Row V (m=0, violated): g=1, d_ader=-1, f0=120, limit=100 -> raw t0 =
        (100-120)/1 = -20.0 (already past the limit in the direction
        increasing T also pushes toward). Old (buggy) bound was
        t0 + r/|g| = -20 + 20 = 0.0; the fixed bound clamps the headroom
        term first: max(t0,0) + r/|g| = 0 + 20 = 20.0.
    Row N (m=1, normal): g=1, d_ader=-1, f0=30, limit=100 -> raw t0 =
        (100-30)/1 = 70.0; bound (same either way since t0>0) = 70+20=90.
    ADER: single node, u=w=20 -> cdir = -sign(g)*d_ader = -(+1)*(-1) = +1
        for both rows (same g sign, same d_ader) -> r = max(1*20,-1*-20)
        = 20.0 for both.

    headroom = max(0, min(-20, 70)) = 0.0: at x=0, any T>0 would worsen
        the already-violated row V, so Tier 0 stays 0 by construction.
    potential (fixed) = min(20.0, 90.0) = 20.0 -- not the old bug's 0.0.

    The non-LP assertions above need no scipy; the LP cross-check below
    does, and is isolated so the rest of the test still runs without it.

    Tier-2 hand check: row V's clamped upper row is
    "-x + T <= max(100-120,0) = 0" -> T <= x; row N's is
    "-x + T <= max(100-30,0) = 70" -> T <= x+70. T<=x is tighter for any
    x <= 20, so the optimum picks x=+20 (the top of the box), giving
    T_max = 20 -- exactly the fixed Tier-1 bound in this single-
    contingency, single-node case (the LP's one shared x also happens to
    be each row's own best-case x here).
    """
    referenced_factors = np.array(
        [
            [[-1.0, -1.0]],  # m=0 (row V): d_ader=-1, d_poi=-1 -> g=1
            [[-1.0, -1.0]],  # m=1 (row N): d_ader=-1, d_poi=-1 -> g=1
        ]
    )  # (M=2, C=1, B=2)
    base_contingency_flow = np.array([[120.0], [30.0]])
    limit_mw = np.array([[100.0], [100.0]])
    valid = np.array([[True], [True]])
    ader_bus_columns = np.array([0])
    u = np.array([20.0])
    w = np.array([20.0])

    potential = screen_poi_potential(
        referenced_factors,
        base_contingency_flow,
        limit_mw,
        valid,
        ader_bus_columns=ader_bus_columns,
        ader_injection_max_mw=u,
        ader_withdrawal_max_mw=w,
        poi_bus_columns=[1],
    )[0]

    assert potential.headroom_mw == pytest.approx(0.0, abs=1e-9)
    assert potential.potential_capacity_mw == pytest.approx(20.0, abs=1e-6)
    assert potential.potential_capacity_mw > 0.0  # the bug produced exactly 0.0

    pytest.importorskip("scipy")
    recourse = poi_recourse_capacity(
        referenced_factors,
        base_contingency_flow,
        limit_mw,
        valid,
        ader_bus_columns=ader_bus_columns,
        ader_injection_max_mw=u,
        ader_withdrawal_max_mw=w,
        poi_bus_column=1,
    )
    assert recourse.capacity_mw == pytest.approx(20.0, abs=1e-6)
    assert potential.headroom_mw <= recourse.capacity_mw + 1e-6
    assert recourse.capacity_mw <= potential.potential_capacity_mw + 1e-6


def test_co_binding_and_next_capacity_honest_tie() -> None:
    """Two identical-t0 rows: binder is the lower flat index, the other
    is a co-binder, and next_capacity equals that SAME tied value (not
    the next-strictly-larger one) -- the honest "resolving one constraint
    alone buys nothing" finding.

    Zero ADER bounds isolate Tier 0 (potential == headroom exactly).
    """
    # Row0: limit=100, flow=50 -> g=+1 -> t0=50. Row1: identical -> t0=50.
    # Row2: limit=100, flow=20 -> t0=80 (strictly larger).
    referenced_factors = np.zeros((3, 1, 2))
    referenced_factors[:, :, 1] = -1.0  # poi bus column -> g = +1 for all rows
    base_contingency_flow = np.array([[50.0], [50.0], [20.0]])
    limit_mw = np.array([[100.0], [100.0], [100.0]])
    valid = np.ones((3, 1), dtype=bool)

    results = screen_poi_potential(
        referenced_factors,
        base_contingency_flow,
        limit_mw,
        valid,
        ader_bus_columns=np.array([0]),
        ader_injection_max_mw=np.array([0.0]),
        ader_withdrawal_max_mw=np.array([0.0]),
        poi_bus_columns=[1],
    )
    r = results[0]
    assert r.headroom_mw == pytest.approx(50.0)
    assert r.binding is not None
    assert r.binding.monitored_index == 0  # lower flat index wins the tie
    assert len(r.co_binding) == 1
    assert r.co_binding[0].monitored_index == 1
    assert r.co_binding[0].transfer_limit_mw == pytest.approx(50.0)
    # Excluding ONLY k* (row0) leaves row1 (tied at 50) as next best.
    assert r.next_capacity_mw == pytest.approx(50.0)

    # Now remove the duplicate (keep only row0 and row2): no tie, so
    # next_capacity correctly reflects the strictly-larger second pair.
    referenced_factors2 = np.zeros((2, 1, 2))
    referenced_factors2[:, :, 1] = -1.0
    base_contingency_flow2 = np.array([[50.0], [20.0]])
    limit_mw2 = np.array([[100.0], [100.0]])
    valid2 = np.ones((2, 1), dtype=bool)

    results2 = screen_poi_potential(
        referenced_factors2,
        base_contingency_flow2,
        limit_mw2,
        valid2,
        ader_bus_columns=np.array([0]),
        ader_injection_max_mw=np.array([0.0]),
        ader_withdrawal_max_mw=np.array([0.0]),
        poi_bus_columns=[1],
    )
    r2 = results2[0]
    assert len(r2.co_binding) == 0
    assert r2.next_capacity_mw == pytest.approx(80.0)
    # Different from the tied case above -- proof next_capacity isn't
    # hardcoded to "second row" but genuinely reflects the second value.
    assert r2.next_capacity_mw != pytest.approx(r.next_capacity_mw)


def test_intact_contingency_can_be_the_binder() -> None:
    """Appending the intact network can make IT the binding pair, and
    omitting it would under-report severity (report a larger headroom).
    """
    # Pre-existing (loose) contingency column: g = -0.1 (negative branch).
    referenced_factors = np.array([[[0.1, 0.3]]])  # (M=1, C=1, B=2)
    base_contingency_flow = np.array([[10.0]])
    limit_mw = np.array([[100.0]])
    valid = np.array([[True]])

    # Intact (no-outage) state: g = -1.0, much tighter.
    base_referenced_factors = np.array([[1.0, 0.3]])  # (M=1, B=2)
    base_flow = np.array([90.0])  # (M=1,)

    zero_u = np.array([0.0])
    zero_w = np.array([0.0])

    without_intact = screen_poi_potential(
        referenced_factors,
        base_contingency_flow,
        limit_mw,
        valid,
        ader_bus_columns=np.array([1]),
        ader_injection_max_mw=zero_u,
        ader_withdrawal_max_mw=zero_w,
        poi_bus_columns=[0],
    )[0]
    # g=-0.1 (negative branch): (base_flow+limit)/(-g) = (10+100)/0.1 = 1100.
    assert without_intact.headroom_mw == pytest.approx(1100.0)

    new_factors, new_flow, new_valid, intact_index = append_intact_contingency(
        referenced_factors, base_contingency_flow, valid, base_referenced_factors, base_flow
    )
    assert intact_index == 1

    with_intact = screen_poi_potential(
        new_factors,
        new_flow,
        limit_mw,
        new_valid,
        ader_bus_columns=np.array([1]),
        ader_injection_max_mw=zero_u,
        ader_withdrawal_max_mw=zero_w,
        poi_bus_columns=[0],
    )[0]
    # g=-1.0 (negative branch): (90+100)/1.0 = 190 -- tighter than 1100.
    assert with_intact.headroom_mw == pytest.approx(190.0)
    assert with_intact.binding is not None
    assert with_intact.binding.contingency_index == intact_index
    assert with_intact.headroom_mw < without_intact.headroom_mw


def test_nan_in_base_contingency_flow_raises_value_error() -> None:
    referenced_factors = np.zeros((1, 1, 2))
    base_contingency_flow = np.array([[np.nan]])
    limit_mw = np.array([[100.0]])
    valid = np.array([[True]])

    with pytest.raises(ValueError):
        screen_poi_potential(
            referenced_factors,
            base_contingency_flow,
            limit_mw,
            valid,
            ader_bus_columns=np.array([0]),
            ader_injection_max_mw=np.array([1.0]),
            ader_withdrawal_max_mw=np.array([1.0]),
            poi_bus_columns=[1],
        )


# --------------------------------------------------------------------
# The following tests exercise poi_recourse_capacity (Tier 2), which
# requires scipy. The module itself has no top-level scipy import; only
# these tests need it, guarded per-test.
# --------------------------------------------------------------------


def _recourse_two_contingency_case():
    """Shared fixture for the killer recourse test and its variants.

    M=1, C=2, B=2 (bus0=ADER, bus1=POI). g=+1.0 for both contingencies
    (positive branch: t = limit - flow, since g=1).
    Contingency 0: d_ader = -1.0 -> a POSITIVE dispatch relieves it.
    Contingency 1: d_ader = +1.0 -> a NEGATIVE dispatch relieves it.
    Both start at flow=50, limit=100 -> t0 = 50 for both at x=0.
    """
    referenced_factors = np.array(
        [[[-1.0, -1.0], [1.0, -1.0]]]
    )  # (M=1, C=2, B=2)
    base_contingency_flow = np.array([[50.0, 50.0]])
    limit_mw = np.array([[100.0]])
    valid = np.array([[True, True]])
    return referenced_factors, base_contingency_flow, limit_mw, valid


def test_recourse_beats_any_single_fixed_dispatch() -> None:
    """The killer recourse test: opposite-sign relief per contingency.

    Recourse dispatches x0=+20 for c0 (T0=50+20=70) and x1=-20 for c1
    (T1=50+20=70) independently -> capacity = min(70,70) = 70.

    Any FIXED x must serve both contingencies at once:
    T0(x) = 50+x, T1(x) = 50-x -> capacity(x) = min(50+x, 50-x).
    At x=+20 (=+u): capacity = min(70, 30) = 30.
    At x=-20 (=-w): capacity = min(30, 70) = 30.
    Recourse (70) strictly beats both fixed extremes (30).
    """
    scipy = pytest.importorskip("scipy")
    del scipy

    referenced_factors, base_contingency_flow, limit_mw, valid = _recourse_two_contingency_case()
    u = np.array([20.0])
    w = np.array([20.0])

    recourse = poi_recourse_capacity(
        referenced_factors,
        base_contingency_flow,
        limit_mw,
        valid,
        ader_bus_columns=np.array([0]),
        ader_injection_max_mw=u,
        ader_withdrawal_max_mw=w,
        poi_bus_column=1,
    )
    assert recourse.capacity_mw == pytest.approx(70.0, abs=1e-6)

    fixed_plus = screen_beneficiary_loads(
        referenced_factors,
        base_contingency_flow,
        limit_mw,
        valid,
        action_bus_columns=np.array([0]),
        action_mw=np.array([20.0]),
        poi_bus_columns=[1],
    )[0]
    fixed_minus = screen_beneficiary_loads(
        referenced_factors,
        base_contingency_flow,
        limit_mw,
        valid,
        action_bus_columns=np.array([0]),
        action_mw=np.array([-20.0]),
        poi_bus_columns=[1],
    )[0]
    assert fixed_plus.managed_capacity_mw == pytest.approx(30.0)
    assert fixed_minus.managed_capacity_mw == pytest.approx(30.0)
    assert recourse.capacity_mw > fixed_plus.managed_capacity_mw
    assert recourse.capacity_mw > fixed_minus.managed_capacity_mw


def test_recourse_lp_respects_a_dispatch_sensitive_unaffected_facility() -> None:
    """A second facility under the same contingency, g~=0 (load-insensitive)
    but strongly affected by dispatch, with a tight limit: the LP must
    respect it, so capacity WITH it is strictly less than WITHOUT it.

    Row0 (m=0): g=1, d_ader=-1, flow=50, limit=100 -> T(x) = 50+x.
    Row1 (m=1): g=0 (poi factor 0), d_ader=5, flow=0, limit=20 ->
        |5x| <= 20 -> x in [-4, 4], independent of T.
    With row1 valid: x capped at 4 -> capacity = 50+4 = 54.
    Without row1: x capped only by the +/-20 ADER box -> capacity = 70.
    """
    pytest.importorskip("scipy")

    referenced_factors = np.array(
        [
            [[-1.0, -1.0]],  # m=0: d_ader=-1, d_poi=-1 -> g=+1
            [[5.0, 0.0]],  # m=1: d_ader=5, d_poi=0 -> g=0
        ]
    )  # (M=2, C=1, B=2)
    base_contingency_flow = np.array([[50.0], [0.0]])
    limit_mw = np.array([[100.0], [20.0]])
    u = np.array([20.0])
    w = np.array([20.0])

    valid_with = np.array([[True], [True]])
    valid_without = np.array([[True], [False]])

    with_row = poi_recourse_capacity(
        referenced_factors,
        base_contingency_flow,
        limit_mw,
        valid_with,
        ader_bus_columns=np.array([0]),
        ader_injection_max_mw=u,
        ader_withdrawal_max_mw=w,
        poi_bus_column=1,
    )
    without_row = poi_recourse_capacity(
        referenced_factors,
        base_contingency_flow,
        limit_mw,
        valid_without,
        ader_bus_columns=np.array([0]),
        ader_injection_max_mw=u,
        ader_withdrawal_max_mw=w,
        poi_bus_column=1,
    )

    assert with_row.capacity_mw == pytest.approx(54.0, abs=1e-6)
    assert without_row.capacity_mw == pytest.approx(70.0, abs=1e-6)
    assert with_row.capacity_mw < without_row.capacity_mw


def test_pre_existing_opposite_side_violation_does_not_zero_recourse() -> None:
    """A pre-existing violation the load doesn't push toward must not zero
    out recourse capacity (the real-data RTS-GMLC regression).

    Row A (m=0): g=1, d_ader=0 (dispatch-independent), f0=30, limit=100
        -> t0_A = (100-30)/1 = 70.0 (normal, not violated).
    Row B (m=1): g=0 (load-insensitive -- the load never moves this flow
        at all) AND d_ader=0 (dispatch can't touch it either -- genuinely
        "unable to cure"), f0=-80, limit=50 -> already violated by 30 MW
        on a side the load doesn't push toward. Pre-fix, the unclamped
        lower row was "0*x - 0*T <= limit+f0 = 50-80 = -30", i.e. the
        literal inequality "0 <= -30": infeasible for ANY x, T, regardless
        of the ADER box. Post-fix (RHS clamped at 0): the row becomes
        "0 <= max(-30, 0) = 0", always satisfied, and row B drops out of
        the LP entirely -- exactly matching how Tier 0 already treats it
        (g=0 means transfer_limits reports +inf for this row, so it never
        entered headroom either).

    Expected recourse capacity: exactly row A's own limit, 70.0 -- NOT the
    old bug's 0.0 -- and the sandwich holds against screen_poi_potential.
    """
    pytest.importorskip("scipy")

    referenced_factors = np.array(
        [
            [[0.0, -1.0]],  # m=0 (row A): d_ader=0, d_poi=-1 -> g=1
            [[0.0, 0.0]],  # m=1 (row B): d_ader=0, d_poi=0  -> g=0
        ]
    )  # (M=2, C=1, B=2)
    base_contingency_flow = np.array([[30.0], [-80.0]])
    limit_mw = np.array([[100.0], [50.0]])
    valid = np.array([[True], [True]])
    ader_bus_columns = np.array([0])
    u = np.array([20.0])
    w = np.array([20.0])

    recourse = poi_recourse_capacity(
        referenced_factors,
        base_contingency_flow,
        limit_mw,
        valid,
        ader_bus_columns=ader_bus_columns,
        ader_injection_max_mw=u,
        ader_withdrawal_max_mw=w,
        poi_bus_column=1,
    )
    assert recourse.capacity_mw == pytest.approx(70.0, abs=1e-6)
    assert recourse.capacity_mw > 0.0  # the bug produced exactly 0.0 here

    potential = screen_poi_potential(
        referenced_factors,
        base_contingency_flow,
        limit_mw,
        valid,
        ader_bus_columns=ader_bus_columns,
        ader_injection_max_mw=u,
        ader_withdrawal_max_mw=w,
        poi_bus_columns=[1],
    )[0]
    assert potential.headroom_mw == pytest.approx(70.0, abs=1e-6)
    assert potential.headroom_mw <= recourse.capacity_mw + 1e-6
    assert recourse.capacity_mw <= potential.potential_capacity_mw + 1e-6


def test_dispatch_may_not_worsen_a_pre_existing_violation() -> None:
    """Dispatch may relieve a facility that's within limit, but must not
    WORSEN one that's already violated at x=0 -- the "no worsening, no new
    binders" validity rule applied to a pre-existing violation.

    Row A (m=0): g=1, d_ader=-1 (a +x relieves A), f0=20, limit=100 ->
        t0_A = (100-20)/1 = 80.0. If dispatch could freely use +x up to
        u=20 with no other constraint, T_max would be 80+20 = 100.0.
    Row B (m=1): g=0 (load-insensitive), d_ader=-1 -- the SAME sign as
        row A's, so the identical +x that helps A also pushes B's flow
        further negative: flow_B(x) = -80 + (-1)*x = -80-x. B is already
        violated by 30 MW (|-80| > 50), and any x>0 makes it worse.
        Clamped lower row: "-d_ader_B*x <= max(limit_B+f0_B, 0)" ->
        "-(-1)*x <= max(50-80, 0) = 0" -> "x <= 0". This caps dispatch at
        exactly "no worse than base" for row B.

    So the LP cannot use +x to help row A beyond x=0: the optimal feasible
    x is exactly 0, giving capacity = 80.0 (row A's own limit) -- strictly
    less than the uncapped 100.0, proving the cap actively binds. Row B's
    lower row is exactly tight at x=0 (0 <= 0): the cap point itself.
    """
    pytest.importorskip("scipy")

    referenced_factors = np.array(
        [
            [[-1.0, -1.0]],  # m=0 (row A): d_ader=-1, d_poi=-1 -> g=1
            [[-1.0, 0.0]],  # m=1 (row B): d_ader=-1, d_poi=0  -> g=0
        ]
    )  # (M=2, C=1, B=2)
    base_contingency_flow = np.array([[20.0], [-80.0]])
    limit_mw = np.array([[100.0], [50.0]])
    valid = np.array([[True], [True]])
    ader_bus_columns = np.array([0])
    u = np.array([20.0])
    w = np.array([20.0])

    recourse = poi_recourse_capacity(
        referenced_factors,
        base_contingency_flow,
        limit_mw,
        valid,
        ader_bus_columns=ader_bus_columns,
        ader_injection_max_mw=u,
        ader_withdrawal_max_mw=w,
        poi_bus_column=1,
    )
    assert recourse.capacity_mw == pytest.approx(80.0, abs=1e-6)
    assert recourse.capacity_mw < 100.0  # proves the no-worsening cap binds
    assert recourse.binding_dispatch_mw is not None
    assert recourse.binding_dispatch_mw[0] == pytest.approx(0.0, abs=1e-6)


def test_recourse_dispatch_for_contingency_matches_full_solve() -> None:
    """recourse_dispatch_for_contingency reproduces poi_recourse_capacity's
    own per-contingency solve exactly -- both call the shared
    _solve_contingency_lp helper -- for the binding contingency, and also
    exposes a non-binding one on request.

    Reuses the killer recourse case (two contingencies, opposite-sign
    relief at the same ADER node): recourse capacity is 70.0, achieved by
    both c=0 (x=+20) and c=1 (x=-20) independently (see
    test_recourse_beats_any_single_fixed_dispatch for the arithmetic).
    """
    pytest.importorskip("scipy")

    referenced_factors, base_contingency_flow, limit_mw, valid = _recourse_two_contingency_case()
    ader_bus_columns = np.array([0])
    u = np.array([20.0])
    w = np.array([20.0])

    full = poi_recourse_capacity(
        referenced_factors,
        base_contingency_flow,
        limit_mw,
        valid,
        ader_bus_columns=ader_bus_columns,
        ader_injection_max_mw=u,
        ader_withdrawal_max_mw=w,
        poi_bus_column=1,
    )
    assert full.binding_contingency_index is not None
    assert full.binding_dispatch_mw is not None

    t_binding, x_binding = recourse_dispatch_for_contingency(
        referenced_factors,
        base_contingency_flow,
        limit_mw,
        valid,
        ader_bus_columns=ader_bus_columns,
        ader_injection_max_mw=u,
        ader_withdrawal_max_mw=w,
        poi_bus_column=1,
        contingency_index=full.binding_contingency_index,
    )
    # Same LP, same contingency -> must match the full solve's own value
    # for the binding contingency (capacity_mw IS that contingency's
    # solved T_c_max, since it's the argmin by construction) and dispatch.
    assert t_binding == pytest.approx(full.capacity_mw, abs=1e-6)
    assert x_binding == pytest.approx(full.binding_dispatch_mw, abs=1e-6)

    # The other contingency (there are exactly two, indices 0 and 1): its
    # own T_c_max must be >= the overall (min-over-contingencies) capacity.
    other_c = 1 - full.binding_contingency_index
    t_other, _x_other = recourse_dispatch_for_contingency(
        referenced_factors,
        base_contingency_flow,
        limit_mw,
        valid,
        ader_bus_columns=ader_bus_columns,
        ader_injection_max_mw=u,
        ader_withdrawal_max_mw=w,
        poi_bus_column=1,
        contingency_index=other_c,
    )
    assert t_other >= full.capacity_mw - 1e-6


def test_recourse_dispatch_respects_no_worsening() -> None:
    """The dispatch returned for an arbitrary contingency must never push
    an already-violated facility further past its limit.

    Reuses the no-worsening-cap case: row A (m=0) wants +x, but the
    identical +x would push already-violated row B (m=1, f0=-80 < -limit
    = -50) further negative. The hand-derived optimal dispatch is x=0
    exactly (see test_dispatch_may_not_worsen_a_pre_existing_violation),
    which leaves row B's flow exactly at its base value -- the boundary of
    "no worse than base".
    """
    pytest.importorskip("scipy")

    referenced_factors = np.array(
        [
            [[-1.0, -1.0]],  # m=0 (row A): d_ader=-1, d_poi=-1 -> g=1
            [[-1.0, 0.0]],  # m=1 (row B): d_ader=-1, d_poi=0  -> g=0
        ]
    )  # (M=2, C=1, B=2)
    base_contingency_flow = np.array([[20.0], [-80.0]])
    limit_mw = np.array([[100.0], [50.0]])
    valid = np.array([[True], [True]])
    ader_bus_columns = np.array([0])
    u = np.array([20.0])
    w = np.array([20.0])

    t_c_max, x_c = recourse_dispatch_for_contingency(
        referenced_factors,
        base_contingency_flow,
        limit_mw,
        valid,
        ader_bus_columns=ader_bus_columns,
        ader_injection_max_mw=u,
        ader_withdrawal_max_mw=w,
        poi_bus_column=1,
        contingency_index=0,
    )
    assert t_c_max == pytest.approx(80.0, abs=1e-6)

    f0_row_b = float(base_contingency_flow[1, 0])
    d_row_b = referenced_factors[1, 0, ader_bus_columns]
    flow_row_b_with_dispatch = f0_row_b + float(np.dot(d_row_b, x_c))
    # Row B is violated on the NEGATIVE side (f0=-80 < -limit=-50): "no
    # worse than base" means the dispatched flow must not go MORE
    # negative than the base flow.
    assert flow_row_b_with_dispatch >= f0_row_b - 1e-9


def _six_contingency_case():
    """M=1, C=6, B=2. g=+1 constant; d_ader alternates sign, |d_ader|=1.

    t0_raw[c] = 50 - 5*c for c=0..5 -> 50,45,40,35,30,25 (descending in c,
    so ascending-T_c0 processing order is c=5,4,3,2,1,0).
    ADER box +/-10 (P=1): best relief is always exactly +10 (since
    |d_ader|=1 and the box is symmetric), so T_c_max[c] = t0_raw[c] + 10:
    60,55,50,45,40,35.
    """
    n_c = 6
    referenced_factors = np.zeros((1, n_c, 2))
    for c in range(n_c):
        referenced_factors[0, c, 0] = -1.0 if c % 2 == 0 else 1.0  # d_ader
        referenced_factors[0, c, 1] = -1.0  # d_poi -> g = +1
    base_contingency_flow = np.array([[50.0 + 5.0 * c for c in range(n_c)]])
    limit_mw = np.array([[100.0]])
    valid = np.ones((1, n_c), dtype=bool)
    return referenced_factors, base_contingency_flow, limit_mw, valid


def test_skip_rule_matches_brute_force_and_actually_skips() -> None:
    pytest.importorskip("scipy")
    from scipy.optimize import linprog

    referenced_factors, base_contingency_flow, limit_mw, valid = _six_contingency_case()
    u = np.array([10.0])
    w = np.array([10.0])
    n_c = base_contingency_flow.shape[1]

    result = poi_recourse_capacity(
        referenced_factors,
        base_contingency_flow,
        limit_mw,
        valid,
        ader_bus_columns=np.array([0]),
        ader_injection_max_mw=u,
        ader_withdrawal_max_mw=w,
        poi_bus_column=1,
    )

    # Brute force: solve every contingency's LP independently, no skipping.
    g = -referenced_factors[:, :, 1]
    d = referenced_factors[:, :, [0]]
    brute_t_max = []
    for c in range(n_c):
        d_row = d[0, c, :]
        g_m = g[0, c]
        f0 = base_contingency_flow[0, c]
        lim = limit_mw[0, 0]
        a_ub = np.array(
            [
                [d_row[0], g_m],
                [-d_row[0], -g_m],
            ]
        )
        b_ub = np.array([lim - f0, lim + f0])
        bounds = [(-w[0], u[0]), (0.0, None)]
        c_obj = np.array([0.0, -1.0])
        res = linprog(c_obj, A_ub=a_ub, b_ub=b_ub, bounds=bounds, method="highs")
        assert res.status == 0
        brute_t_max.append(res.x[1])
    brute_capacity = max(0.0, min(brute_t_max))

    assert result.capacity_mw == pytest.approx(brute_capacity, abs=1e-6)
    assert result.capacity_mw == pytest.approx(35.0, abs=1e-6)
    assert result.lp_solves < n_c
    assert result.contingencies_skipped > 0


def test_sandwich_headroom_le_recourse_le_potential() -> None:
    pytest.importorskip("scipy")
    referenced_factors, base_contingency_flow, limit_mw, valid = _six_contingency_case()
    u = np.array([10.0])
    w = np.array([10.0])

    potential = screen_poi_potential(
        referenced_factors,
        base_contingency_flow,
        limit_mw,
        valid,
        ader_bus_columns=np.array([0]),
        ader_injection_max_mw=u,
        ader_withdrawal_max_mw=w,
        poi_bus_columns=[1],
    )[0]
    recourse = poi_recourse_capacity(
        referenced_factors,
        base_contingency_flow,
        limit_mw,
        valid,
        ader_bus_columns=np.array([0]),
        ader_injection_max_mw=u,
        ader_withdrawal_max_mw=w,
        poi_bus_column=1,
    )

    assert potential.headroom_mw == pytest.approx(25.0)
    assert potential.headroom_mw <= recourse.capacity_mw + 1e-6
    assert recourse.capacity_mw <= potential.potential_capacity_mw + 1e-6
