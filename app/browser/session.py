"""
Browser lifecycle — where every page a flow runs on comes from.

``BrowserSession`` is used by both entry points (the pytest plugin in
conftest.py and the CLI's Orchestrator): one Playwright driver and browser
per session locally, a fresh ``BrowserContext`` per flow (isolation: cookies,
storage, viewport), shaped by the device profile. Under RUNNING_MODE=lambda
every flow opens its own grid session, because the LambdaTest dashboard
names and grades tests per session.

``create_browser`` is the provider factory RUNNING_MODE selects:
  local   → Playwright launches a local browser (reads BROWSER / HEADLESS / SLOW_MO)
  lambda  → Connects to LambdaTest's Playwright cloud grid

Adding a new provider (e.g. Sauce Labs): a branch in ``create_browser``, a
``_saucelabs_browser()`` helper below, and its status call in ``report_status``.
"""

from __future__ import annotations

import json
import logging
import urllib.parse
from collections.abc import Iterator
from contextlib import contextmanager

from playwright.sync_api import Browser, Page, Playwright, sync_playwright

from app.browser import profiles
from app.config.settings import settings
from app.utils.build import get_build_name

logger = logging.getLogger(__name__)

# ── Public API ─────────────────────────────────────────────────────────────────


def create_browser(pw: Playwright, test_name: str = "web-agent") -> tuple[Browser, dict]:
    """Return an open Playwright Browser and context options based on RUNNING_MODE.

    Args:
        pw:        Active Playwright instance (from ``sync_playwright()``).
        test_name: Human-readable label for the test session.
                   Used as the session name on remote providers (e.g. LambdaTest dashboard).

    Returns:
        (browser, context_kwargs): The browser instance and a dict of keyword
        arguments to pass to ``browser.new_context()``.

    Raises:
        ValueError:        Unknown RUNNING_MODE value.
        EnvironmentError:  Required env vars are missing for the selected provider.
    """
    mode = settings.running_mode
    logger.info("[provider] mode=%r", mode)

    if mode == "local":
        return _local_browser(pw)
    if mode == "lambda":
        return _lambdatest_browser(pw, test_name)

    raise ValueError(
        f"Unknown RUNNING_MODE {mode!r}. Supported values: local, lambda"
    )


# ── Local ──────────────────────────────────────────────────────────────────────


def _local_browser(pw: Playwright) -> tuple[Browser, dict]:
    """Launch a local browser with consistent viewport using env-controlled options.

    Env vars (all optional, with defaults):
      BROWSER    chromium | firefox | webkit  (default: chromium)
      HEADLESS   true | false                 (default: true)
      SLOW_MO    milliseconds                 (default: 0)
      VIEWPORT   WIDTHxHEIGHT                 (default: 1920x1080)

    Headed mode:  ``--start-maximized`` + ``no_viewport=True`` so the page
                  fills the entire OS window (Chromium only; other browsers
                  fall back to the VIEWPORT size).
    Headless mode: Uses VIEWPORT (default 1920×1080) since there is no OS
                   window to maximize.
    """
    browser_name = settings.browser
    headless = settings.headless
    slow_mo = settings.slow_mo
    viewport_str = settings.viewport

    browser_type = getattr(pw, browser_name, None)
    if browser_type is None:
        raise ValueError(
            f"Unknown BROWSER {browser_name!r}. Supported: chromium, firefox, webkit"
        )

    # Parse VIEWPORT env var (e.g. "1920x1080")
    try:
        w, h = viewport_str.lower().split("x")
        viewport = {"width": int(w), "height": int(h)}
    except (ValueError, AttributeError):
        viewport = {"width": 1920, "height": 1080}

    launch_args = []
    if browser_name == "chromium" and not headless:
        launch_args.append("--start-maximized")

    logger.debug(
        "[provider:local] browser=%s headless=%s slow_mo=%d viewport=%s",
        browser_name, headless, slow_mo, viewport_str,
    )
    browser = browser_type.launch(
        headless=headless,
        slow_mo=slow_mo,
        args=launch_args,
    )

    # Headed Chromium: no_viewport lets the page fill the maximized OS window.
    # Everything else: use an explicit viewport for consistent rendering.
    if browser_name == "chromium" and not headless:
        return browser, {"no_viewport": True}
    return browser, {"viewport": viewport}


# ── LambdaTest ─────────────────────────────────────────────────────────────────

