# gridagent-mcp

Thin MCP server that re-exports the `gridagent-tools` registry over JSON-RPC so
external clients (Claude Desktop, Cursor, etc.) can drive the platform.

MCP is a *transport*, not a framework: every tool here is the same callable
the in-process orchestrator uses. We don't add behavior at this layer.

## Resources

- `grid://snapshots/latest/manifest` — manifest of the most recent
  `gridagent-data` snapshot bundle.
- `grid://scenarios/{id}/results` — orchestrator episode results for a scenario.

## Run

```bash
uv run gridagent-mcp                 # stdio transport (default)
uv run gridagent-mcp --transport sse # SSE for browser-side clients
```

Configure in Claude Desktop's `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "gridagent": {
      "command": "uv",
      "args": ["run", "--directory", "/abs/path/to/wayne/platform/mcp", "gridagent-mcp"]
    }
  }
}
```
