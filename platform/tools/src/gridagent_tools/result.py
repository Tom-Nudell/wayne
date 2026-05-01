"""Uniform result envelope for every tool call.

The orchestrator's verifier reads ``signal`` (not ``value``) to decide whether
to advance, retry, replan, or abort. Keeping the two separate means the verifier
logic is reproducible and doesn't depend on parsing free-form result payloads.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class ToolResult(BaseModel):
    """Envelope returned by every tool."""

    tool: str = Field(..., description="Tool name, matches registry key.")
    value: Any = Field(..., description="Tool-specific result payload.")
    signal: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Supervisory signal consumed by the orchestrator's verifier. "
            "Examples: {'converged': true}, {'n_overloads': 7, 'monotone': true}, "
            "{'solver_status': 'OPTIMAL', 'slack_mw': 0.0}."
        ),
    )
    log_path: Path | None = Field(default=None, description="Path to per-call log, if any.")
