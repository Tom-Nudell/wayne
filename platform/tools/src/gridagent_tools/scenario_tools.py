"""Scenario tools: change-table DSL persisted to ``scenarios/{id}.json``.

DSL pattern is borrowed from ``PowerSimData/powersimdata/input/change_table.py:40``
(`scale_plant_capacity`, `add_plant`, `add_branch`, `add_dcline`,
`scale_load`). It's small, declarative, and maps cleanly onto whatever
backend executes the study.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

from .registry import register
from .result import ToolResult


def _scenario_root() -> Path:
    root = Path(os.environ.get("GRIDAGENT_SCENARIO_ROOT", "data_root/scenarios"))
    root.mkdir(parents=True, exist_ok=True)
    return root


_CHANGE_TABLE_KEYS = {
    "scale_plant_capacity",
    "scale_load",
    "add_plant",
    "add_branch",
    "add_dcline",
    "out_of_service_branches",
}


_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "snapshot_id": {"type": "string", "description": "Bundle ID; omit for newest."},
        "change_table": {
            "type": "object",
            "description": "Declarative grid mutations. See PowerSimData change-table DSL.",
            "additionalProperties": True,
        },
    },
    "required": ["name", "change_table"],
    "additionalProperties": False,
}


@register(
    name="create_scenario",
    description="Persist a named scenario (change-table over a snapshot). Returns scenario_id.",
    schema=_SCHEMA,
)
def create_scenario(name: str, change_table: dict, snapshot_id: str | None = None) -> ToolResult:
    unknown = set(change_table or {}) - _CHANGE_TABLE_KEYS
    if unknown:
        raise ValueError(f"Unknown change-table keys: {sorted(unknown)}")
    scenario_id = uuid.uuid4().hex[:12]
    payload = {
        "scenario_id": scenario_id,
        "name": name,
        "snapshot_id": snapshot_id,
        "change_table": change_table or {},
    }
    target = _scenario_root() / f"{scenario_id}.json"
    target.write_text(json.dumps(payload, indent=2, sort_keys=True))
    return ToolResult(
        tool="create_scenario",
        value=payload,
        signal={"scenario_id": scenario_id, "n_changes": len(change_table or {})},
    )


@register(
    name="inspect_scenario",
    description="Read back a scenario by ID.",
    schema={
        "type": "object",
        "properties": {"scenario_id": {"type": "string"}},
        "required": ["scenario_id"],
        "additionalProperties": False,
    },
)
def inspect_scenario(scenario_id: str) -> ToolResult:
    path = _scenario_root() / f"{scenario_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"No scenario {scenario_id!r}")
    payload = json.loads(path.read_text())
    return ToolResult(
        tool="inspect_scenario",
        value=payload,
        signal={"scenario_id": scenario_id, "n_changes": len(payload.get("change_table", {}))},
    )


def load_scenario(scenario_id: str) -> dict:
    """Helper consumed by the study tools."""
    path = _scenario_root() / f"{scenario_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"No scenario {scenario_id!r}")
    return json.loads(path.read_text())
