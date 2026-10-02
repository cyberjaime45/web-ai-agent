"""Outcome and result of an execution, read from the report its run wrote.

Nothing here parses console output. ``summary.json`` and ``test_cases.json``
are the Web Agent's own structured report (docs/REPORTS.md); this module
projects them onto the MCP contract and decides the one thing the report does
not say by itself: whether the *execution* worked.
"""

from __future__ import annotations

import json
from collections import deque
from pathlib import Path
from typing import Any

from mcp_server.models import (
    CaseOutcome,
    ErrorCode,
    ErrorInfo,
    ExecutionState,
    Failure,
    FailureEvidence,
    Finding,
    ReportFiles,
    Totals,
)

_COMPLETED = frozenset({"passed", "passed_with_warnings", "failed"})
_MAX_TEXT = 2000        # a message is evidence, not a log: the full text stays in the report
_MAX_TESTS = 500
_MAX_WARNINGS = 50


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def tail(path: Path, lines: int = 40) -> list[str]:
    """The last lines of a log file, for an error's debugging details."""
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            return [line.rstrip("\n") for line in deque(fh, maxlen=lines)]
    except OSError:
        return []


def _clip(text: Any) -> str:
    text = "" if text is None else str(text)
    return text if len(text) <= _MAX_TEXT else text[:_MAX_TEXT] + " …[truncated]"


# ── Did the execution work? ──────────────────────────────────────────────────

def judge(report_dir: Path, console_log: Path, exit_code: int | None, *,
          timed_out: bool, cancelled: bool, timeout_seconds: float) -> tuple[ExecutionState, ErrorInfo | None]:
    """The final state of a finished run.

    COMPLETED means the Web Agent ran the flow and reported on it — failed
    tests included. Everything else means it did not get that far.
    """
    details = {"exit_code": exit_code, "console_log": str(console_log)}
    if timed_out:
        return ExecutionState.TIMED_OUT, ErrorInfo(
            code=ErrorCode.EXECUTION_TIMEOUT,
            message=f"The execution was stopped after {timeout_seconds:g} seconds.", details=details)
    if cancelled:
        return ExecutionState.CANCELLED, None

    summary = read_json(report_dir / "summary.json")
    if summary is None:
        return ExecutionState.FAILED, ErrorInfo(
            code=ErrorCode.WEB_AGENT_ERROR,
            message=f"The Web Agent exited with code {exit_code} without writing a report.",
            details={**details, "console_tail": tail(console_log)})

    status = summary.get("status")
    if status not in _COMPLETED:
        return ExecutionState.FAILED, ErrorInfo(
            code=ErrorCode.WEB_AGENT_ERROR,
            message=f"The Web Agent reported the run as {status!r}: it did not complete normally.",
            details={**details, "console_tail": tail(console_log)})

    tests = (read_json(report_dir / "test_cases.json") or {}).get("tests") or []
    broken = [t for t in tests if _kind(t) == "execution_error"]
    if broken and not any(t.get("steps") for t in tests):
        # Nothing ran a single step: the flow never started (browser, setup).
        message = _clip(((broken[0].get("error") or {}).get("message")) or "no step was executed")
        return ExecutionState.FAILED, ErrorInfo(
            code=ErrorCode.WEB_AGENT_ERROR,
            message=f"The flow could not start: {message}",
            details={**details, "console_tail": tail(console_log)})
    return ExecutionState.COMPLETED, None


# ── Result ───────────────────────────────────────────────────────────────────

def _failed_leaf(steps: list[dict]) -> dict | None:
    """The step where a test failed: the last failed step that is not a group
    holding another failed step."""
    failed = [s for s in steps if s.get("status") == "failed"]
    parents = {s.get("parent") for s in failed}
    leaves = [s for s in failed if s.get("id") not in parents]
    return leaves[-1] if leaves else None


def _kind(test: dict) -> str | None:
    if test.get("status") not in ("failed", "error"):
        return None
    if test.get("status") == "failed" and _failed_leaf(test.get("steps") or []):
        return "test_failure"
    return "execution_error"


def _absolute(report_dir: Path, rel: str | None) -> str | None:
    return str((report_dir / rel).resolve()) if rel else None


def _evidence(report_dir: Path, test: dict, step: dict | None) -> FailureEvidence | None:
    ev = (step or {}).get("evidence") or {}
    artifacts = test.get("artifacts") or {}
    shots = [p for p in (ev.get("screenshots") or {}).values() if p] \
        or [s.get("path") for s in artifacts.get("screenshots") or [] if s.get("path")]
    trace = ev.get("trace") or artifacts.get("trace")
    if not (ev or shots or trace):
        return None
    return FailureEvidence(
        url=ev.get("url") or "", title=ev.get("title") or "",
        screenshots=[p for rel in shots if (p := _absolute(report_dir, rel))],
        trace=_absolute(report_dir, trace),
        layers={str(k): str(v) for k, v in (ev.get("layers") or {}).items()},
    )


def _failure(report_dir: Path, test: dict) -> Failure:
    step = _failed_leaf(test.get("steps") or [])
    error = test.get("error") or {}
    diagnosis = ((step or {}).get("evidence") or {}).get("diagnosis") or {}
    return Failure(
        test=test.get("name") or "", file=test.get("file") or "",
        kind=_kind(test) or "execution_error",
        step=(step or {}).get("name"),
        message=_clip((step or {}).get("error") or error.get("message")),
        likely_cause={k: diagnosis[k] for k in ("verdict", "summary") if diagnosis.get(k)} or None,
        evidence=_evidence(report_dir, test, step),
    )


def build_result(report_dir: Path) -> dict[str, Any] | None:
    """What the report says, as contract fields — or None when there is no report."""
    summary = read_json(report_dir / "summary.json")
    if summary is None:
        return None
    tests = (read_json(report_dir / "test_cases.json") or {}).get("tests") or []
    totals = summary.get("totals") or {}
    environment = summary.get("environment") or {}

    warnings = [
        Finding(test=t.get("name") or "", check=w.get("check") or "",
                detail=_clip(w.get("detail")), severity=w.get("severity") or "")
        for t in tests for w in t.get("warnings") or []
    ]
    existing = {name: path for name in ("report.html", "summary.json", "test_cases.json", "junit.xml")
                if (path := report_dir / name).is_file()}
    return {
        "verdict": summary.get("status"),
        "summary": Totals(**{k: totals[k] for k in Totals.model_fields if k in totals}),
        "tests": [
            CaseOutcome(name=t.get("name") or "", file=t.get("file") or "", status=t.get("status") or "",
                        profile=(t.get("profile") or {}).get("name") or "",
                        duration_ms=t.get("duration_ms") or 0.0, retried=bool(t.get("retries")))
            for t in tests[:_MAX_TESTS]
        ],
        "failures": [_failure(report_dir, t) for t in tests if _kind(t)],
        "warnings": warnings[:_MAX_WARNINGS],
        "healed_steps": sum(len(t.get("healings") or []) for t in tests),
        "report": ReportFiles(
            html=str(existing["report.html"]) if "report.html" in existing else None,
            summary_json=str(existing["summary.json"]) if "summary.json" in existing else None,
            test_cases_json=str(existing["test_cases.json"]) if "test_cases.json" in existing else None,
            junit=str(existing["junit.xml"]) if "junit.xml" in existing else None,
        ),
        "run": {
            "run_id": summary.get("run_id"),
            "created_at": summary.get("created_at"),
            "browser": environment.get("browser"),
            "headless": environment.get("headless"),
            "web_agent_version": environment.get("framework"),
            "playwright": environment.get("playwright"),
            "warnings_total": len(warnings),
        },
    }
