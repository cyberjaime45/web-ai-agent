"""
Shared pytest fixtures and hooks for the Web AI Agent runtime.

Auto-discovery: every .md file pytest traverses (testpaths, or any path given
on the command line) is collected as a flow by pytest_collect_file — no
test_*.py files needed. tests/<app>/flows/ is the convention, not a rule.
"""

from __future__ import annotations

import dataclasses
import datetime
import logging
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

import pytest
from playwright.sync_api import sync_playwright

from app.flow.parser import FlowParseError, FlowDefinition, parse_flow_file, parse_flow_markdown
from app.execution.engine import FlowRunner
from app.layers.providers import ConfigError, get_provider
from app.schemas.actions import Evidence, FlowResult
from app.browser import profiles
from app.browser.session import create_browser
from app.config.settings import settings
from app.observability.console import (
    FLOW_FILE_PROP, FLOW_NAME_PROP, HEALINGS_PROP,
    execution_summary, install_console_reporter,
)
from app.observability.evidence import annotate_error_elements, slugify, stop_trace
from app.observability.recorder import PageRecorder
from app.observability.reporter import generate_report
from app.utils.banner import show_banner
from app.utils.build import get_build_name

_ENV = settings.environment   # .env is loaded by app.config.settings

# ── Configure logging ───────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# ── Report paths ───────────────────────────────────────────────

_REPORT_DIR   = settings.report_dir
_IMAGES_DIR   = settings.images_dir
_REPORT_PATH  = _REPORT_DIR / "report.html"


# ── Professional report plugin ──────────────────────────────────


class ProfessionalReportPlugin:
    """Collects test results and generates a professional HTML report."""

    def __init__(self) -> None:
        self.results: list[dict] = []
        self.flow_meta: dict[str, dict] = {}
        self.flow_steps: dict[str, list[dict]] = {}
        self.flow_errors: dict[str, str] = {}
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
            r["flow_steps"] = self.flow_steps.get(nodeid, [])
            capture = self.captures.get(nodeid, {})
            r["console"] = capture.get("console", [])
            r["network"] = capture.get("network", [])
            r["capture_dropped"] = capture.get("dropped", {})

        self.json_path = generate_report(
            results=self.results,
            session_start=self.session_start,
            output_path=_REPORT_PATH,
            environment=_ENV,
        )
        self.report_path = _REPORT_PATH


# ── CLI options ─────────────────────────────────────────────────


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--flow",
        default=None,
        metavar="MARKDOWN",
        help="Run a flow defined as raw Markdown text (passed inline).",
    )
    parser.addoption(
        "--flow_file",
        default=None,
        metavar="PATH",
        help="Run a flow from an explicit .md file path.",
    )
    parser.addoption(
        "--profile",
        default=None,
        metavar="NAMES",
        help="Device profile(s) to run every flow under, comma-separated "
             f"({', '.join(profiles.BUILTIN)}). Overrides the flows' own `profiles:` config.",
    )


# ── Plugin registration ────────────────────────────────────────

def pytest_configure(config: pytest.Config) -> None:
    plugin = ProfessionalReportPlugin()
    config.pluginmanager.register(plugin, "professional_report")


class _SessionBrowser:
    """One Playwright driver + browser for the whole session (local mode).

    Each flow gets a fresh BrowserContext — that is where isolation (cookies,
    storage, viewport) comes from; the browser process itself is the expensive
    part (~1.5-3 s per launch) and is shared. Under RUNNING_MODE=lambda every
    flow still opens its own grid session, because the LambdaTest dashboard
    names and grades tests per session.
    """

    def __init__(self) -> None:
        self._pw = None
        self._browser = None
        self._ctx_opts: dict = {}

    @contextmanager
    def page(self, test_name: str, profile: str = profiles.DESKTOP):
        """A fresh page in a context shaped by *profile* (desktop / mobile)."""
        if settings.remote:
            pw = sync_playwright().start()
            try:
                browser, opts = create_browser(pw, test_name=test_name)
                try:
                    yield from self._new_page(browser, profiles.context_options(profile, opts, pw.devices))
                finally:
                    browser.close()
            finally:
                pw.stop()
            return
        if self._browser is None or not self._browser.is_connected():
            self._pw = self._pw or sync_playwright().start()
            self._browser, self._ctx_opts = create_browser(self._pw, test_name=test_name)
        yield from self._new_page(
            self._browser, profiles.context_options(profile, self._ctx_opts, self._pw.devices))

    @staticmethod
    def _new_page(browser, opts: dict):
        ctx = browser.new_context(**opts)
        # Tracing records for every flow; whether it is kept is decided at
        # flow end (_keep_trace). Closing the context discards an unstopped trace.
        if settings.trace_on_failure:
            ctx.tracing.start(screenshots=True, snapshots=True)
        try:
            yield ctx.new_page()
        finally:
            ctx.close()

    def close(self) -> None:
        if self._browser is not None:
            self._browser.close()
        if self._pw is not None:
            self._pw.stop()
        self._browser = self._pw = None


