"""
Shared pytest fixtures and hooks for the Web AI Agent runtime.

Auto-discovery: .md flow files in flows/ are collected automatically
by pytest_collect_file — no test_*.py files needed.
"""

from __future__ import annotations

import datetime
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Generator

import pytest
from dotenv import load_dotenv
from playwright.sync_api import Page, sync_playwright

from app.flow.parser import FlowParseError, load_all_flows, FlowDefinition, parse_flow_file, parse_flow_markdown
from app.execution.engine import FlowRunner
from app.schemas.actions import FlowResult
from app.browser.session import create_browser
from app.browser.driver import BrowserDriver
from app.observability.recorder import PageRecorder
from app.observability.reporter import generate_report
from app.utils.banner import show_banner

# ── Load .env ──────────────────────────────────────────────────

load_dotenv()

_ENV = os.getenv("ENVIRONMENT", "staging")

# ── Configure logging ───────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# ── Report paths ───────────────────────────────────────────────

_PROJECT_ROOT = Path(__file__).parent
_REPORT_DIR   = _PROJECT_ROOT / "reports" / _ENV
_IMAGES_DIR   = _REPORT_DIR / "images"
_REPORT_PATH  = _REPORT_DIR / "report.html"


# ── Professional report plugin ──────────────────────────────────


class ProfessionalReportPlugin:
    """Collects test results and generates a professional HTML report."""

    def __init__(self) -> None:
        self.results: list[dict] = []
        self.flow_steps: dict[str, list[dict]] = {}
        self.flow_errors: dict[str, str] = {}
        self.captures: dict[str, dict] = {}
        self.session_start = time.time()

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
        for r in self.results:
            nodeid = r["nodeid"]
            r["error"] = self.flow_errors.get(nodeid, "")
            r["flow_steps"] = self.flow_steps.get(nodeid, [])
            capture = self.captures.get(nodeid, {})
            r["console"] = capture.get("console", [])
            r["network"] = capture.get("network", [])
            r["capture_dropped"] = capture.get("dropped", {})

        generate_report(
            results=self.results,
            session_start=self.session_start,
            output_path=_REPORT_PATH,
            environment=_ENV,
        )
        print(f"\n📊 Report: {_REPORT_PATH}")


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


# ── Plugin registration ────────────────────────────────────────

def pytest_configure(config: pytest.Config) -> None:
    plugin = ProfessionalReportPlugin()
    config.pluginmanager.register(plugin, "professional_report")


def pytest_sessionstart(session: pytest.Session) -> None:
    show_banner()


# ── Screenshot annotation — draw red rectangles around error elements ──────────


def _annotate_failure_screenshot(shot_path: str, page) -> None:
    """Overlay red rectangles on a failure screenshot at DOM error-element locations."""
    try:
        from PIL import Image, ImageDraw  # type: ignore[import]

        rects = page.evaluate("""
            () => {
                const selectors = [
                    '[role="alert"]', '.error', '.alert-danger', '.alert-error',
                    '[aria-invalid="true"]', '.invalid-feedback', 'p.error',
                    'span.error', '.flash.error', '.notification-error',
                    '#error', '.error-message', '.validation-error', '.is-invalid'
                ];
                const found = [];
                for (const sel of selectors) {
                    try {
                        for (const el of document.querySelectorAll(sel)) {
                            const r = el.getBoundingClientRect();
                            if (r.width > 0 && r.height > 0 && r.top >= 0)
                                found.push({x: r.left, y: r.top, w: r.width, h: r.height});
                        }
                    } catch(e) {}
                }
                return found;
            }
        """)

        img = Image.open(shot_path).convert("RGB")
        draw = ImageDraw.Draw(img)

        if rects:
            vp_width = (page.viewport_size or {}).get("width", 1280)
            scale = img.width / vp_width if vp_width else 1.0
            for rect in rects[:4]:
                pad = 3
                x1 = max(0,         int(rect["x"] * scale) - pad)
                y1 = max(0,         int(rect["y"] * scale) - pad)
                x2 = min(img.width, int((rect["x"] + rect["w"]) * scale) + pad)
                y2 = min(img.height, int((rect["y"] + rect["h"]) * scale) + pad)
                if x2 > x1 and y2 > y1:
                    for offset in range(3):
                        draw.rectangle(
                            [x1 - offset, y1 - offset, x2 + offset, y2 + offset],
                            outline=(220, 38, 38),
                        )

        if not rects:
            return  # No identifiable error elements — keep screenshot clean

        img.save(shot_path)
    except Exception:
        pass  # Annotation is best-effort; never block reporting


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
        items.append(FlowItem.from_parent(session, name=flow.name, flow=flow))

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
        items.append(FlowItem.from_parent(session, name=flow.name, flow=flow))


# ── .md flow auto-discovery ────────────────────────────────────
#
# pytest_collect_file is called for every file pytest traverses.
# When it finds a .md file inside a "flows" directory it creates a
# FlowFile node, which in turn yields one FlowItem per flow file.
# FlowItem.runtest() launches its own Playwright browser so no
# test_*.py file is needed — just drop a .md file in src/flows/.


