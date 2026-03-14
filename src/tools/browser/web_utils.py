"""
WebUtils — Mixin containing all artifact capture and debug-export utilities
used by the BrowserDriver.

Provides: screenshots (full-page and viewport), HTML snapshots, PDF export,
and a composite debug bundle.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from playwright.sync_api import Page

logger = logging.getLogger(__name__)


class WebUtilsMixin:
    """All artifact-capture and web-utility methods for BrowserDriver."""

    page: "Page"          # set by BrowserDriver.__init__
    artifacts_dir: Path   # set by BrowserDriver.__init__
    _screenshot_counter: int  # set by BrowserDriver.__init__

    # ── Screenshots ─────────────────────────────────────────────

    def capture_screenshot(self, name: Optional[str] = None) -> str:
        """Capture a full-page screenshot and return the saved file path."""
        self._screenshot_counter += 1
        filename = name or f"screenshot_{self._screenshot_counter:03d}"
        if not filename.endswith(".png"):
            filename += ".png"
        path = self.artifacts_dir / "screenshots" / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        self.page.screenshot(path=str(path), full_page=True)
        logger.info("Screenshot saved: %s", path)
        return str(path)

    def capture_viewport_screenshot(self, name: Optional[str] = None) -> str:
        """Capture a viewport-only (non-full-page) screenshot.

        Useful when the full-page height would produce an unreadably tall image.
        """
        self._screenshot_counter += 1
        filename = name or f"viewport_{self._screenshot_counter:03d}"
        if not filename.endswith(".png"):
            filename += ".png"
        path = self.artifacts_dir / "screenshots" / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        self.page.screenshot(path=str(path), full_page=False)
        logger.info("Viewport screenshot saved: %s", path)
        return str(path)

    # ── HTML snapshots ──────────────────────────────────────────

    def capture_html_snapshot(self, name: Optional[str] = None) -> str:
        """Save the current page HTML source and return the file path."""
        self._screenshot_counter += 1
        filename = name or f"snapshot_{self._screenshot_counter:03d}"
        if not filename.endswith(".html"):
            filename += ".html"
        path = self.artifacts_dir / "traces" / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.page.content(), encoding="utf-8")
        logger.info("HTML snapshot saved: %s", path)
        return str(path)

    # ── PDF export ──────────────────────────────────────────────

    def capture_pdf(self, name: Optional[str] = None) -> str:
        """Export the current page as a PDF and return the file path.

        Note: Playwright PDF export requires a Chromium-based browser in
        headless mode.
        """
        self._screenshot_counter += 1
        filename = name or f"page_{self._screenshot_counter:03d}"
        if not filename.endswith(".pdf"):
            filename += ".pdf"
        path = self.artifacts_dir / "pdfs" / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        self.page.pdf(path=str(path))
        logger.info("PDF saved: %s", path)
        return str(path)

    # ── Debug bundle ────────────────────────────────────────────

    def capture_debug_bundle(self, name: str = "debug") -> dict:
        """Capture screenshot + HTML snapshot together as a debug bundle.

        Returns a dict with ``screenshot`` and ``html`` paths so callers can
        attach both artifacts to a failure report in one call.
        """
        screenshot = self.capture_screenshot(f"{name}_screenshot")
        html_snap  = self.capture_html_snapshot(f"{name}_snapshot")
        return {"screenshot": screenshot, "html": html_snap}
