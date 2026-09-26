"""Blocking-UI dismissal — cookie banners, consent modals, overlays.

``DeterministicRunner.execute`` calls ``dismiss_blockers(page)`` in two places:
after an element interaction fails at L1 (always — it costs nothing on the
passing path; a dismissal triggers one L1 retry), and before every L1 attempt
when DISMISS_BLOCKERS=true (off by default: one ``count()`` round-trip per
selector on every step).
"""

from __future__ import annotations

import logging

from playwright.sync_api import Page

logger = logging.getLogger(__name__)

# Common selectors for blocking UI elements (modals, banners, overlays)
BLOCKER_SELECTORS = [
    '[class*="cookie" i]',
    '[id*="cookie" i]',
    '[class*="consent" i]',
    '[id*="consent" i]',
    '.modal.show',
    '[role="dialog"][aria-modal="true"]',
    '[class*="overlay" i]:not([style*="display: none"])',
    '[class*="popup" i]',
    '[class*="banner" i][class*="accept" i]',
]

# Dismiss button selectors tried inside a detected blocker
DISMISS_SELECTORS = [
    'button:has-text("Accept")',
    'button:has-text("OK")',
    'button:has-text("Close")',
    'button:has-text("Got it")',
    'button:has-text("Dismiss")',
    '[aria-label="Close"]',
    'button:has-text("×")',
]


def dismiss_blockers(page: Page) -> str | None:
    """Dismiss the first visible blocking element; describe what was done, or None."""
    for selector in BLOCKER_SELECTORS:
        try:
            blocker = page.locator(selector).first
            if blocker.count() == 0 or not blocker.is_visible():
                continue
        except Exception:
            continue

        # Try dismiss buttons inside the blocker
        for dismiss in DISMISS_SELECTORS:
            try:
                btn = blocker.locator(dismiss).first
                if btn.count() > 0 and btn.is_visible():
                    btn.click(timeout=2000)
                    logger.info("[L1] Dismissed blocker: %s via %s", selector, dismiss)
                    page.wait_for_timeout(300)
                    return f"{dismiss} in {selector}"
            except Exception:
                continue

        # No dismiss button found — try Escape, and only claim it if the blocker went away
        try:
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)
            if blocker.is_visible():
                continue
            logger.info("[L1] Dismissed blocker: %s via Escape", selector)
            return f"Escape on {selector}"
        except Exception:
            continue
    return None