def pytest_sessionstart(session: pytest.Session) -> None:
    show_banner()
    _IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    session.config._webagent_browser = _SessionBrowser()
    # One LLM client for the whole session (L3 is optional). Partial config is
    # a startup error, not a per-test one.
    try:
        session.config._webagent_provider = get_provider()
    except ConfigError as exc:
        raise pytest.UsageError(
            f"{exc} — set them alongside AI_PROVIDER, or leave AI_PROVIDER empty to disable L3"
        ) from exc


@pytest.hookimpl(tryfirst=True)
def pytest_collection(session: pytest.Session) -> None:
    # By collection time the standard TerminalReporter exists regardless of
    # plugin registration order — the earliest safe moment to adopt it.
    install_console_reporter(session.config)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    browser = getattr(session.config, "_webagent_browser", None)
    if browser is not None:
        browser.close()


def pytest_terminal_summary(terminalreporter, exitstatus, config) -> None:
    """Execution summary + report path, after the failure sections."""
    plugin = config.pluginmanager.get_plugin("professional_report")
    started = plugin.session_start if plugin else None
    duration = time.time() - started if started else 0.0
    lines = execution_summary(
        terminalreporter.stats, duration, settings.run_label(), get_build_name()
    )
    if lines:
        terminalreporter.section("Execution summary")
        for line in lines:
            terminalreporter.write_line(line)
    if plugin and plugin.report_path:
        terminalreporter.section("Report")
        terminalreporter.write_line(f"HTML : {plugin.report_path}")
        terminalreporter.write_line(f"JSON : {plugin.json_path}")


# ── Inline / explicit-path flow injection ─────────────────────
#
# Handles --flow "<markdown>" and --flow_file path/to/file.md.
# Items are appended to the collected list so they go through the
# same execution pipeline as file-discovered flows — no duplicate logic.


