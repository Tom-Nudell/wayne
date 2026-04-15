"""Backend protocol + dispatcher.

Every backend implements the same three actions. The dispatcher is keyed by
short string (``"pandapower"``, ``"sienna"``, ...) so the agent never has
to reason about runtime choice — it passes the string through verbatim.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from ..snapshot import Snapshot


class BackendUnavailable(RuntimeError):
    """Raised when a backend is requested but its dependencies aren't installed."""


@runtime_checkable
class Backend(Protocol):
    name: str

    def power_flow(self, snapshot: Snapshot, scenario: dict[str, Any]) -> dict[str, Any]:
        """Solve AC power flow. Returns ``{"value": {...}, "signal": {...}}``."""

    def n1_contingency(
        self, snapshot: Snapshot, scenario: dict[str, Any], *, monitored: list[str] | None = None
    ) -> dict[str, Any]:
        """LODF-based N-1 contingency screen. Returns ranked overload list."""

    def production_cost(
        self, snapshot: Snapshot, scenario: dict[str, Any], *, horizon_hours: int = 24
    ) -> dict[str, Any]:
        """UC + ED production cost simulation. Returns LMPs and dispatch."""


_REGISTRY: dict[str, Backend] = {}


def register_backend(backend: Backend) -> None:
    if backend.name in _REGISTRY:
        raise RuntimeError(f"Backend {backend.name!r} already registered")
    _REGISTRY[backend.name] = backend


def get_backend(name: str) -> Backend:
    backend = _REGISTRY.get(name)
    if backend is None:
        available = ", ".join(sorted(_REGISTRY)) or "(none)"
        raise BackendUnavailable(
            f"Backend {name!r} not registered. Available: {available}."
        )
    return backend
