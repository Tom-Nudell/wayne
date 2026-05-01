"""MCP server: re-exports every tool in ``gridagent_tools.TOOL_REGISTRY``.

Kept deliberately thin — the registry is the source of truth, this file only
adapts it to the MCP transport. New tools register themselves in
``gridagent-tools`` and appear here automatically.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from gridagent_tools import TOOL_REGISTRY, ToolResult
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Resource, TextContent, Tool


def _bundle_root() -> Path:
    import os

    return Path(os.environ.get("GRIDAGENT_DATA_ROOT", "data_root")) / "bundle"


def _build_server() -> Server:
    server: Server = Server("gridagent")

    @server.list_tools()
    async def _list_tools() -> list[Tool]:
        return [
            Tool(name=spec.name, description=spec.description, inputSchema=spec.schema)
            for spec in TOOL_REGISTRY.values()
        ]

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        spec = TOOL_REGISTRY.get(name)
        if spec is None:
            raise ValueError(f"Unknown tool: {name}")
        result: ToolResult = spec.fn(**(arguments or {}))
        return [TextContent(type="text", text=result.model_dump_json())]

    @server.list_resources()
    async def _list_resources() -> list[Resource]:
        manifest = _bundle_root() / "latest" / "manifest.json"
        resources: list[Resource] = []
        if manifest.exists():
            resources.append(
                Resource(
                    uri="grid://snapshots/latest/manifest",
                    name="Latest snapshot manifest",
                    mimeType="application/json",
                )
            )
        return resources

    @server.read_resource()
    async def _read_resource(uri: str) -> str:
        if uri == "grid://snapshots/latest/manifest":
            return (_bundle_root() / "latest" / "manifest.json").read_text()
        raise ValueError(f"Unknown resource: {uri}")

    return server


async def _run_stdio() -> None:
    server = _build_server()
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def main() -> None:
    parser = argparse.ArgumentParser(prog="gridagent-mcp")
    parser.add_argument("--transport", choices=["stdio"], default="stdio")
    args = parser.parse_args()

    if args.transport == "stdio":
        import anyio

        anyio.run(_run_stdio)
    else:  # pragma: no cover  -- placeholder for SSE
        raise SystemExit(f"Transport {args.transport!r} not yet implemented.")


if __name__ == "__main__":
    main()
