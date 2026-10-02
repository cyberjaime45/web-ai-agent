"""Web Agent MCP — the standardized interface that exposes the Web Agent's
capabilities to JANUS (the QA Orchestrator Agent) and other MCP clients.

It is an interface, not an agent: the Web Agent is the specialized testing
agent and does all the work. The Web Agent MCP offers a small set of QA
capabilities (list flows, run one, follow it, read its result, cancel it),
validates each request and delegates. It is optional and adds no testing
behaviour of its own: every execution is the same `pytest <flow.md>`
run a developer starts by hand, and every result is read from the report
that run writes.

Kept import-free on purpose: pytest loads ``mcp_server.progress_plugin`` in
the flow subprocess, which must not need the MCP SDK.
"""
