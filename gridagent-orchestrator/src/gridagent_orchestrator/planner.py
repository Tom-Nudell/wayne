"""LLM-driven tool-call proposer.

Local-first: defaults to an OpenAI-compatible endpoint served by Ollama
(``http://localhost:11434/v1``) running an open-weight model from the Gemma
family. The OpenAI Python SDK is the transport — same API works against
vLLM and llama.cpp without code changes.

A small ``LLM`` Protocol keeps the orchestrator loop provider-agnostic so a
hosted model can be swapped in for evaluation without touching the agent.
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


class LocalOpenAILLM:
    """Default planner: any OpenAI-compatible local server.

    Tested against Ollama 0.4+ which gained tool-calling support for the
    Gemma family. Override ``base_url`` / ``model`` to point at vLLM or
    llama.cpp's ``server`` binary instead.
    """

    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
    ):
        from openai import OpenAI

        self._client = OpenAI(
            base_url=base_url or os.environ.get("GRIDAGENT_LLM_BASE_URL", "http://localhost:11434/v1"),
            # Local servers ignore the key but the SDK requires a non-empty value.
            api_key=api_key or os.environ.get("GRIDAGENT_LLM_API_KEY", "ollama"),
        )
        self._model = model or os.environ.get("GRIDAGENT_LLM_MODEL", "gemma3:27b")

    def propose(self, prompt: str, tools: list[dict[str, Any]]) -> ToolCall | None:
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            tools=tools,
            tool_choice="auto",
        )
        choice = response.choices[0]
        calls = getattr(choice.message, "tool_calls", None) or []
        if not calls:
            return None  # Model responded with text only -> end of episode.
        first = calls[0]
        arguments = json.loads(first.function.arguments or "{}")
        return ToolCall(name=first.function.name, arguments=arguments)


def tools_for_llm() -> list[dict[str, Any]]:
    """Adapt the in-process registry to the OpenAI tool-call format."""
    return [
        {
            "type": "function",
            "function": {
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.schema,
            },
        }
        for spec in TOOL_REGISTRY.values()
    ]


def parse_tool_call(raw: str) -> ToolCall:
    """Helper for replay / non-LLM testing."""
    payload = json.loads(raw)
    return ToolCall(name=payload["name"], arguments=payload.get("arguments", {}))
