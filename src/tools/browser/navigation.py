"""
Navigation — Mixin containing all browser navigation behaviour.

Provides: URL transitions, history traversal, page reload, URL/title
accessors, and navigation guards used by the BrowserDriver.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.sync_api import Page

logger = logging.getLogger(__name__)


class NavigationMixin:
    """All navigation-related methods for BrowserDriver."""

    page: "Page"  # set by BrowserDriver.__init__

    # ── Core navigation ─────────────────────────────────────────

    def open_page(self, url: str, timeout: int = 30_000) -> None:
        """Navigate to a URL and wait for DOMContentLoaded."""
        logger.info("Navigating to: %s", url)
        self.page.goto(url, wait_until="domcontentloaded", timeout=timeout)

    def go_back(self, timeout: int = 10_000) -> None:
        """Navigate back in browser history."""
        logger.info("Navigating back")
        self.page.go_back(wait_until="domcontentloaded", timeout=timeout)

    def go_forward(self, timeout: int = 10_000) -> None:
        """Navigate forward in browser history."""
        logger.info("Navigating forward")
        self.page.go_forward(wait_until="domcontentloaded", timeout=timeout)

    def reload(self, timeout: int = 30_000) -> None:
        """Reload the current page."""
        logger.info("Reloading page")
        self.page.reload(wait_until="domcontentloaded", timeout=timeout)

    # ── State accessors ─────────────────────────────────────────

    def get_current_url(self) -> str:
        """Return the current page URL."""
        return self.page.url

    def get_page_title(self) -> str:
        """Return the current page title."""
        return self.page.title()

    # ── Wait helpers ────────────────────────────────────────────

    def wait_for_url(self, pattern: str, timeout: int = 10_000) -> None:
        """Wait until the URL contains *pattern* (case-insensitive)."""
        self.page.wait_for_url(f"**{pattern}**", timeout=timeout)

    def wait_for_load(self, state: str = "domcontentloaded", timeout: int = 30_000) -> None:
        """Wait for the page to reach a given load state.

        ``state`` must be one of ``"load"``, ``"domcontentloaded"``, or
        ``"networkidle"``.
        """
        self.page.wait_for_load_state(state, timeout=timeout)  # type: ignore[arg-type]
