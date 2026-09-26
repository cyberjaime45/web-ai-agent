"""Fixtures shared by the framework's browser tests."""

from __future__ import annotations

import pytest


@pytest.fixture(scope="module")
def page():
    """One real Chromium page per test module; skipped when Chromium is not installed."""
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    try:
        browser = pw.chromium.launch()
    except Exception as exc:                       # no browser on this machine
        pw.stop()
        pytest.skip(f"chromium unavailable: {exc}")
    context = browser.new_context(viewport={"width": 1280, "height": 800})
    pg = context.new_page()
    pg.set_default_timeout(5000)
    yield pg
    context.close()
    browser.close()
    pw.stop()
