"""
Fallback Locator (Layer 2) — tries progressively less strict strategies
to find an element when the deterministic Layer 1 exact match fails.

L1 already exhausts exact-match locators, so L2 starts with fuzzy
(case-insensitive / partial) variants to avoid redundant browser queries.

Clickable elements: ``click_target.resolve`` — controls only, matched by
exact name, then whole word, then word similarity; one visible, enabled
candidate or the step fails saying why (ambiguous, hidden, disabled, absent).
``visible_text_match`` (L1's exact-text guard) judges text on the element's
*visible* text (``innerText``, line by line), not Playwright's
``textContent`` match, where a calendar row's cells 1 | 2 | 3 read "123".

Resolution order for inputs:
  1. get_by_label partial
  2. get_by_placeholder partial
  3. get_by_role "textbox" exact / partial
  4. selectolax label->for->input lookup — once, after the poll

Playwright strategies are cheap (one count() round-trip each) and are polled
until the element appears. The selectolax pass serialises and parses the whole
DOM, so it runs a single time after the poll gives up rather than on every
200 ms cycle.

Resolution order for checkboxes / radios:
  1. get_by_label partial
  2. get_by_role "checkbox" partial
  3. get_by_role "radio" partial
"""

from __future__ import annotations

import logging
import time
from difflib import SequenceMatcher
from typing import Callable

from playwright.sync_api import Locator, Page

from app.layers.click_target import Resolution
from app.layers.click_target import resolve as resolve_click_target

logger = logging.getLogger(__name__)


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _is_selector(s: str) -> bool:
    """True when *s* looks like a CSS selector or XPath expression.

    CSS: ``#id``, ``.class``, ``[attr]``, tag-prefixed (``div[class='x']``).
    XPath: starts with ``//`` or ``/``.
    """
    if not s:
        return False
    # XPath expressions
    if s.startswith(("//", "/")):
        return True
    # CSS selectors starting with #, ., [
    if s[0] in (".", "#", "["):
        return True
    # Tag-prefixed CSS: e.g. "div[attr='val']", "input.class", "p#id"
    for ch in s:
        if ch in ("[", ".", "#"):
            return True
        if not (ch.isalnum() or ch in ("-", "_")):
            break
    return False


# Index of the candidate whose rendered text (innerText, line by line) holds *target*.
# exact: a line or the whole text equals it — else the first hidden candidate (the
# caller waits for it to show, as before), else -1. Partial: a line equal to it,
# else a line containing it, else the whole text containing it; -1 when none does.
# textContent glues cells together ("1 | 2 | 3" reads "123"); innerText does not.
_VISIBLE_TEXT_JS = """(els, [target, exact]) => {
  const norm = s => (s || '').replace(/\\s+/g, ' ').trim().toLowerCase();
  const want = norm(target);
  let line = -1, whole = -1, hidden = -1;
  for (let i = 0; i < els.length && i < 50; i++) {
    const el = els[i];
    if (!el.getClientRects().length) { if (hidden < 0) hidden = i; continue; }
    const text = norm(el.innerText);
    const lines = (el.innerText || '').split('\\n').map(norm);
    if (lines.includes(want) || (exact && text === want)) return i;
    if (exact) continue;
    if (line < 0 && lines.some(l => l.includes(want))) line = i;
    if (whole < 0 && text.includes(want)) whole = i;
  }
  return exact ? hidden : (line >= 0 ? line : whole);
}"""


def visible_text_match(candidates: Locator, target: str, exact: bool = False) -> Locator | None:
    """The candidate whose rendered text holds *target* (see _VISIBLE_TEXT_JS), or None."""
    index = candidates.evaluate_all(_VISIBLE_TEXT_JS, [target, exact])
    return candidates.nth(index) if index >= 0 else None


class FallbackLocator:
    """Resolves element locators with progressively looser strategies."""

    _RESOLVE_TIMEOUT_S = 5.0    # max seconds to poll for element appearance
    _POLL_INTERVAL_MS  = 200    # ms between poll cycles

    def resolve_clickable(self, page: Page, target: str) -> Resolution | None:
        """The control *target* names (click_target.resolve: raises when it is
        ambiguous or absent); a selector from the flow is used as written."""
        if _is_selector(target):
            loc = self._try(lambda: page.locator(target))
            return Resolution(loc, "element", target, target, "selector given in the flow") if loc else None
        return resolve_click_target(page, target, self._RESOLVE_TIMEOUT_S, self._POLL_INTERVAL_MS)

    def resolve_input(self, page: Page, target: str) -> Locator | None:
        if _is_selector(target):
            return self._try(lambda: page.locator(target))
        return self._resolve_with_poll(page, [
            lambda: page.get_by_label(target),
            lambda: page.get_by_placeholder(target),
            lambda: page.get_by_role("textbox", name=target, exact=True),
            lambda: page.get_by_role("textbox", name=target),
        ]) or self._fuzzy_input(page, target)

    def resolve_checkbox(self, page: Page, target: str) -> Locator | None:
        return self._resolve_with_poll(page, [
            lambda: page.get_by_label(target),
            lambda: page.get_by_role("checkbox", name=target),
            lambda: page.get_by_role("radio", name=target),
        ])

    # ── helpers ───────────────────────────────────────────────────────────

    def _resolve_with_poll(
        self,
        page: Page,
        strategies: list[Callable],
    ) -> Locator | None:
        """Cycle through strategies with bounded polling.

        First pass is instant (no wait). If nothing is found, polls at
        short intervals until the element appears or the timeout expires.
        This catches elements rendered after AJAX or animations without
        adding delay when the element already exists.
        """
        deadline = time.monotonic() + self._RESOLVE_TIMEOUT_S

        while True:
            for strategy in strategies:
                loc = self._try(strategy)
                if loc is not None:
                    return loc

            if time.monotonic() >= deadline:
                return None

            page.wait_for_timeout(self._POLL_INTERVAL_MS)

    @staticmethod
    def _try(strategy) -> Locator | None:
        try:
            loc = strategy()
            if loc is not None and loc.count() > 0:
                return loc.first
        except Exception:
            pass
        return None

    _FUZZY_MIN = 0.6

    @classmethod
    def _best_fuzzy(cls, page: Page, css: str, target: str):
        """The node matching *css* whose text is most similar to *target*.

        One DOM serialisation + one parse per call. Returns ``None`` when no
        node reaches the similarity floor or selectolax is unavailable.
        """
        try:
            from selectolax.parser import HTMLParser
        except ImportError:
            logger.warning("[L2] selectolax not installed — fuzzy HTML matching disabled")
            return None
        tree = HTMLParser(page.content())
        best_score, best = cls._FUZZY_MIN, None
        for node in tree.css(css):
            text = node.text(strip=True)
            if text:
                score = _similarity(target, text)
                if score > best_score:
                    best_score, best = score, node
        if best is not None:
            logger.debug("[L2] Fuzzy match %r -> %r (%.2f)", target, best.text(strip=True), best_score)
        return best

    def _fuzzy_input(self, page: Page, target: str) -> Locator | None:
        try:
            node = self._best_fuzzy(page, "label", target)
            for_id = node.attributes.get("for") if node is not None else None
            if for_id:
                return self._try(lambda: page.locator(f"#{for_id}"))
        except Exception as exc:
            logger.debug("[L2] fuzzy_input error: %s", exc)
        return None
