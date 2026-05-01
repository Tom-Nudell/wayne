"""Tool registry shared by orchestrator and MCP transport.

Decorator-based so every tool is one self-contained file. The registry only
holds metadata + the callable; transports adapt it to whatever they need
(JSON-RPC for MCP, in-process call for orchestrator).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .result import ToolResult


@dataclass
class ToolSpec:
    name: str
    description: str
    fn: Callable[..., ToolResult]
    schema: dict[str, Any]  # JSON Schema for parameters


TOOL_REGISTRY: dict[str, ToolSpec] = {}


def register(*, name: str, description: str, schema: dict[str, Any]):
    """Decorator used by tool implementations to advertise themselves."""

    def _decorate(fn: Callable[..., ToolResult]) -> Callable[..., ToolResult]:
        if name in TOOL_REGISTRY:
            raise RuntimeError(f"Tool '{name}' already registered.")
        TOOL_REGISTRY[name] = ToolSpec(name=name, description=description, fn=fn, schema=schema)
        return fn

    return _decorate
