"""
Browser provider factory — abstracts local vs remote browser creation.

RUNNING_MODE controls which provider is used:
  local   → Playwright launches a local browser (reads BROWSER / HEADLESS / SLOW_MO)
  lambda  → Connects to LambdaTest's Playwright cloud grid

Adding a new provider (e.g. Sauce Labs):
  1. Add a new elif branch in create_browser()
  2. Implement a _saucelabs_browser() helper below
  3. Document the required env vars in the docstring
"""

from __future__ import annotations

import json
import logging
import os
import urllib.parse

from playwright.sync_api import Browser, BrowserContext, Playwright

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
    mode = os.getenv("RUNNING_MODE", "local").lower().strip()
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
    browser_name = os.getenv("BROWSER", "chromium").lower()
    headless = os.getenv("HEADLESS", "true").lower() != "false"
    slow_mo = int(os.getenv("SLOW_MO", "0"))
    viewport_str = os.getenv("VIEWPORT", "1920x1080")

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
# is validated below to confirm a complete LambdaTest configuration, but Playwright
# connects via CDP at the address below.
_LT_CDP_ENDPOINT = "wss://cdp.lambdatest.com/playwright"

def _lambdatest_browser(pw: Playwright, test_name: str) -> tuple[Browser, dict]:
    """Connect to LambdaTest's Playwright cloud grid via CDP.

    Required env vars:
      LT_USERNAME   LambdaTest account username
      LT_ACCESS_KEY LambdaTest access key

    Optional env vars (shared with local mode):
      ENVIRONMENT   Sets the build name in the LambdaTest dashboard (default: staging)
    """
    username   = os.getenv("LT_USERNAME", "").strip()
    access_key = os.getenv("LT_ACCESS_KEY", "").strip()

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
            "build":      f"QA Web Agent -> {os.getenv('ENVIRONMENT', 'staging')}",
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
