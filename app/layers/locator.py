"""
Fallback Locator (Layer 2) — tries progressively less strict strategies
to find an element when the deterministic Layer 1 exact match fails.

Resolution order for clickable elements:
  1. Exact role+name  (button / link)
  2. Case-insensitive role+name
  3. get_by_text exact
  4. get_by_text partial
  5. selectolax fuzzy HTML search (similarity >= 0.6)

Resolution order for inputs:
  1. get_by_label exact
  2. get_by_label partial
  3. get_by_placeholder exact
  4. get_by_placeholder partial
  5. get_by_role "textbox" exact / partial
  6. selectolax label->for->input lookup
"""

from __future__ import annotations

import logging
from difflib import SequenceMatcher

from playwright.sync_api import Locator, Page

logger = logging.getLogger(__name__)


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


class FallbackLocator:
    """Resolves element locators with progressively looser strategies."""

    def resolve_clickable(self, page: Page, target: str) -> Locator | None:
        # CSS selector shortcut: .class, #id, [attr=val]
        if target and target[0] in (".", "#", "["):
            return self._try(lambda: page.locator(target))
        for strategy in (
            lambda: page.get_by_role("button", name=target, exact=True),
            lambda: page.get_by_role("link",   name=target, exact=True),
            lambda: page.get_by_role("button", name=target),
            lambda: page.get_by_role("link",   name=target),
            lambda: page.get_by_text(target, exact=True),
            lambda: page.get_by_text(target),
            lambda: self._fuzzy_clickable(page, target),
        ):
            loc = self._try(strategy)
            if loc is not None:
                return loc
        return None

    def resolve_input(self, page: Page, target: str) -> Locator | None:
        # CSS selector shortcut: .class, #id, [attr=val]
        if target and target[0] in (".", "#", "["):
            return self._try(lambda: page.locator(target))
        for strategy in (
            lambda: page.get_by_label(target, exact=True),
            lambda: page.get_by_label(target),
            lambda: page.get_by_placeholder(target, exact=True),
            lambda: page.get_by_placeholder(target),
            lambda: page.get_by_role("textbox", name=target, exact=True),
            lambda: page.get_by_role("textbox", name=target),
            lambda: self._fuzzy_input(page, target),
        ):
            loc = self._try(strategy)
            if loc is not None:
                return loc
        return None

    def resolve_checkbox(self, page: Page, target: str) -> Locator | None:
        """Resolve a checkbox or radio element by label or role."""
        for strategy in (
            lambda: page.get_by_label(target, exact=True),
            lambda: page.get_by_label(target),
            lambda: page.get_by_role("checkbox", name=target, exact=True),
            lambda: page.get_by_role("checkbox", name=target),
            lambda: page.get_by_role("radio", name=target, exact=True),
            lambda: page.get_by_role("radio", name=target),
        ):
            loc = self._try(strategy)
            if loc is not None:
                return loc
        return None

    def resolve_table_row(self, page: Page, text: str) -> Locator | None:
        """Resolve a table row containing the given text."""
        for strategy in (
            lambda: page.locator(f'tr:has-text("{text}")'),
            lambda: page.locator(f'[role="row"]:has-text("{text}")'),
        ):
            loc = self._try(strategy)
            if loc is not None:
                return loc
        return None

    # ── helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _try(strategy) -> Locator | None:
        try:
            loc = strategy()
            if loc is not None and loc.count() > 0:
                return loc.first
        except Exception:
            pass
        return None

    def _fuzzy_clickable(self, page: Page, target: str) -> Locator | None:
        try:
            from selectolax.parser import HTMLParser

            tree = HTMLParser(page.content())
            best_score, best_text = 0.0, None
            for node in tree.css("button, a, [role=button], [role=link], [role=menuitem], [role=tab]"):
                text = node.text(strip=True)
                if not text:
                    continue
                score = _similarity(target, text)
                if score > best_score and score >= 0.6:
                    best_score, best_text = score, text

            if best_text:
                logger.debug(f"[L2] Fuzzy match '{target}' -> '{best_text}' ({best_score:.2f})")
                return self._try(lambda: page.get_by_text(best_text))
        except Exception as exc:
            logger.debug(f"[L2] fuzzy_clickable error: {exc}")
        return None

    def _fuzzy_input(self, page: Page, target: str) -> Locator | None:
        try:
            from selectolax.parser import HTMLParser

            tree = HTMLParser(page.content())
            best_score, best_for_id = 0.0, None
            for label in tree.css("label"):
                text = label.text(strip=True)
                if not text:
                    continue
                score = _similarity(target, text)
                if score > best_score and score >= 0.6:
                    best_score = score
                    best_for_id = label.attributes.get("for")

            if best_for_id:
                return self._try(lambda: page.locator(f"#{best_for_id}"))
        except Exception as exc:
            logger.debug(f"[L2] fuzzy_input error: {exc}")
        return None
