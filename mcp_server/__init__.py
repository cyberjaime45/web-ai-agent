"""MCP adapter for the Web Agent — an additional, optional interface.

Exposes a small set of QA capabilities (list flows, run one, follow it, read
its result, cancel it) to MCP clients such as Janus (the QA orchestrator). It adds no
testing behaviour of its own: every execution is the same `pytest <flow.md>`
run a developer starts by hand, and every result is read from the report
that run writes.

Kept import-free on purpose: pytest loads ``mcp_server.progress_plugin`` in
the flow subprocess, which must not need the MCP SDK.
"""
