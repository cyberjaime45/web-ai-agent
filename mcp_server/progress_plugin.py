"""pytest plugin the adapter loads into a flow run (``-p mcp_server.progress_plugin``).

Writes how many flows pytest collected and how many have finished to the file
named by ``WEB_AGENT_MCP_PROGRESS_FILE``, so ``get_status`` reports progress
the test runner itself counted. Without that variable it does nothing.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

_state = {"total": 0, "completed": 0, "current": None}


def _write() -> None:
    target = os.environ.get("WEB_AGENT_MCP_PROGRESS_FILE")
    if not target:
        return
    path = Path(target)
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(_state), encoding="utf-8")
        os.replace(tmp, path)          # atomic: a reader never sees half a file
    except OSError:
        pass                           # progress is best effort; the run goes on


def pytest_collection_finish(session) -> None:
    _state["total"] = len(session.items)
    _write()


def pytest_runtest_logstart(nodeid, location) -> None:
    _state["current"] = nodeid
    _write()


def pytest_runtest_logreport(report) -> None:
    # One count per test: its call, or a setup that failed or skipped.
    if report.when == "call" or (report.when == "setup" and report.outcome != "passed"):
        _state["completed"] += 1
        _write()
