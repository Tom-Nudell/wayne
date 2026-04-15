"""Scenario tools: change-table DSL persisted to ``scenarios/{id}.json``.

The DSL is inspired by ``PowerSimData/powersimdata/input/change_table.py:40``
(``scale_plant_capacity``, ``add_plant``, ``add_branch``, ``add_dcline``)
because that vocabulary maps cleanly to PowerSystems.jl mutations on a System.
"""

from __future__ import annotations

from .registry import register
from .result import ToolResult

_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "change_table": {
            "type": "object",
            "description": "Declarative grid mutations.",
            "properties": {
                "scale_plant_capacity": {"type": "object"},
                "add_plant": {"type": "array"},
                "add_branch": {"type": "array"},
                "add_dcline": {"type": "array"},
            },
            "additionalProperties": False,
        },
    },
    "required": ["name", "change_table"],
    "additionalProperties": False,
}


@register(
    name="create_scenario",
    description="Persist a named scenario with a change-table relative to the current snapshot.",
    schema=_SCHEMA,
)
def create_scenario(name: str, change_table: dict) -> ToolResult:
    raise NotImplementedError("Wired up once gridagent-data writes a snapshot.")
