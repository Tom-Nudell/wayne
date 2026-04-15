# gridagent-tools

Typed Python tool surface used by both the orchestrator and the MCP server.
Every tool returns `ToolResult(value, signal, log_path)`.

Categories:

- **Data tools** — DuckDB queries over the `gridagent-data` snapshot bundle.
- **Scenario tools** — change-table DSL (inspired by
  `PowerSimData/powersimdata/input/change_table.py:40`).
- **Study tools** — shell out to `gridagent-julia`'s `run.jl`.

The point of this package: there is exactly one Python implementation of each
tool, and both transports (the orchestrator's in-process runtime and the MCP
server) bind to the same functions.
