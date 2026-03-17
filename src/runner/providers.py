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

from playwright.sync_api import Browser, Playwright

logger = logging.getLogger(__name__)

# ── Public API ─────────────────────────────────────────────────────────────────


def create_browser(pw: Playwright, test_name: str = "web-agent") -> Browser:
    """Return an open Playwright Browser based on the RUNNING_MODE env var.

    Args:
        pw:        Active Playwright instance (from ``sync_playwright()``).
        test_name: Human-readable label for the test session.
                   Used as the session name on remote providers (e.g. LambdaTest dashboard).

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


def _local_browser(pw: Playwright) -> Browser:
    """Launch a local browser using env-controlled options.

    Env vars (all optional, with defaults):
      BROWSER   chromium | firefox | webkit  (default: chromium)
      HEADLESS  true | false                 (default: true)
      SLOW_MO   milliseconds                 (default: 0)
    """
    browser_name = os.getenv("BROWSER", "chromium").lower()
    headless = os.getenv("HEADLESS", "true").lower() != "false"
    slow_mo = int(os.getenv("SLOW_MO", "0"))

    browser_type = getattr(pw, browser_name, None)
    if browser_type is None:
        raise ValueError(
            f"Unknown BROWSER {browser_name!r}. Supported: chromium, firefox, webkit"
        )

    logger.debug(
        "[provider:local] browser=%s headless=%s slow_mo=%d",
        browser_name, headless, slow_mo,
    )
    return browser_type.launch(headless=headless, slow_mo=slow_mo)


# ── LambdaTest ─────────────────────────────────────────────────────────────────

# LambdaTest's Playwright CDP endpoint (different from the Selenium hub URL).
# is validated below to confirm a complete LambdaTest configuration, but Playwright
# connects via CDP at the address below.
_LT_CDP_ENDPOINT = "wss://cdp.lambdatest.com/playwright"

def _lambdatest_browser(pw: Playwright, test_name: str) -> Browser:
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
            "build":      f"QA Web Agent -> {os.getenv("ENVIRONMENT", "staging")}",
            "name":       test_name,
            "platform":   "Windows 11",
            "resolution": "1280x720",
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
    return pw.chromium.connect(endpoint)
