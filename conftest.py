"""
Shared pytest fixtures and hooks for the QA AI Agent framework.

Auto-discovery: .md flow files in tests/flows/ are collected automatically
by pytest_collect_file — no test_*.py files needed.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Generator

import pytest
from dotenv import load_dotenv
from playwright.sync_api import Page, sync_playwright

from agent.flow_parser import load_all_flows, FlowDefinition, parse_flow_file, parse_flow_markdown
from runner.flow_runner import FlowRunner
from runner.actions import FlowResult
from tools.browser.driver import BrowserDriver
from report_generator import generate_report

# ── Load .env ──────────────────────────────────────────────────

load_dotenv()

_ENV          = os.getenv("ENVIRONMENT", "staging")
_BASE_URL     = os.getenv("BASE_URL", "")
_LOG_LEVEL    = os.getenv("LOG_LEVEL", "info")
_COVERAGE     = int(os.getenv("COVERAGE", "0"))
_COV_TARGET   = int(os.getenv("COVERAGE_TARGET", "80"))
_THEME_STYLE  = os.getenv("THEME_STYLE", "system")

# ── Configure logging ───────────────────────────────────────────

logging.basicConfig(
    level=getattr(logging, _LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# ── Report paths ───────────────────────────────────────────────

_PROJECT_ROOT = Path(__file__).parent
_REPORT_DIR   = _PROJECT_ROOT / "reports" / _ENV
_IMAGES_DIR   = _REPORT_DIR / "images"
_REPORT_PATH  = _REPORT_DIR / "report.html"
_HISTORY_PATH = _PROJECT_ROOT / "reports" / "run_history.json"


# ── Professional report plugin ──────────────────────────────────


class ProfessionalReportPlugin:
    """Collects test results and generates a professional HTML report."""

    def __init__(self) -> None:
        self.results: list[dict] = []
        self.failure_screenshots: dict[str, str] = {}
        self.session_start = time.time()

    def record_screenshot(self, nodeid: str, path: str) -> None:
        self.failure_screenshots[nodeid] = path

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        if report.when == "call" or (report.when == "setup" and report.failed):
            self.results.append(
                {
                    "nodeid":   report.nodeid,
                    "name":     report.nodeid.split("::")[-1],
                    "class":    "::".join(report.nodeid.split("::")[1:-1]),
                    "outcome":  report.outcome,
                    "duration": getattr(report, "duration", 0.0),
                    "longrepr": str(report.longrepr) if report.failed else "",
                    "screenshot": None,
                }
            )

    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int) -> None:
        for r in self.results:
            path = self.failure_screenshots.get(r["nodeid"])
            if path:
                r["screenshot"] = path

        generate_report(
            results=self.results,
            session_start=self.session_start,
            output_path=_REPORT_PATH,
            environment=_ENV,
            base_url=_BASE_URL,
            log_level=_LOG_LEVEL,
            coverage=_COVERAGE,
            coverage_target=_COV_TARGET,
            history_path=_HISTORY_PATH,
            theme_style=_THEME_STYLE,
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
        else:
            # No error element found — draw a small ✕ marker in the top-right corner
            w, h = img.size
            m, s = 8, 28
            draw.rectangle([w - m - s, m, w - m, m + s], outline=(220, 38, 38), width=3)
            draw.line([w - m - s, m, w - m, m + s], fill=(220, 38, 38), width=2)
            draw.line([w - m, m, w - m - s, m + s], fill=(220, 38, 38), width=2)

        img.save(shot_path)
    except Exception:
        pass  # Annotation is best-effort; never block reporting


# ── Screenshot capture on call-phase failure ───────────────────
#
# Captured here — inside makereport for the "call" phase — because
# the browser page is still open at this point.

@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo):
    outcome = yield
    rep = outcome.get_result()
    setattr(item, f"rep_{rep.when}", rep)

    if call.when == "call" and rep.failed:
        funcargs = getattr(item, "funcargs", None) or {}
        driver: BrowserDriver | None = funcargs.get("browser_driver")  # type: ignore[assignment]
        if driver is not None:
            try:
                safe_name = item.name.replace("/", "_").replace(":", "_")
                shot_path = driver.capture_screenshot(f"FAIL_{safe_name}")
                _annotate_failure_screenshot(shot_path, driver.page)
                plugin = item.config.pluginmanager.get_plugin("professional_report")
                if plugin is not None:
                    plugin.record_screenshot(item.nodeid, shot_path)
            except Exception:
                pass


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
            browser = pw.chromium.launch(headless=True)
            ctx = browser.new_context(viewport={"width": 1280, "height": 720})
            page = ctx.new_page()
            page.set_default_timeout(self.flow.timeout)

            runner = FlowRunner(artifacts_dir=str(self._artifacts))
            result: FlowResult = runner.run(self.flow, page)

            # Take a fresh failure screenshot while the browser is still open.
            # This captures the exact page state at the moment of failure and
            # is more reliable than relying on the last explicit `screenshot` step.
            if not result.success:
                try:
                    safe = self.flow.name.replace(" ", "_")
                    shot_path = str(self._artifacts / f"FAIL_{safe}.png")
                    page.screenshot(path=shot_path)
                    _annotate_failure_screenshot(shot_path, page)
                    result.last_screenshot = shot_path
                except Exception:
                    pass  # best-effort; don't block test reporting

                if result.last_screenshot:
                    plugin = self.config.pluginmanager.get_plugin("professional_report")
                    if plugin:
                        plugin.record_screenshot(self.nodeid, result.last_screenshot)

            ctx.close()
            browser.close()

        if not result.success:
            raise _FlowFailure(result)

    def repr_failure(self, excinfo) -> str:
        if isinstance(excinfo.value, _FlowFailure):
            r = excinfo.value.result
            lines = [f"Flow '{r.flow_name}' failed — {r.error}", ""]
            for s in r.steps:
                icon = "✓" if s.success else "✗"
                layer = f"[L{s.layer_used}]" if s.success else f"[L{s.layer_used} FAIL]"
                lines.append(f"  {icon} Step {s.action.step_num:>2} {layer}  {s.action.raw}")
                if not s.success:
                    lines.append(f"       {s.message}")
            return "\n".join(lines)
        return str(excinfo.value)

    def reportinfo(self):
        return self.fspath, 0, f"flow: {self.flow.name}"


class FlowFile(pytest.File):
    """Collects a single .md flow file as a pytest node."""

    def collect(self) -> Generator:
        flow = parse_flow_file(Path(self.fspath))
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
    flows_dir = Path(__file__).parent / "tests" / "flows"
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