# LambdaTest's Playwright CDP endpoint (different from the Selenium hub URL).
_LT_CDP_ENDPOINT = "wss://cdp.lambdatest.com/playwright"

def _lambdatest_browser(pw: Playwright, test_name: str) -> tuple[Browser, dict]:
    """Connect to LambdaTest's Playwright cloud grid via CDP.

    Required env vars:
      LT_USERNAME   LambdaTest account username
      LT_ACCESS_KEY LambdaTest access key

    Optional env vars (shared with local mode):
      BUILD_NAME    Build label in the LambdaTest dashboard (default: "Web Test Report")
      ENVIRONMENT   Suffixed to the build label (default: staging)
    """
    username   = settings.lt_username
    access_key = settings.lt_access_key

    missing = [
        name for name, val in (
            ("LT_USERNAME",   username),
            ("LT_ACCESS_KEY", access_key),
        )
        if not val
    ]
    if missing:
        raise EnvironmentError(
            f"RUNNING_MODE=lambda requires the following env vars to be set: "
            f"{', '.join(missing)}. Add them to your .env file."
        )

    capabilities = {
        "browserName": "Chrome",
        "browserVersion": "latest",
        "LT:Options": {
            "username":   username,
            "accessKey":  access_key,
            "build":      f"{get_build_name()} -> {settings.environment}",
            "name":       test_name,
            "platform":   "Windows 11",
            "resolution": "1920x1080",
            "console":    "true",
            "network":    "true",
            "visual":     "true",
        },
    }

    endpoint = (
        f"{_LT_CDP_ENDPOINT}"
        f"?capabilities={urllib.parse.quote(json.dumps(capabilities))}"
    )

    logger.debug("[provider:lambda] connecting to LambdaTest (user=%r build=%r name=%r)",
                 username, capabilities["LT:Options"]["build"], test_name)
    browser = pw.chromium.connect(endpoint)
    # Match the LambdaTest VM resolution
    return browser, {"viewport": {"width": 1920, "height": 1080}}


# ── Session: browser reuse, one context per flow ──────────────────────────────


class BrowserSession:
    """One Playwright driver + browser for many flows; a fresh context per page().

    The browser process is the expensive part (~1.5-3 s per launch) and is
    shared locally; isolation comes from the per-flow BrowserContext.
    """

    def __init__(self) -> None:
        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self._ctx_opts: dict = {}

    @contextmanager
    def page(self, test_name: str, profile: str = profiles.DESKTOP, trace: bool = False) -> Iterator[Page]:
        """A fresh page in a context shaped by *profile*; *trace* starts Playwright
        tracing on the context (the caller stops it, keeping the zip or not)."""
        if settings.remote:
            pw = sync_playwright().start()
            try:
                browser, opts = create_browser(pw, test_name=test_name)
                try:
                    yield from self._new_page(browser, profiles.context_options(profile, opts, pw.devices), trace)
                finally:
                    browser.close()
            finally:
                pw.stop()
            return
        if self._browser is None or not self._browser.is_connected():
            self._pw = self._pw or sync_playwright().start()
            self._browser, self._ctx_opts = create_browser(self._pw, test_name=test_name)
        yield from self._new_page(
            self._browser, profiles.context_options(profile, self._ctx_opts, self._pw.devices), trace)

    @staticmethod
    def _new_page(browser: Browser, opts: dict, trace: bool) -> Iterator[Page]:
        ctx = browser.new_context(**opts)
        if trace:
            ctx.tracing.start(screenshots=True, snapshots=True)
        try:
            yield ctx.new_page()
        finally:
            ctx.close()     # closing also discards an unstopped trace

    def close(self) -> None:
        if self._browser is not None:
            self._browser.close()
        if self._pw is not None:
            self._pw.stop()
        self._browser = self._pw = None


def report_status(page: Page, success: bool, error: str = "") -> None:
    """Tell the remote grid (LambdaTest) whether the flow passed; no-op locally."""
    if not settings.remote:
        return
    try:
        payload = json.dumps({
            "action": "setTestStatus",
            "arguments": {"status": "passed" if success else "failed",
                          "remark": "" if success else (error or "Test failed")[:255]},
        })
        page.evaluate("_ => {}", f"lambdatest_action: {payload}")
    except Exception as exc:
        logger.debug("LambdaTest status not sent: %s", exc)
