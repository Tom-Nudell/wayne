"""Engine-neutral DC beneficiary-load screening.

This module is the pure-numpy core of the beneficiary-load screen: given
linearized sensitivity factors (PTDF/OTDF/LODF-derived) and a BA
participation vector, it BA-references the factors, applies a signed ADER
dispatch, and computes before/after transfer limits for candidate load
points of interest (POIs).

It has no solver dependency. Callers backed by pandapower build the PTDF/
LODF tables themselves and call :func:`otdf_from_ptdf_lodf`; callers backed
by commercial tools (PSS/E, PowerWorld, TARA) that already export an OTDF
cube, or per-contingency OTDF slices, skip straight to
:func:`ba_referenced_factors`.

This is a DC screen, not an AC-feasible operating plan: it linearizes flow
around a single base-case solution and ignores voltage, reactive power, and
any post-contingency redispatch beyond the modeled BA participation. Treat
its output as a ranking / triage signal, not a dispatch instruction.

Sign convention used throughout:

* Sensitivity factors ``d[q, b]`` (or the pre-reference ``a[q, b]``) give the
  MW change on monitored/outage pair ``q`` per +1 MW injected at bus ``b``
  and withdrawn pro rata across the BA participation vector ``alpha``.
* A +1 MW *injection* at bus ``b``, balanced by BA backdown, changes flow on
  ``q`` by ``+d[q, b]``.
* A +1 MW *load* at bus ``b``, supplied by BA generation, changes flow on
  ``q`` by ``-d[q, b]`` — the load factor is the negation of the injection
  factor at the same bus.

Tiered screening funnel (added 2026-08-07, semantics settled with the
project owner):

For a candidate load POI, **headroom** (Tier 0) is the additional MW of
load the POI can take before any constraint binds. Constraints are (m, c)
pairs where c ranges over contingencies **including the intact network**
(see :func:`append_intact_contingency`) — the intact state is just another
screening column, not a special case. ADER nodes can be dispatched to
relieve flow, but only **once per contingency**: a single recourse vector
``x_c`` is shared by every monitored facility under that contingency, and
the fallback is always do-nothing (``x=0``), so any valid dispatch can only
help, never hurt, a POI's headroom.

The funnel has three tiers above headroom:

* **Tier 1** (:func:`screen_poi_potential`) is a certified *optimistic*
  upper bound on what any valid recourse dispatch could unlock — each
  constraint independently gets its own best-case dispatch, which is not
  simultaneously achievable in general, but guarantees no DC false
  negatives when selecting the study set. This is the number the screen
  ranks by.
* **Tier 2** (:func:`poi_recourse_capacity`) is the exact DC-achievable
  value: one LP per contingency, shared recourse across all monitored
  facilities under it, capacity is the min across contingencies.
* **Tier 3** is full AC study, outside this package.

The original :func:`screen_beneficiary_loads` (a *fixed*, shared dispatch
evaluated at every POI) predates this funnel and is retained as a sub-tool
for evaluating one specific proposed action — it is not a substitute for
Tier 1 or Tier 2, and a fixed dispatch can make a POI's capacity *worse*
(see its docstring).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

import numpy as np

__all__ = [
    "BeneficiaryConstraint",
    "BeneficiaryPoiResult",
    "otdf_from_ptdf_lodf",
    "ba_referenced_factors",
    "dispatch_flow_change",
    "transfer_limits",
    "screen_beneficiary_loads",
    "append_intact_contingency",
    "ScreenedConstraint",
    "PoiPotential",
    "screen_poi_potential",
    "RecourseResult",
    "poi_recourse_capacity",
]

# Below this magnitude a load factor is treated as "does not move this
# constraint" rather than risking a near-zero division.
_LOAD_FACTOR_EPSILON = 1e-9


@dataclass(frozen=True)
class BeneficiaryConstraint:
    """One monitored/outage pair among a POI's binding constraints.

    All fields are the raw numbers the algorithm produced for this pair —
    no geometry, no branch-name strings, no rounding. Callers that need
    those for display join them back in by ``monitored_index`` /
    ``outage_index``.
    """

    monitored_index: int
    outage_index: int
    rank: int
    limit_mw: float
    base_flow_mw: float
    managed_flow_mw: float
    ader_flow_change_mw: float
    poi_load_factor: float
    base_transfer_limit_mw: float
    managed_transfer_limit_mw: float


@dataclass(frozen=True)
class BeneficiaryPoiResult:
    """Screening result for one candidate load POI."""

    poi_index: int
    base_capacity_mw: float
    managed_capacity_mw: float
    unlocked_capacity_mw: float
    rank: int
    constraints: list[BeneficiaryConstraint] = field(default_factory=list)


def otdf_from_ptdf_lodf(
    ptdf: np.ndarray, lodf: np.ndarray, *, invalid_to_zero: bool = True
) -> np.ndarray:
    """Build the post-contingency OTDF cube from base PTDF and LODF.

    ``a[m, c, b] = ptdf[m, b] + lodf[m, c] * ptdf[c, b]``

    ptdf: (M, B) monitored-branch rows, bus columns, one consistent
        orientation. Also indexed by contingency branch ``c`` (its rows must
        cover the contingency set).
    lodf: (M, C) monitored branch ``m`` under outage of contingency branch
        ``c``. Entries for islanding/self-outage cases are typically NaN or
        inf; by default they're zeroed for this arithmetic only — exclude
        those columns from downstream screening via a ``valid`` mask rather
        than relying on this substitution.
    invalid_to_zero: replace non-finite LODF entries with 0.0 before
        multiplying, so a single bad entry doesn't NaN-poison a whole row.

    Returns (M, C, B).

    Commercial tools usually export the OTDF cube (or per-contingency OTDF
    slices) directly; those callers skip this function.
    """
    ptdf = np.asarray(ptdf, dtype=np.float64)
    lodf = np.asarray(lodf, dtype=np.float64)
    if invalid_to_zero:
        lodf = np.where(np.isfinite(lodf), lodf, 0.0)
    return ptdf[:, None, :] + lodf[:, :, None] * ptdf[None, :, :]


def ba_referenced_factors(otdf: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    """Apply the frozen BA reference: ``d[q,b] = a[q,b] - sum_b' a[q,b'] * alpha[b']``.

    otdf: (M, C, B) pre-reference sensitivity cube (e.g. from
        :func:`otdf_from_ptdf_lodf`, or supplied directly by a commercial
        tool).
    alpha: (B,) participation over BA buses, must sum to 1.0.

    Returns (M, C, B).

    +1 MW injection at ``b`` balanced by BA backdown changes flow on ``q``
    by ``+d[q,b]``. +1 MW load at ``b`` supplied by BA generation changes
    flow on ``q`` by ``-d[q,b]``.

    This re-referencing is what makes the result invariant to the arbitrary
    slack/reference bus baked into the input PTDF: shifting every PTDF row
    by a constant across the bus axis shifts ``a[q,b]`` by that same
    constant for every ``b``, which cancels exactly against the
    ``sum_b' a[q,b'] * alpha[b']`` term since ``alpha`` sums to 1.
    """
    otdf = np.asarray(otdf, dtype=np.float64)
    alpha = np.asarray(alpha, dtype=np.float64)
    ba_component = np.einsum("mcb,b->mc", otdf, alpha)
    return otdf - ba_component[:, :, None]


def dispatch_flow_change(
    referenced_factors: np.ndarray,
    action_bus_columns: np.ndarray,
    action_mw: np.ndarray,
) -> np.ndarray:
    """Flow change on every (m,c) from a signed ADER action.

    referenced_factors: (M, C, B) BA-referenced factors.
    action_bus_columns: bus-column index for each ADER node.
    action_mw: signed MW at each ADER node (positive injects at the node and
        withdraws pro rata across the BA; negative is the reverse).

    Returns (M, C).
    """
    referenced_factors = np.asarray(referenced_factors, dtype=np.float64)
    action_bus_columns = np.asarray(action_bus_columns)
    action_mw = np.asarray(action_mw, dtype=np.float64)
    return np.einsum("mcd,d->mc", referenced_factors[:, :, action_bus_columns], action_mw)


def transfer_limits(
    base_flow: np.ndarray,
    load_factor: np.ndarray,
    limit_mw: np.ndarray,
    valid: np.ndarray,
) -> np.ndarray:
    """Per-(m,c) positive-load transfer limit.

    Returns (M, C): the additional load (MW, always interpreted as a
    positive quantity moved along ``load_factor``) each pair can absorb
    before ``base_flow`` reaches ``limit_mw`` in either direction. +inf
    where the pair cannot bind (near-zero load factor, or excluded by
    ``valid``). Values may be negative when the pair is already in
    violation at zero added load — callers that want a non-negative
    "capacity" clamp at the point of use (see the module's ``screen_*``
    functions), so the raw signed value survives here for diagnostics.
    """
    base_flow = np.asarray(base_flow, dtype=np.float64)
    load_factor = np.asarray(load_factor, dtype=np.float64)
    limit_mw = np.asarray(limit_mw, dtype=np.float64)
    valid = np.asarray(valid, dtype=bool)

    transfer = np.full(base_flow.shape, np.inf, dtype=np.float64)
    positive = load_factor > _LOAD_FACTOR_EPSILON
    negative = load_factor < -_LOAD_FACTOR_EPSILON
    upper = np.broadcast_to(limit_mw, base_flow.shape)
    with np.errstate(divide="ignore", invalid="ignore"):
        transfer[positive] = ((upper - base_flow) / load_factor)[positive]
        transfer[negative] = ((base_flow + upper) / (-load_factor))[negative]
    transfer[~valid] = np.inf
    return transfer


def _capacity(limits: np.ndarray) -> float:
    """Binding transfer capacity across all pairs: the tightest limit, clamped at 0."""
    return max(0.0, float(np.nanmin(limits)))


def screen_beneficiary_loads(
    referenced_factors: np.ndarray,
    base_contingency_flow: np.ndarray,
    limit_mw: np.ndarray,
    valid: np.ndarray,
    *,
    action_bus_columns: np.ndarray,
    action_mw: np.ndarray,
    poi_bus_columns: Sequence[int],
    constraints_per_poi: int = 4,
    poi_sort_keys: Sequence[str] | None = None,
) -> list[BeneficiaryPoiResult]:
    """Rank candidate load POIs by unlocked BA-to-load transfer capability.

    For each POI bus, added load is supplied by the same BA participation
    vector used to reference ``referenced_factors``, so its load factor is
    ``-referenced_factors[:, :, poi_bus_column]``. Capacity is computed
    before and after the ADER action given by ``action_bus_columns`` /
    ``action_mw``; "unlocked" is the difference.

    referenced_factors: (M, C, B) BA-referenced sensitivity factors.
    base_contingency_flow: (M, C) pre-action post-contingency flow.
    limit_mw: (M, 1) or (M, C) branch rating, broadcastable to (M, C).
    valid: (M, C) mask of screenable pairs (excludes islanding/self-outage).
    poi_bus_columns: bus-column index for each candidate POI.
    constraints_per_poi: how many binding constraints to keep per POI.
    poi_sort_keys: optional secondary sort key per POI (e.g. the caller's
        bus id), used to break ties in unlocked capacity deterministically.
        Falls back to the POI's position in ``poi_bus_columns`` when None.

    Returns results sorted by ``(-unlocked_mw, poi order)``, rank assigned
    1..N.

    This evaluates one *specific, fixed, shared* dispatch supplied by the
    caller — it is a sub-tool for scoring a proposed action, not the POI
    screening score; see :func:`screen_poi_potential` for the certified
    upper-bound ranking metric.
    """
    referenced_factors = np.asarray(referenced_factors, dtype=np.float64)
    base_contingency_flow = np.asarray(base_contingency_flow, dtype=np.float64)
    limit_mw = np.asarray(limit_mw, dtype=np.float64)
    valid = np.asarray(valid, dtype=bool)

    ader_flow_change = dispatch_flow_change(referenced_factors, action_bus_columns, action_mw)
    managed_contingency_flow = base_contingency_flow + ader_flow_change

    if poi_sort_keys is None:
        secondary_keys: Sequence = list(range(len(poi_bus_columns)))
    else:
        secondary_keys = list(poi_sort_keys)

    unranked: list[tuple[int, float, float, float, list[BeneficiaryConstraint]]] = []
    for poi_index, bus_column in enumerate(poi_bus_columns):
        # Added load at POI l, supplied by the BA, has g_q,l = -d_q,l.
        load_factor = -referenced_factors[:, :, bus_column]
        base_limits = transfer_limits(base_contingency_flow, load_factor, limit_mw, valid)
        managed_limits = transfer_limits(
            managed_contingency_flow, load_factor, limit_mw, valid
        )
        base_capacity = _capacity(base_limits)
        managed_capacity = _capacity(managed_limits)

        # The smallest managed transfer limits are the constraints reached
        # first. Tie-break by the base limit and stable matrix index.
        candidates = np.flatnonzero(np.isfinite(managed_limits).ravel())
        candidates = sorted(
            candidates,
            key=lambda flat: (
                managed_limits.ravel()[flat],
                base_limits.ravel()[flat],
                int(flat),
            ),
        )[:constraints_per_poi]

        limit_broadcast = np.broadcast_to(limit_mw, base_contingency_flow.shape)
        constraint_rows: list[BeneficiaryConstraint] = []
        for rank, flat in enumerate(candidates, start=1):
            m, c = np.unravel_index(flat, managed_limits.shape)
            constraint_rows.append(
                BeneficiaryConstraint(
                    monitored_index=int(m),
                    outage_index=int(c),
                    rank=rank,
                    limit_mw=float(limit_broadcast[m, c]),
                    base_flow_mw=float(base_contingency_flow[m, c]),
                    managed_flow_mw=float(managed_contingency_flow[m, c]),
                    ader_flow_change_mw=float(ader_flow_change[m, c]),
                    poi_load_factor=float(load_factor[m, c]),
                    base_transfer_limit_mw=max(0.0, float(base_limits[m, c])),
                    managed_transfer_limit_mw=max(0.0, float(managed_limits[m, c])),
                )
            )

        unlocked_capacity = managed_capacity - base_capacity
        unranked.append((poi_index, base_capacity, managed_capacity, unlocked_capacity, constraint_rows))

    order = sorted(range(len(unranked)), key=lambda i: (-unranked[i][3], secondary_keys[i]))

    results: list[BeneficiaryPoiResult] = []
    for rank, i in enumerate(order, start=1):
        poi_index, base_capacity, managed_capacity, unlocked_capacity, constraint_rows = unranked[i]
        results.append(
            BeneficiaryPoiResult(
                poi_index=poi_index,
                base_capacity_mw=base_capacity,
                managed_capacity_mw=managed_capacity,
                unlocked_capacity_mw=unlocked_capacity,
                rank=rank,
                constraints=constraint_rows,
            )
        )
    return results


def append_intact_contingency(
    referenced_factors: np.ndarray,
    base_contingency_flow: np.ndarray,
    valid: np.ndarray,
    base_referenced_factors: np.ndarray,
    base_flow: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, int]:
    """Append a screening column for the intact network (no contingency).

    The intact network is a screening state like any contingency: its LODF
    is identically zero, so its BA-referenced factor slice is just the base
    BA-referenced factor (``base_referenced_factors``), and its flow is the
    base flow. Appending it here means every downstream function that loops
    over contingency columns automatically also screens the pre-contingency
    state, with no special-casing.

    referenced_factors: (M, C, B) BA-referenced factors.
    base_contingency_flow: (M, C) pre-contingency-column flow.
    valid: (M, C) screenable-pair mask.
    base_referenced_factors: (M, B) BA-referenced factors with no outage
        applied (e.g. ``d_base`` in the cube-free identity).
    base_flow: (M,) base-case flow (no outage).

    Returns ``(referenced_factors, base_contingency_flow, valid,
    intact_index)`` with one column appended at the end (index ``C``,
    returned as ``intact_index``). Pure concatenation; always float64.
    """
    referenced_factors = np.asarray(referenced_factors, dtype=np.float64)
    base_contingency_flow = np.asarray(base_contingency_flow, dtype=np.float64)
    valid = np.asarray(valid, dtype=bool)
    base_referenced_factors = np.asarray(base_referenced_factors, dtype=np.float64)
    base_flow = np.asarray(base_flow, dtype=np.float64)

    intact_index = referenced_factors.shape[1]
    new_referenced_factors = np.concatenate(
        [referenced_factors, base_referenced_factors[:, None, :]], axis=1
    )
    new_base_contingency_flow = np.concatenate(
        [base_contingency_flow, base_flow[:, None]], axis=1
    )
    new_valid = np.concatenate(
        [valid, np.ones((valid.shape[0], 1), dtype=bool)], axis=1
    )
    return new_referenced_factors, new_base_contingency_flow, new_valid, intact_index


@dataclass(frozen=True)
class ScreenedConstraint:
    """One monitored/contingency pair reported by :func:`screen_poi_potential`.

    Raw numbers only, same philosophy as :class:`BeneficiaryConstraint`:
    no geometry or names, callers join those back in by
    ``monitored_index`` / ``contingency_index``.
    """

    monitored_index: int
    contingency_index: int
    transfer_limit_mw: float
    limit_mw: float
    flow_mw: float
    load_factor: float


@dataclass(frozen=True)
class PoiPotential:
    """Tiered screening result for one candidate load POI.

    ``headroom_mw`` is Tier 0 (no dispatch). ``potential_capacity_mw`` /
    ``potential_unlock_mw`` are the Tier 1 certified optimistic bound. See
    :func:`screen_poi_potential` for the full semantics.
    """

    poi_index: int
    rank: int
    headroom_mw: float
    binding: ScreenedConstraint | None
    co_binding: tuple[ScreenedConstraint, ...]
    next_capacity_mw: float
    potential_capacity_mw: float
    potential_unlock_mw: float
    potential_binding: ScreenedConstraint | None
    ader_relief_mw: tuple[float, ...]


def screen_poi_potential(
    referenced_factors: np.ndarray,
    base_contingency_flow: np.ndarray,
    limit_mw: np.ndarray,
    valid: np.ndarray,
    *,
    ader_bus_columns: np.ndarray,
    ader_injection_max_mw: np.ndarray,
    ader_withdrawal_max_mw: np.ndarray,
    poi_bus_columns: Sequence[int],
    poi_sort_keys: Sequence | None = None,
) -> list[PoiPotential]:
    """Rank candidate load POIs by the Tier-1 certified optimistic bound.

    This is the screening metric: a certified *upper bound* on what ANY
    valid recourse dispatch (one ``x_c`` per contingency, within the ADER
    bus bounds, shared across every monitored facility under that
    contingency) could unlock for this POI. It is optimistic by
    construction — each constraint independently receives its own
    best-case dispatch, which is not necessarily simultaneously achievable
    across constraints — so it is suitable for building the study set S
    with no DC false negatives, but it is NOT an achievable operating
    value. :func:`poi_recourse_capacity` gives the exact, achievable-in-DC
    value (Tier 2).

    Do-nothing floor: ``x=0`` is always inside the dispatch box, so for
    every POI ``potential_capacity_mw >= headroom_mw`` and
    ``potential_unlock_mw >= 0`` by construction.

    The per-pair bound uses no-worsening semantics, consistent with
    :func:`poi_recourse_capacity`'s LP rows: a pair already violated at
    ``x=0`` in the POI's loading direction (``t0 < 0``) is held to "no
    worse than base", not "within limit", so it contributes ``r/|g|`` --
    the load admissible while the dispatch holds that pair no worse than
    base -- rather than a negative or zero value from adding relief
    directly to an already-negative ``t0``. Tier 0 (headroom, no dispatch)
    is unaffected by this and stays 0 in that situation by construction:
    with ``x=0``, any ``T > 0`` would worsen the already-violated pair, so
    the no-dispatch capacity is 0 regardless of how much relief a dispatch
    could later buy.

    referenced_factors: (M, C, B) BA-referenced factors. Include the
        intact network as a column (see :func:`append_intact_contingency`)
        if it should be screened alongside contingencies.
    base_contingency_flow: (M, C) pre-dispatch flow.
    limit_mw: (M, 1) or (M, C) branch rating, broadcastable to (M, C).
    valid: (M, C) screenable-pair mask.
    ader_bus_columns: bus-column index for each of the P ADER nodes.
    ader_injection_max_mw: (P,) per-node injection bound ``u``, >= 0.
    ader_withdrawal_max_mw: (P,) per-node withdrawal bound ``w``, >= 0.
        Dispatch at node p is constrained to ``-w[p] <= x[p] <= u[p]``.
    poi_bus_columns: bus-column index for each candidate POI.
    poi_sort_keys: optional secondary sort key per POI, same convention as
        :func:`screen_beneficiary_loads`.

    Raises ValueError if ``referenced_factors``, ``base_contingency_flow``,
    or ``limit_mw`` contains NaN, if ``ader_injection_max_mw`` or
    ``ader_withdrawal_max_mw`` has a negative entry, or if their shapes
    don't match ``ader_bus_columns``. This deliberately replaces the old
    ``nanmin``-swallows-NaN behavior with a loud failure: a NaN input here
    is a data bug, not a "no constraint" signal.

    Returns results sorted by ``(-potential_unlock_mw, poi order)``, rank
    assigned 1..N.
    """
    referenced_factors = np.asarray(referenced_factors, dtype=np.float64)
    base_contingency_flow = np.asarray(base_contingency_flow, dtype=np.float64)
    limit_mw_arr = np.asarray(limit_mw, dtype=np.float64)
    valid = np.asarray(valid, dtype=bool)
    ader_bus_columns = np.asarray(ader_bus_columns)
    u = np.asarray(ader_injection_max_mw, dtype=np.float64)
    w = np.asarray(ader_withdrawal_max_mw, dtype=np.float64)

    if np.isnan(referenced_factors).any():
        raise ValueError("referenced_factors contains NaN")
    if np.isnan(base_contingency_flow).any():
        raise ValueError("base_contingency_flow contains NaN")
    if np.isnan(limit_mw_arr).any():
        raise ValueError("limit_mw contains NaN")
    if np.any(u < 0):
        raise ValueError("ader_injection_max_mw must be >= 0 elementwise")
    if np.any(w < 0):
        raise ValueError("ader_withdrawal_max_mw must be >= 0 elementwise")
    if not (
        u.ndim == 1
        and w.ndim == 1
        and ader_bus_columns.ndim == 1
        and u.shape == w.shape == ader_bus_columns.shape
    ):
        raise ValueError(
            "ader_injection_max_mw, ader_withdrawal_max_mw, and "
            "ader_bus_columns must be 1-D with matching shape"
        )

    limit_broadcast = np.broadcast_to(limit_mw_arr, base_contingency_flow.shape)

    if poi_sort_keys is None:
        secondary_keys: Sequence = list(range(len(poi_bus_columns)))
    else:
        secondary_keys = list(poi_sort_keys)

    # d_ader[m, c, p]: BA-referenced factor at monitored/contingency pair
    # (m, c) for a +1 MW injection at ADER node p. Independent of POI.
    d_ader = referenced_factors[:, :, ader_bus_columns]  # (M, C, P)

    def make_constraint(
        g: np.ndarray, flat: int, transfer_value: float
    ) -> ScreenedConstraint:
        m, c = np.unravel_index(flat, g.shape)
        return ScreenedConstraint(
            monitored_index=int(m),
            contingency_index=int(c),
            transfer_limit_mw=max(0.0, float(transfer_value)),
            limit_mw=float(limit_broadcast[m, c]),
            flow_mw=float(base_contingency_flow[m, c]),
            load_factor=float(g[m, c]),
        )

    # Each entry: (poi_index, headroom, binding, co_binding, next_capacity,
    # potential_capacity, potential_unlock, potential_binding, ader_relief).
    unranked: list[tuple] = []

    for poi_index, bus_column in enumerate(poi_bus_columns):
        # Added load at POI l, supplied by the BA, has g_q,l = -d_q,l.
        g = -referenced_factors[:, :, bus_column]  # (M, C)
        t0 = transfer_limits(base_contingency_flow, g, limit_mw_arr, valid)
        flat_t0 = t0.ravel()
        finite_mask = np.isfinite(flat_t0)

        if not finite_mask.any():
            unranked.append(
                (poi_index, float("inf"), None, (), float("inf"), float("inf"), 0.0, None, ())
            )
            continue

        # np.argmin never returns a NaN-masked index here (inputs are
        # validated NaN-free above) and, on exact ties, returns the first
        # (lowest) flat index in row-major order -- exactly the tie-break
        # this screen wants.
        best_flat = int(np.argmin(flat_t0))
        headroom = max(0.0, float(flat_t0[best_flat]))
        binding = make_constraint(g, best_flat, flat_t0[best_flat])

        tol = max(1e-4, 1e-6 * max(float(flat_t0[best_flat]), 0.0))
        co_mask = flat_t0 <= (flat_t0[best_flat] + tol)
        co_mask[best_flat] = False
        co_flats = sorted(np.flatnonzero(co_mask).tolist(), key=lambda f: (flat_t0[f], f))
        co_binding = tuple(make_constraint(g, f, flat_t0[f]) for f in co_flats)

        # next_capacity: best over every finite pair EXCLUDING k* only (a
        # co-binder at the same value legitimately caps next_capacity too
        # -- that IS the honest finding that resolving one constraint
        # alone buys nothing).
        rest = flat_t0.copy()
        rest[best_flat] = np.inf
        next_capacity = max(0.0, float(np.min(rest)))

        # Tier 1 envelope: best-case relief at every pair independently.
        s = np.sign(g)  # (M, C); unused where |g| <= EPS (those pairs stay +inf)
        cdir = -s[:, :, None] * d_ader  # (M, C, P): unloading coefficient
        relief_term = np.maximum(cdir * u[None, None, :], -cdir * w[None, None, :])
        r = relief_term.sum(axis=2)  # (M, C), >= 0 everywhere

        abs_g = np.abs(g)
        with np.errstate(divide="ignore", invalid="ignore"):
            # Clamp the headroom term at 0 before adding relief: this is
            # what makes the bound match the LP's per-row no-worsening
            # semantics exactly (see the docstring and
            # poi_recourse_capacity's own RHS clamp). For a pair not
            # already violated (t0 > 0) this is identical to t0 + r/|g|;
            # for a pair already violated in the loading direction
            # (t0 < 0) it becomes r/|g| -- the load admissible while the
            # dispatch holds that pair no worse than base, not a negative
            # or zero bound from adding relief to an already-negative t0.
            t_bound = np.where(np.isfinite(t0), np.maximum(t0, 0.0) + r / abs_g, np.inf)
        flat_tb = t_bound.ravel()

        best_pot_flat = int(np.argmin(flat_tb))
        potential_capacity = max(0.0, float(flat_tb[best_pot_flat]))
        potential_binding = make_constraint(g, best_pot_flat, flat_tb[best_pot_flat])

        diff = potential_capacity - headroom
        if diff < -1e-9:
            raise AssertionError(
                f"potential_unlock_mw went negative ({diff!r}) for POI index "
                f"{poi_index}: Tier-1 bound must dominate Tier-0 headroom "
                "pairwise (r >= 0 everywhere)"
            )
        potential_unlock = max(0.0, diff)

        m_star, c_star = np.unravel_index(best_flat, g.shape)
        cdir_star = cdir[m_star, c_star, :]
        ader_relief = tuple(
            float(v) for v in np.maximum(cdir_star * u, -cdir_star * w)
        )

        unranked.append(
            (
                poi_index,
                headroom,
                binding,
                co_binding,
                next_capacity,
                potential_capacity,
                potential_unlock,
                potential_binding,
                ader_relief,
            )
        )

    order = sorted(range(len(unranked)), key=lambda i: (-unranked[i][6], secondary_keys[i]))

    results: list[PoiPotential] = []
    for rank, i in enumerate(order, start=1):
        (
            poi_index,
            headroom,
            binding,
            co_binding,
            next_capacity,
            potential_capacity,
            potential_unlock,
            potential_binding,
            ader_relief,
        ) = unranked[i]
        results.append(
            PoiPotential(
                poi_index=poi_index,
                rank=rank,
                headroom_mw=headroom,
                binding=binding,
                co_binding=co_binding,
                next_capacity_mw=next_capacity,
                potential_capacity_mw=potential_capacity,
                potential_unlock_mw=potential_unlock,
                potential_binding=potential_binding,
                ader_relief_mw=ader_relief,
            )
        )
    return results


@dataclass(frozen=True)
class RecourseResult:
    """Tier-2 exact-in-DC recourse capacity for one POI.

    See :func:`poi_recourse_capacity`.
    """

    capacity_mw: float
    binding_contingency_index: int | None
    binding_dispatch_mw: tuple[float, ...] | None
    lp_solves: int
    contingencies_skipped: int


def poi_recourse_capacity(
    referenced_factors: np.ndarray,
    base_contingency_flow: np.ndarray,
    limit_mw: np.ndarray,
    valid: np.ndarray,
    *,
    ader_bus_columns: np.ndarray,
    ader_injection_max_mw: np.ndarray,
    ader_withdrawal_max_mw: np.ndarray,
    poi_bus_column: int,
    max_load_mw: float | None = None,
) -> RecourseResult:
    """Exact DC-achievable recourse capacity for one POI (Tier 2).

    Unlike :func:`screen_poi_potential`'s per-constraint optimistic bound,
    this solves the real recourse problem: for each contingency ``c`` the
    ADER fleet applies ONE dispatch ``x_c`` (``-w <= x_c <= u``), and every
    monitored facility valid under ``c`` must stay within its limit for
    the shared additional load ``T`` at the POI simultaneously. ``T`` is
    shared across contingencies, so the achievable capacity is
    ``T_l = min over c of T_c_max``, and each ``T_c_max`` is its own LP:

        maximize T
        s.t. for every valid (m, c):
            d[m,c,:] . x_c + g[m,c] * T <=  max(limit[m,c] - f0[m,c], 0)
           -d[m,c,:] . x_c - g[m,c] * T <=  max(limit[m,c] + f0[m,c], 0)
        -w <= x_c <= u
        0 <= T <= max_load_mw (or unbounded above if max_load_mw is None)

    where ``g = -referenced_factors[:, :, poi_bus_column]``. ALL valid m
    under c are included, even those with a near-zero load factor -- the
    dispatch must not create a new binding violation at any of them; that
    is the "no new binding constraints" validity rule from the funnel
    semantics.

    The RHS of each row is clamped at 0. A facility already in violation
    at ``x=0`` (``|f0[m,c]| > limit[m,c]``) is held to "no worse than
    base", not "within limit": the validity rule is "do not worsen flows
    past limits or create new binding constraints", not "cure every
    pre-existing violation the load doesn't push toward". Without the
    clamp, a facility violated on the side AWAY from the POI's loading
    direction (or one the load barely touches at all) would demand an
    infeasible cure from the ADER box even though the load never created
    that violation -- this is what makes Tier 0 (which only screens the
    loading direction via :func:`transfer_limits`) and Tier 2 agree.

    Status handling per contingency: optimal -> ``T_c_max`` = the LP's T;
    unbounded (no valid m depends on T at all, so a dispatch-independent
    facility never actually appears once ``T_c0`` is finite -- see below)
    -> ``T_c_max = inf``; infeasible -> ``T_c_max = 0.0`` as a
    screening-conservative stand-in. With the RHS clamped at 0,
    ``(x=0, T=0)`` is always feasible, so infeasible is unreachable in
    practice; the branch is retained purely as a defensive guard against
    an unexpected solver result.

    Skip rule: ``T_c_max >= T_c0`` always, where ``T_c0`` is the no-dispatch
    (``x=0``) transfer limit for c, because ``(x=0, T=T_c0)`` is feasible
    under the clamped rows for every c (see the implementation comment at
    the skip-rule floor for the g>0/g<0 walk-through). Processing
    contingencies in ascending ``T_c0`` order, once the next ``T_c0 >=``
    the running min of solved ``T_c_max``, no remaining contingency can
    lower that min, so the rest are skipped without solving.

    ``headroom_mw <= capacity_mw <= potential_capacity_mw`` for the same
    POI (Tier 0 <= Tier 2 <= Tier 1).

    Requires scipy (``pip install scipy``); imported lazily so the module
    itself has no hard scipy dependency.
    """
    try:
        from scipy.optimize import linprog
    except ImportError as exc:
        raise RuntimeError(
            "poi_recourse_capacity requires scipy (pip install scipy)"
        ) from exc

    referenced_factors = np.asarray(referenced_factors, dtype=np.float64)
    base_contingency_flow = np.asarray(base_contingency_flow, dtype=np.float64)
    limit_mw_arr = np.asarray(limit_mw, dtype=np.float64)
    valid = np.asarray(valid, dtype=bool)
    ader_bus_columns = np.asarray(ader_bus_columns)
    u = np.asarray(ader_injection_max_mw, dtype=np.float64)
    w = np.asarray(ader_withdrawal_max_mw, dtype=np.float64)

    if np.isnan(referenced_factors).any():
        raise ValueError("referenced_factors contains NaN")
    if np.isnan(base_contingency_flow).any():
        raise ValueError("base_contingency_flow contains NaN")
    if np.isnan(limit_mw_arr).any():
        raise ValueError("limit_mw contains NaN")
    if np.any(u < 0):
        raise ValueError("ader_injection_max_mw must be >= 0 elementwise")
    if np.any(w < 0):
        raise ValueError("ader_withdrawal_max_mw must be >= 0 elementwise")
    if not (
        u.ndim == 1
        and w.ndim == 1
        and ader_bus_columns.ndim == 1
        and u.shape == w.shape == ader_bus_columns.shape
    ):
        raise ValueError(
            "ader_injection_max_mw, ader_withdrawal_max_mw, and "
            "ader_bus_columns must be 1-D with matching shape"
        )

    g = -referenced_factors[:, :, poi_bus_column]  # (M, C)
    d = referenced_factors[:, :, ader_bus_columns]  # (M, C, P)
    limit_broadcast = np.broadcast_to(limit_mw_arr, base_contingency_flow.shape)
    t0_all = transfer_limits(base_contingency_flow, g, limit_mw_arr, valid)  # (M, C)

    n_c = base_contingency_flow.shape[1]
    n_p = u.shape[0]

    # T_c0: the no-dispatch (x=0) transfer limit per contingency. With the
    # RHS clamped at 0, (x=0, T=T_c0) is feasible for every valid row under
    # c, so T_c_max >= T_c0 always -- this is the skip-rule floor.
    #
    # Proof, per valid row m under c. Let raw_m be what transfer_limits
    # would give for row m alone: (limit_m-f0_m)/g_m if g_m>EPS,
    # (limit_m+f0_m)/(-g_m) if g_m<-EPS, +inf if |g_m|<=EPS. By definition
    # T_c0 = max(0, min over valid m' of raw_m'); since min(...) <= raw_m
    # for every m, and max(0, .) is monotonic, T_c0 <= max(0, raw_m) for
    # EVERY valid row m -- this holds even when raw_m itself is negative
    # (a row already violated at x=0 in its own loading direction), since
    # both sides pass through the same max(0, .) clamp.
    #   g_m > EPS (upper/loading row binds as T grows): the clamped RHS is
    #     max(limit_m-f0_m, 0) = max(g_m*raw_m, 0) = g_m*max(raw_m, 0)
    #     (g_m>0 commutes with max). Multiplying T_c0 <= max(raw_m,0) by
    #     g_m>0 gives g_m*T_c0 <= g_m*max(raw_m,0) = RHS: upper row holds.
    #     Lower row: LHS = -g_m*T_c0 <= 0 (g_m>0, T_c0>=0) <= RHS (a
    #     max(.,0), always >=0): holds trivially, regardless of whether
    #     this opposite side is already violated.
    #   g_m < -EPS: mirror image. Lower row's clamped RHS =
    #     max(limit_m+f0_m,0) = (-g_m)*max(raw_m,0); T_c0<=max(raw_m,0)
    #     times (-g_m)>0 gives the lower row. Upper row's LHS = g_m*T_c0
    #     <= 0 <= RHS trivially.
    #   |g_m| <= EPS: both rows' T-coefficient is negligible by
    #     construction (that's what the epsilon guards against), so any
    #     residual is O(EPS * T_c0) -- inside ordinary LP solver tolerance,
    #     consistent with the module's design choice to treat sub-EPS load
    #     factors as non-binding rather than exactly zero.
    # So (x=0, T=T_c0) is feasible under every valid row for every sign of
    # g_m, confirming T_c_max >= T_c0 for every c.
    t_c0 = np.full(n_c, np.inf, dtype=np.float64)
    for c in range(n_c):
        valid_col = valid[:, c]
        if not valid_col.any():
            continue
        t_c0[c] = max(0.0, float(np.min(t0_all[:, c][valid_col])))

    order = np.argsort(t_c0, kind="stable")

    solved_T: dict[int, float] = {}
    solved_x: dict[int, tuple[float, ...]] = {}
    lp_solves = 0
    contingencies_skipped = 0
    cur = float("inf")

    for idx in range(n_c):
        c = int(order[idx])
        if t_c0[c] >= cur:
            contingencies_skipped += n_c - idx
            break

        valid_m = np.flatnonzero(valid[:, c])
        n_rows = valid_m.shape[0]
        n_vars = n_p + 1

        a_ub = np.zeros((2 * n_rows, n_vars))
        b_ub = np.zeros(2 * n_rows)
        for i, m in enumerate(valid_m):
            m = int(m)
            d_row = d[m, c, :]
            g_m = g[m, c]
            f0 = base_contingency_flow[m, c]
            lim = limit_broadcast[m, c]
            a_ub[2 * i, :n_p] = d_row
            a_ub[2 * i, n_p] = g_m
            # Clamped at 0: a facility already in violation at x=0 (|f0| >
            # limit) is held to "no worse than base", not "within limit" --
            # the dispatch must not worsen it or create a new binder, but
            # is never required to cure a pre-existing violation the load
            # doesn't create. Without this clamp, a negative RHS here would
            # demand the impossible and the LP would report infeasible for
            # a facility the load never even pushes toward.
            b_ub[2 * i] = max(lim - f0, 0.0)
            a_ub[2 * i + 1, :n_p] = -d_row
            a_ub[2 * i + 1, n_p] = -g_m
            b_ub[2 * i + 1] = max(lim + f0, 0.0)

        bounds = [(-float(w[p]), float(u[p])) for p in range(n_p)]
        bounds.append((0.0, max_load_mw))

        c_obj = np.zeros(n_vars)
        c_obj[-1] = -1.0  # maximize T == minimize -T

        result = linprog(c_obj, A_ub=a_ub, b_ub=b_ub, bounds=bounds, method="highs")
        lp_solves += 1

        if result.status == 0:
            t_c_max = float(result.x[n_p])
            x_c = tuple(float(v) for v in result.x[:n_p])
        elif result.status == 3:
            # Unbounded: no valid m under this contingency has a nonzero
            # load factor, so T has zero coefficient everywhere and any
            # dispatch (in particular the do-nothing one) is a witness.
            t_c_max = float("inf")
            x_c = tuple(0.0 for _ in range(n_p))
        elif result.status == 2:
            # Infeasible: unreachable under the RHS-clamped rows above --
            # (x=0, T=0) always satisfies every row (both clamped RHS
            # values are >= 0 and the LHS is 0 at x=0, T=0), so this branch
            # cannot trigger in practice. Retained as a defensive guard in
            # case of an unexpected solver numerical result; 0.0 is the
            # screening-conservative stand-in if it ever does.
            t_c_max = 0.0
            x_c = tuple(0.0 for _ in range(n_p))
        else:
            raise RuntimeError(
                f"linprog returned unexpected status {result.status} for "
                f"contingency {c}: {result.message}"
            )

        solved_T[c] = t_c_max
        solved_x[c] = x_c
        if t_c_max < cur:
            cur = t_c_max

    capacity_mw = max(0.0, cur)

    if solved_T:
        binding_contingency = min(solved_T, key=lambda c: (solved_T[c], c))
        binding_dispatch = solved_x[binding_contingency]
    else:
        binding_contingency = None
        binding_dispatch = None

    return RecourseResult(
        capacity_mw=capacity_mw,
        binding_contingency_index=binding_contingency,
        binding_dispatch_mw=binding_dispatch,
        lp_solves=lp_solves,
        contingencies_skipped=contingencies_skipped,
    )