def pytest_collection_modifyitems(
    session: pytest.Session,
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    inline_md       = config.getoption("--flow",      default=None)
    flow_file_path  = config.getoption("--flow_file", default=None)

    if inline_md and flow_file_path:
        pytest.exit(
            "ERROR: --flow and --flow_file are mutually exclusive; use only one.",
            returncode=4,
        )

    if inline_md is not None:
        inline_md = inline_md.strip()
        if not inline_md:
            pytest.exit("ERROR: --flow content is empty.", returncode=4)
        flow = parse_flow_markdown(inline_md)
        if not flow.actions:
            pytest.exit(
                "ERROR: --flow content parsed to zero actions. "
                "Check the Markdown format (needs a ## Steps section).",
                returncode=4,
            )
        items.extend(_flow_items(session, config, flow))

    elif flow_file_path is not None:
        path = Path(flow_file_path)
        if not path.exists():
            pytest.exit(f"ERROR: --flow_file path not found: {path}", returncode=4)
        if path.suffix.lower() != ".md":
            pytest.exit(
                f"ERROR: --flow_file must be a .md file, got '{path.suffix}'.",
                returncode=4,
            )
        flow = parse_flow_file(path)
        if not flow.actions:
            pytest.exit(
                f"ERROR: {path} parsed to zero actions. "
                "Check the Markdown format (needs a ## Steps section).",
                returncode=4,
            )
        items.extend(_flow_items(session, config, flow))


# ── Device profiles: one FlowItem per profile the flow runs under ────────────


def _profiles_for(config: pytest.Config, flow: FlowDefinition) -> list[str]:
    """``--profile`` wins, then the flow's ``## Config`` line, then PROFILE."""
    spec = config.getoption("--profile", default=None)
    if spec:
        names = profiles.parse_names(spec)
    else:
        names = flow.profiles or profiles.parse_names(settings.profile)
    try:
        return profiles.validate(names) or [profiles.DESKTOP]
    except ValueError as exc:
        raise pytest.UsageError(str(exc)) from exc


def _flow_items(parent, config: pytest.Config, flow: FlowDefinition) -> list[FlowItem]:
    """The desktop item keeps the flow's plain name; others are ``name[profile]``."""
    return [
        FlowItem.from_parent(
            parent, flow=flow, profile=p,
            name=flow.name if p == profiles.DESKTOP else f"{flow.name}[{p}]",
        )
        for p in _profiles_for(config, flow)
    ]


def _keep_trace(page, result: FlowResult | None, flow_name: str, profile: str) -> None:
    """Stop the context's trace; when the flow failed, keep it on the failure
    site — the last failed (non-skipped) step."""
    if not settings.trace_on_failure:
        return
    failed = [] if result is None else [s for s in result.steps if not s.success and not s.skipped]
    path = stop_trace(page, keep=result is None or bool(failed),
                      traces_dir=settings.traces_dir, stem=f"{slugify(flow_name)}__{profile}")
    if path and failed:
        if failed[-1].evidence is None:
            failed[-1].evidence = Evidence()
        failed[-1].evidence.trace = path


# ── .md flow auto-discovery ────────────────────────────────────
#
# pytest_collect_file is called for every file pytest traverses. Every
# .md file becomes a FlowFile node, which yields one FlowItem per flow
# file. Where the file lives does not matter: plain `pytest` walks
# `testpaths` (tests/), and `pytest path/to/any.md` collects that file
# from anywhere. FlowItem.runtest() drives the session browser, so no
# test_*.py file is needed.


def _set_lambdatest_status(page, success: bool, error: str = "") -> None:
    """Report test pass/fail to LambdaTest dashboard (no-op for local runs)."""
    if not settings.remote:
        return
    try:
        import json as _json
        status = "passed" if success else "failed"
        remark = "" if success else (error or "Test failed")[:255]
        action_payload = _json.dumps({
            "action": "setTestStatus",
            "arguments": {"status": status, "remark": remark},
        })
        page.evaluate("_ => {}", f"lambdatest_action: {action_payload}")
    except Exception as exc:
        logging.getLogger(__name__).debug("LambdaTest status not sent: %s", exc)


class _FlowFailure(Exception):
    """Raised by FlowItem.runtest() to carry the FlowResult for reporting."""

    def __init__(self, result: FlowResult) -> None:
        self.result = result
        super().__init__(result.error)


class FlowItem(pytest.Item):
    """A pytest test item backed by a .md flow file."""

    def __init__(self, name: str, parent, flow: FlowDefinition,
                 profile: str = profiles.DESKTOP) -> None:
        super().__init__(name, parent)
        self.flow = flow
        self.profile = profile
        self._artifacts = _IMAGES_DIR   # created once in pytest_sessionstart

    def runtest(self) -> None:
        # Console reporting reads these off the TestReport. Inline/--flow_file
        # items are parented to the session (path = rootdir), so no file part.
        file_part = self.path.name if self.path.is_file() else ""
        self.user_properties.append((FLOW_FILE_PROP, file_part))
        self.user_properties.append((FLOW_NAME_PROP, self.name))   # includes [profile]
        plugin = self.config.pluginmanager.get_plugin("professional_report")
        if plugin:
            plugin.record_flow(self.nodeid, self.flow, self.profile)
        result: FlowResult | None = None

        with self.config._webagent_browser.page(self.flow.name, self.profile) as page:
            page.set_default_timeout(self.flow.timeout)
            if plugin:
                plugin.record_profile_label(
                    self.nodeid, profiles.describe(self.profile, page.viewport_size))
            recorder = PageRecorder()   # console errors/warnings + network, for the report
            recorder.attach(page)
            runner = FlowRunner(artifacts_dir=str(self._artifacts), flows_dir=self.path.parent,
                                provider=self.config._webagent_provider, profile=self.profile)
            try:
                result = runner.run(self.flow, page, recorder=recorder)
                healed = sum(1 for s in result.steps if s.success and (s.layer_used or 1) > 1)
                self.user_properties.append((HEALINGS_PROP, healed))
                if not result.success:
                    self._backfill_evidence(result, page, runner)
            finally:
                # Whatever happened inside the flow, the report and the remote
                # dashboard still get what was captured.
                _keep_trace(page, result, self.flow.name, self.profile)
                if plugin:
                    if result is not None and result.steps:
                        plugin.record_steps(self.nodeid, result.steps)
                    if result is not None and not result.success:
                        plugin.record_error(self.nodeid, result.error)
                    plugin.record_capture(self.nodeid, recorder.console,
                                          recorder.network, recorder.dropped)
                _set_lambdatest_status(
                    page,
                    result.success if result is not None else False,
                    result.error if result is not None else "flow crashed before completing",
                )

        if not result.success:
            raise _FlowFailure(result)

    @staticmethod
    def _backfill_evidence(result: FlowResult, page, runner: FlowRunner) -> None:
        """Failure evidence lives on the failing step — single path.

        The engine collects it at the failure site; only when the viewport
        shot was impossible there (page navigating, crash) capture the
        flow-end state here. Skipped steps never get evidence.
        """
        failed_steps = [s for s in result.steps
                        if not s.success and not getattr(s, "skipped", False)]
        if not failed_steps or failed_steps[-1].screenshot_path:
            return
        step = runner.attach_evidence(failed_steps[-1], page)
        if step.screenshot_path:
            annotate_error_elements(step.screenshot_path, page)
            result.last_screenshot = step.screenshot_path

    def repr_failure(self, excinfo) -> str:
        if isinstance(excinfo.value, FlowParseError):
            e = excinfo.value
            return (
                f"Flow parse error at step {e.step_num}: {e}\n"
                f"  Raw: {e.raw!r}"
            )
        if isinstance(excinfo.value, _FlowFailure):
            r = excinfo.value.result
            lines = [f"Flow '{r.flow_name}' failed — {r.error}", ""]
            for s in r.steps:
                if getattr(s, "skipped", False):
                    icon, layer = "—", "[skipped]"
                elif s.success:
                    icon, layer = "✓", f"[L{s.layer_used}]"
                else:
                    icon, layer = "✗", f"[L{s.layer_used} FAIL]"
                dur = f"{s.duration * 1000:.0f}ms" if s.duration < 1 else f"{s.duration:.2f}s"
                prefix = f"↳ [{s.sub_flow}]  " if s.sub_flow else ""
                lines.append(f"  {icon} Step {s.action.step_num:>2} {layer}  {prefix}{s.action.raw}  ({dur})")
                if not s.success and not getattr(s, "skipped", False):
                    lines.append(f"       {s.message}")
            return "\n".join(lines)
        return str(excinfo.value)

    def reportinfo(self):
        return self.path, 0, f"flow: {self.flow.name}"


class FlowFile(pytest.File):
    """Collects a single .md flow file as a pytest node."""

    def collect(self) -> Generator:
        try:
            flow = parse_flow_file(Path(self.fspath))
        except FlowParseError as exc:
            import warnings
            warnings.warn(f"Failed to parse flow {self.fspath}: {exc}")
            return
        yield from _flow_items(self, self.config, flow)


def pytest_collect_file(parent, file_path: Path):
    """Hook: turn every .md file pytest traverses into a flow test, wherever it lives."""
    if file_path.suffix.lower() == ".md":
        # Skip auto-discovery when --flow_file explicitly targets this file —
        # the injection in pytest_collection_modifyitems will handle it.
        explicit = parent.config.getoption("--flow_file", default=None)
        if explicit and Path(explicit).resolve() == file_path.resolve():
            return None
        return FlowFile.from_parent(parent, path=file_path)

