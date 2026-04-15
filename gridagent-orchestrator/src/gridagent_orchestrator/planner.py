"""LLM-driven tool-call proposer.

Anthropic Claude by default; provider-agnostic via a tiny ``LLM`` protocol so
we can swap in OpenAI / local models without touching the orchestrator loop.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Protocol

from gridagent_tools import TOOL_REGISTRY


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]


class LLM(Protocol):
    def propose(self, prompt: str, tools: list[dict[str, Any]]) -> ToolCall | None: ...


class AnthropicLLM:
    """Default planner backed by Anthropic Claude."""

    def __init__(self, model: str = "claude-sonnet-4-6", api_key: str | None = None):
        from anthropic import Anthropic

        self._client = Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))
        self._model = model

    def propose(self, prompt: str, tools: list[dict[str, Any]]) -> ToolCall | None:
        message = self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            tools=tools,
            messages=[{"role": "user", "content": prompt}],
        )
        for block in message.content:
            if getattr(block, "type", None) == "tool_use":
                return ToolCall(name=block.name, arguments=dict(block.input))
        return None  # Model responded with text only -> end of episode.


def tools_for_llm() -> list[dict[str, Any]]:
    """Adapt the in-process registry to the Anthropic Messages tool format."""
    return [
        {"name": spec.name, "description": spec.description, "input_schema": spec.schema}
        for spec in TOOL_REGISTRY.values()
    ]


def parse_tool_call(raw: str) -> ToolCall:
    """Helper for replay / non-LLM testing."""
    payload = json.loads(raw)
    return ToolCall(name=payload["name"], arguments=payload.get("arguments", {}))
