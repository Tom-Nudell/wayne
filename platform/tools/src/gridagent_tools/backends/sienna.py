"""Sienna backend: subprocess / container shim.

Calls into the NREL Sienna stack (`PowerSystems.jl` + `PowerFlows.jl` +
`PowerNetworkMatrices.jl` + `PowerSimulations.jl`) via the Julia entrypoint
at ``gridagent-julia/run.jl``. Two execution modes:

* **subprocess** (default) — `julia --project gridagent-julia/run.jl ...`.
  Requires Julia installed locally; expected for dev.
* **container** — `docker run --rm gridagent/sienna:latest ...`. Expected
  for CI and production. Toggle with env var ``GRIDAGENT_SIENNA_RUNNER``.

The backend is intentionally a thin shim — no Julia code lives here.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from ..snapshot import Snapshot
from .protocol import BackendUnavailable, register_backend

_DEFAULT_JULIA_ROOT = Path(__file__).resolve().parents[5] / "gridagent-julia"


def _runner_command() -> list[str]:
    runner = os.environ.get("GRIDAGENT_SIENNA_RUNNER", "subprocess")
    if runner == "subprocess":
        if shutil.which("julia") is None:
            raise BackendUnavailable(
                "Sienna backend requested but `julia` is not on PATH. "
                "Install Julia 1.10+ or set GRIDAGENT_SIENNA_RUNNER=container."
            )
        julia_root = Path(os.environ.get("GRIDAGENT_JULIA_ROOT", _DEFAULT_JULIA_ROOT))
        return ["julia", f"--project={julia_root}", str(julia_root / "run.jl")]
    if runner == "container":
        image = os.environ.get("GRIDAGENT_SIENNA_IMAGE", "gridagent/sienna:latest")
        if shutil.which("docker") is None:
            raise BackendUnavailable("docker not on PATH; cannot run Sienna container.")
        return ["docker", "run", "--rm", "-i", image]
    raise BackendUnavailable(f"Unknown GRIDAGENT_SIENNA_RUNNER={runner!r}")


def _invoke(study: str, snapshot: Snapshot, scenario: dict[str, Any]) -> dict[str, Any]:
    cmd = _runner_command() + [study, str(snapshot.root), json.dumps(scenario)]
    completed = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"Sienna `{study}` failed (rc={completed.returncode}):\n{completed.stderr}")
    return json.loads(completed.stdout)


class SiennaBackend:
    name = "sienna"

    def power_flow(self, snapshot: Snapshot, scenario: dict[str, Any]) -> dict[str, Any]:
        return _invoke("power_flow", snapshot, scenario)

    def n1_contingency(
        self, snapshot: Snapshot, scenario: dict[str, Any], *, monitored: list[str] | None = None
    ) -> dict[str, Any]:
        return _invoke("n1_contingency", snapshot, dict(scenario, monitored=monitored or []))

    def production_cost(
        self, snapshot: Snapshot, scenario: dict[str, Any], *, horizon_hours: int = 24
    ) -> dict[str, Any]:
        return _invoke("production_cost", snapshot, dict(scenario, horizon_hours=horizon_hours))


register_backend(SiennaBackend())
