"""Study tools: shell out to ``gridagent-julia/run.jl``.

Subprocess (rather than PythonCall/JuliaCall) is chosen for crash isolation
and debuggability. Revisit if Julia startup latency becomes a problem;
DaemonMode.jl is the next step.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from .registry import register
from .result import ToolResult


def _julia_root() -> Path:
    return Path(os.environ.get("GRIDAGENT_JULIA_ROOT", Path(__file__).resolve().parents[4] / "gridagent-julia"))


def _run_julia(study: str, scenario: dict) -> dict:
    julia_root = _julia_root()
    run_script = julia_root / "run.jl"
    if not run_script.exists():
        raise RuntimeError(f"Julia entrypoint missing at {run_script}")

    scenario_path = Path(scenario.get("scenario_path") or "/tmp/_gridagent_scenario.json")
    scenario_path.write_text(json.dumps(scenario))

    completed = subprocess.run(
        ["julia", "--project", str(run_script), study, str(scenario_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"Julia study '{study}' failed:\n{completed.stderr}")
    return json.loads(completed.stdout)


_STUDY_SCHEMA = {
    "type": "object",
    "properties": {
        "scenario_id": {"type": "string"},
        "executor": {"type": "string", "enum": ["local_cpu", "madnlp_gpu", "distributed"], "default": "local_cpu"},
    },
    "required": ["scenario_id"],
    "additionalProperties": True,
}


@register(name="run_power_flow", description="Solve AC power flow on a scenario.", schema=_STUDY_SCHEMA)
def run_power_flow(scenario_id: str, executor: str = "local_cpu") -> ToolResult:
    raise NotImplementedError("Wired up once gridagent-data writes a snapshot and gridagent-julia is installed.")


@register(
    name="run_n1_contingency",
    description="LODF-based N-1 contingency screening; returns ranked overload list.",
    schema=_STUDY_SCHEMA,
)
def run_n1_contingency(scenario_id: str, executor: str = "local_cpu") -> ToolResult:
    raise NotImplementedError("Wired up once gridagent-data writes a snapshot and gridagent-julia is installed.")


@register(
    name="run_production_cost",
    description="UC + ED production cost simulation; returns nodal LMPs and dispatch.",
    schema={**_STUDY_SCHEMA, "properties": {**_STUDY_SCHEMA["properties"], "horizon_hours": {"type": "integer", "default": 24}}},
)
def run_production_cost(scenario_id: str, executor: str = "local_cpu", horizon_hours: int = 24) -> ToolResult:
    raise NotImplementedError("Wired up once gridagent-data writes a snapshot and gridagent-julia is installed.")


# Importing this module triggers registration of every tool.
def _ensure_loaded() -> None:
    from . import data_tools, scenario_tools  # noqa: F401  (side-effects only)


_ensure_loaded()
del sys  # avoid leaking
