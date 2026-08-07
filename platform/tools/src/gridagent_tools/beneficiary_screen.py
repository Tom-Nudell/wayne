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
