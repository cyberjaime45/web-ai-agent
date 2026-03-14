"""
Shared pytest fixtures and hooks for the QA AI Agent framework.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

import pytest
from dotenv import load_dotenv
from playwright.sync_api import Page

from agent.flow_parser import load_all_flows, FlowDefinition
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
        driver: BrowserDriver | None = item.funcargs.get("browser_driver")  # type: ignore[assignment]
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


# ── Fixtures ───────────────────────────────────────────────────


@pytest.fixture(scope="session")
def all_flows() -> dict[str, FlowDefinition]:
    flows_dir = Path(__file__).parent / "src" / "flows"
    return load_all_flows(flows_dir)


@pytest.fixture
def browser_driver(page: Page, tmp_path: Path) -> BrowserDriver:
    artifacts_dir = Path(__file__).parent / "artifacts"
    artifacts_dir.mkdir(exist_ok=True)
    return BrowserDriver(page, artifacts_dir=str(artifacts_dir))


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
