"""pytest plugin that collects what the HTML report needs, then writes it.

conftest.py registers one instance per session. ``FlowItem`` feeds it as a
flow runs (``record_flow``, ``record_steps``, ``record_capture``…); pytest
feeds it every test outcome (``pytest_runtest_logreport``, Python tests
included); at session end it hands everything to ``reporter.generate_report``.
It only gathers and serialises — no browser, no layout decisions.
"""

from __future__ import annotations

import dataclasses
import datetime
import time
from pathlib import Path

import pytest

from app.config.settings import settings
from app.flow.parser import FlowDefinition
from app.observability.reporter import generate_report


class ProfessionalReportPlugin:
    """Collects test results and generates a professional HTML report."""

    def __init__(self) -> None:
        self.results: list[dict] = []
        self.flow_meta: dict[str, dict] = {}
        self.flow_steps: dict[str, list[dict]] = {}
        self.flow_errors: dict[str, str] = {}
        self.flow_retries: dict[str, dict[str, str]] = {}
        self.captures: dict[str, dict] = {}
        self.session_start = time.time()
        self.report_path: Path | None = None
        self.json_path: Path | None = None

    def record_flow(self, nodeid: str, flow: FlowDefinition, profile: str) -> None:
        """Suite-level facts the report needs: the file's # title, markers, profile."""
        self.flow_meta[nodeid] = {
            "flow_title": flow.title,
            "flow_markers": list(flow.markers),
            "section_markers": {k: list(v) for k, v in flow.section_markers.items()},
            "profile": {"name": profile, "label": profile},
        }

    def record_profile_label(self, nodeid: str, label: str) -> None:
        """``mobile · iPhone 13 · chromium · 390x664`` — known once the page exists."""
        if nodeid in self.flow_meta:
            self.flow_meta[nodeid]["profile"]["label"] = label

    def record_error(self, nodeid: str, error: str) -> None:
        self.flow_errors[nodeid] = error

    def record_retries(self, nodeid: str, retried: dict[int, str]) -> None:
        """Sections (by index) a RERUN_FAILED rerun retried → first attempt's error."""
        self.flow_retries[nodeid] = {str(i): err for i, err in retried.items()}

    def record_capture(self, nodeid: str, console: list[dict],
                       network: list[dict], dropped: dict | None = None) -> None:
        """Store console/network entries captured by the PageRecorder."""
        self.captures[nodeid] = {"console": console, "network": network,
                                 "dropped": dropped or {}}

    def record_steps(self, nodeid: str, steps: list) -> None:
        """Serialize FlowResult.steps for the report (both pass and fail)."""
        self.flow_steps[nodeid] = [
            {
                "name": s.action.raw,
                "action": s.action.type.value,
                "passed": s.success,
                "skipped": getattr(s, "skipped", False),
                "msg": "" if s.success else s.message,
                "duration": s.duration,
                "sub_flow": s.sub_flow,
                "section": s.action.section or "",
                "screenshot": s.screenshot_path or "",
                "layer": s.layer_used,
                "ts_start": s.started_at,
                "ts_end": s.ended_at,
                "evidence": dataclasses.asdict(s.evidence) if s.evidence else None,
                "checks": [dataclasses.asdict(c) for c in s.checks],
                "group": s.group,
                "url": s.url,
                "agent": s.agent,
            }
            for s in steps
        ]

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        if report.when == "call" or (report.when == "setup" and report.failed):
            started = getattr(report, "start", None)
            self.results.append(
                {
                    "nodeid":   report.nodeid,
                    "name":     report.nodeid.split("::")[-1],
                    "outcome":  report.outcome,
                    "duration": getattr(report, "duration", 0.0),
                    "started_at": (
                        datetime.datetime.fromtimestamp(started).astimezone().isoformat(
                            timespec="milliseconds"
                        )
                        if started
                        else ""
                    ),
                    "longrepr": str(report.longrepr) if report.failed else "",
                }
            )

    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int) -> None:
        # Nothing ran (collect-only, everything deselected): keep the previous
        # report instead of overwriting it with an empty one.
        if session.config.option.collectonly or not self.results:
            return
        for r in self.results:
            nodeid = r["nodeid"]
            r.update(self.flow_meta.get(nodeid, {}))
            r["error"] = self.flow_errors.get(nodeid, "")
            r["retried"] = self.flow_retries.get(nodeid, {})
            r["flow_steps"] = self.flow_steps.get(nodeid, [])
            capture = self.captures.get(nodeid, {})
            r["console"] = capture.get("console", [])
            r["network"] = capture.get("network", [])
            r["capture_dropped"] = capture.get("dropped", {})

        self.json_path = generate_report(
            results=self.results,
            session_start=self.session_start,
            output_path=settings.report_dir / "report.html",
            environment=settings.environment,
        )
        self.report_path = settings.report_dir / "report.html"
