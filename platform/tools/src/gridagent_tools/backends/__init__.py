"""Pluggable execution backends.

The agent surface is **grid actions over a snapshot** — `run_power_flow`,
`run_n1_contingency`, `run_production_cost`. Backends are plugins that
implement those actions against the canonical Snapshot:

  * ``pandapower`` — in-process Python (BSD-3); default while bringing things up.
  * ``sienna``     — NREL Sienna stack via subprocess or container; canonical
                     once Julia is available locally.
  * future         — PowerWorld bridge, custom GPU LODF, etc.

Decoupling means the platform is no longer Sienna-anchored: Sienna is one
backend among several, and the agent never picks one — it asks for an
``executor`` string and the dispatcher does the rest.
"""

from __future__ import annotations

from .protocol import Backend, BackendUnavailable, get_backend, register_backend

# Eager import of the in-process backend so it's always available; the Sienna
# shim registers itself but doesn't import Julia at module load.
from . import pandapower as _pandapower  # noqa: F401
from . import sienna as _sienna  # noqa: F401

__all__ = ["Backend", "BackendUnavailable", "get_backend", "register_backend"]