def _set_lambdatest_status(page, success: bool, error: str = "") -> None:
    """Report test pass/fail to LambdaTest dashboard (no-op for local runs)."""
    if os.getenv("RUNNING_MODE", "local").lower().strip() != "lambda":
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
    except Exception:
        pass  # best-effort; don't block test reporting


class _FlowFailure(Exception):
    """Raised by FlowItem.runtest() to carry the FlowResult for reporting."""

    def __init__(self, result: FlowResult) -> None:
        self.result = result
        super().__init__(result.error)


class FlowItem(pytest.Item):
    """A pytest test item backed by a .md flow file."""

    def __init__(self, name: str, parent, flow: FlowDefinition) -> None:
        super().__init__(name, parent)
        self.flow = flow
        self._artifacts = _IMAGES_DIR
        self._artifacts.mkdir(parents=True, exist_ok=True)

    def runtest(self) -> None:
        with sync_playwright() as pw:
            browser, ctx_opts = create_browser(pw, test_name=self.flow.name)
            ctx = browser.new_context(**ctx_opts)
            page = ctx.new_page()
            page.set_default_timeout(self.flow.timeout)

            # Capture console errors/warnings + network traffic for the report.
            recorder = PageRecorder()
            recorder.attach(page)

            flows_dir = Path(str(self.fspath)).parent if self.fspath else Path("flows")
            runner = FlowRunner(artifacts_dir=str(self._artifacts), flows_dir=flows_dir)
            result: FlowResult = runner.run(self.flow, page)

            # Record steps for the report (both pass and fail)
            plugin = self.config.pluginmanager.get_plugin("professional_report")

            # Failure screenshots live on the failing step — single path.
            # The engine captures one at the failure site; only when that was
            # impossible (page navigating, crash) capture the flow-end state
            # here instead. Skipped steps never get a screenshot.
            if not result.success:
                failed_steps = [s for s in result.steps
                                if not s.success and not getattr(s, "skipped", False)]
                last_failed = failed_steps[-1] if failed_steps else None
                if last_failed is not None and not last_failed.screenshot_path:
                    try:
                        shot_path = str(self._artifacts / f"{uuid.uuid4()}.png")
                        page.screenshot(path=shot_path)
                        _annotate_failure_screenshot(shot_path, page)
                        last_failed.screenshot_path = shot_path
                        result.last_screenshot = shot_path
                    except Exception:
                        pass  # best-effort; don't block test reporting

            if plugin:
                if result.steps:
                    plugin.record_steps(self.nodeid, result.steps)
                if not result.success:
                    plugin.record_error(self.nodeid, result.error)
                plugin.record_capture(self.nodeid, recorder.console,
                                      recorder.network, recorder.dropped)

            # Report pass/fail status to LambdaTest
            _set_lambdatest_status(page, result.success, result.error)

            ctx.close()
            browser.close()

        if not result.success:
            raise _FlowFailure(result)

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
        return self.fspath, 0, f"flow: {self.flow.name}"


class FlowFile(pytest.File):
    """Collects a single .md flow file as a pytest node."""

    def collect(self) -> Generator:
        try:
            flow = parse_flow_file(Path(self.fspath))
        except FlowParseError as exc:
            import warnings
            warnings.warn(f"Failed to parse flow {self.fspath}: {exc}")
            return
        yield FlowItem.from_parent(self, name=flow.name, flow=flow)


def pytest_collect_file(parent, file_path: Path):
    """Hook: turn every .md file in a flows/ directory into a test."""
    if file_path.suffix == ".md" and "flows" in file_path.parts:
        # Skip auto-discovery when --flow_file explicitly targets this file —
        # the injection in pytest_collection_modifyitems will handle it.
        explicit = parent.config.getoption("--flow_file", default=None)
        if explicit and Path(explicit).resolve() == file_path.resolve():
            return None
        return FlowFile.from_parent(parent, path=file_path)


# ── Fixtures ───────────────────────────────────────────────────


@pytest.fixture(scope="session")
def all_flows() -> dict[str, FlowDefinition]:
    flows_dir = Path(__file__).parent / "flows"
    return load_all_flows(flows_dir)


@pytest.fixture
def browser_driver(page: Page, tmp_path: Path) -> BrowserDriver:
    _IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    return BrowserDriver(page, artifacts_dir=str(_IMAGES_DIR))


@pytest.fixture
def login_flow(all_flows) -> FlowDefinition:
    assert "Login" in all_flows, f"Login.md not found. Available: {list(all_flows.keys())}"
    return all_flows["Login"]


@pytest.fixture
def navigation_flow(all_flows) -> FlowDefinition:
    assert "Navigation" in all_flows, f"Navigation.md not found. Available: {list(all_flows.keys())}"
    return all_flows["Navigation"]


@pytest.fixture
def form_validation_flow(all_flows) -> FlowDefinition:
    assert "FormValidation" in all_flows, f"FormValidation.md not found. Available: {list(all_flows.keys())}"
    return all_flows["FormValidation"]


@pytest.fixture
def multi_page_journey_flow(all_flows) -> FlowDefinition:
    assert "MultiPageJourney" in all_flows, (
        f"MultiPageJourney.md not found. Available: {list(all_flows.keys())}"
    )
    return all_flows["MultiPageJourney"]
