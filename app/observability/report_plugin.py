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
from app.observability.reporter import ReportFiles, generate_report


class ProfessionalReportPlugin:
    """Collects test results and generates a professional HTML report."""

    def __init__(self) -> None:
        self.results: list[dict] = []
        self.flow_meta: dict[str, dict] = {}
        self.flow_steps: dict[str, list[dict]] = {}
        self.flow_errors: dict[str, str] = {}
        self.flow_retries: dict[str, dict[str, str]] = {}
        self.flow_retry_verdicts: dict[str, dict[str, str]] = {}
        self.captures: dict[str, dict] = {}
        self.session_start = time.time()
        self.report_path: Path | None = None
        self.files: ReportFiles | None = None   # what the last generate_report wrote
        self.deselected: list[str] = []         # node ids of the flows a `-m` filter left out

    def pytest_deselected(self, items: list[pytest.Item]) -> None:
        self.deselected += [item.nodeid for item in items if hasattr(item, "flow")]

    def record_flow(self, nodeid: str, flow: FlowDefinition, profile: str) -> None:
        """Suite-level facts the report needs: the file's # title, markers, profile."""
        self.flow_meta[nodeid] = {
            "flow_title": flow.title,
            "flow_markers": list(flow.markers),
            "section_markers": {k: list(v) for k, v in flow.section_markers.items()},
            "flow_expected": list(getattr(flow, "expected", [])),
            "profile": {"name": profile, "label": profile},
        }

    def record_profile_label(self, nodeid: str, label: str) -> None:
        """``mobile · iPhone 13 · chromium · 390x664`` — known once the page exists."""
        if nodeid in self.flow_meta:
            self.flow_meta[nodeid]["profile"]["label"] = label

    def record_error(self, nodeid: str, error: str) -> None:
        self.flow_errors[nodeid] = error

    def record_retries(self, nodeid: str, retried: dict[int, str],
                       verdicts: dict[int, str] | None = None) -> None:
        """Sections (by index) a RERUN_FAILED rerun retried → first attempt's
        error, and its likely cause (diagnosis verdict) when known."""
        self.flow_retries[nodeid] = {str(i): err for i, err in retried.items()}
        self.flow_retry_verdicts[nodeid] = {str(i): v for i, v in (verdicts or {}).items() if v}

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
                "checks": [{**dataclasses.asdict(c), "outcome": c.outcome} for c in s.checks],
                "group": s.group,
                "soft": s.soft,
                "url": s.url,
                "agent": s.agent,
            }
            for s in steps
        ]

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        # One result per test: the call, or a setup that failed (an error) or
        # skipped (a skip marker). A teardown failure turns that result into an
        # error — pytest fails the run for it, so the report must too.
        if report.when == "teardown":
            if report.failed:
                prior = next((r for r in reversed(self.results) if r["nodeid"] == report.nodeid), None)
                if prior is not None:
                    prior["outcome"] = "error"
                    prior["longrepr"] = "\n".join(filter(None, [prior["longrepr"], str(report.longrepr)]))
            return
        if report.when == "call" or (report.when == "setup" and (report.failed or report.skipped)):
            started = getattr(report, "start", None)
            self.results.append(
                {
                    "nodeid":   report.nodeid,
                    "name":     report.nodeid.split("::")[-1],
                    "outcome":  "error" if report.when == "setup" and report.failed else report.outcome,
                    "duration": getattr(report, "duration", 0.0),
                    "started_at": (
                        datetime.datetime.fromtimestamp(started).astimezone().isoformat(
                            timespec="milliseconds"
                        )
                        if started
                        else ""
                    ),
                    "longrepr": str(report.longrepr) if report.failed or report.when == "setup" else "",
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
            r["retried_verdicts"] = self.flow_retry_verdicts.get(nodeid, {})
            r["flow_steps"] = self.flow_steps.get(nodeid, [])
            capture = self.captures.get(nodeid, {})
            r["console"] = capture.get("console", [])
            r["network"] = capture.get("network", [])
            r["capture_dropped"] = capture.get("dropped", {})

        self.files = generate_report(
            results=self.results,
            session_start=self.session_start,
            output_path=settings.report_dir / "report.html",
            environment=settings.environment,
            exit_status=int(exitstatus),
            selection=_selection(session.config, self.deselected),
        )
        # The exit code is the model's verdict (reporter.run_status), so CI,
        # the console and the JSON can never disagree about pass / fail.
        session.exitstatus = self.files.exit_code
        self.report_path = settings.report_dir / "report.html"


def _selection(config: pytest.Config, deselected: list[str]) -> dict | None:
    """The run's ``-m`` filter and the flows it left out; None when there was none."""
    expression = (config.option.markexpr or "").strip()
    return {"markers": expression, "deselected": sorted(deselected)} if expression else None
