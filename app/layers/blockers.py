"""Blocking-UI dismissal — cookie banners, consent modals, overlays.

Opt-in via DISMISS_BLOCKERS=true: ``DeterministicRunner.execute`` calls
``dismiss_blockers(page)`` before each L1 attempt. Off by default because it
costs one ``count()`` round-trip per selector on every step.
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


def dismiss_blockers(page: Page) -> None:
    """Detect and dismiss common blocking UI elements (modals, banners)."""
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
                    logger.info(f"[L1] Dismissed blocker: {selector} via {dismiss}")
                    page.wait_for_timeout(300)
                    return
            except Exception:
                continue

        # No dismiss button found — try Escape key
        try:
            page.keyboard.press("Escape")
            logger.info(f"[L1] Dismissed blocker: {selector} via Escape")
            page.wait_for_timeout(300)
            return
        except Exception:
            continue
