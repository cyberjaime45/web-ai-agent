"""Layer 2 handlers — fuzzy fallbacks for the DeterministicRunner.

Mixed into ``DeterministicRunner`` and registered by name, like L1: a method
``_l2_<keyword>`` is the fallback for that ``ActionType``. Every handler
returns a ``StepResult`` on success or ``None`` when its looser strategy
found nothing, and ``_layer2`` turns that ``None`` into the ``RuntimeError``
the engine expects. Handlers use the runner's ``page``, ``_locator``
(FallbackLocator), ``_ok`` and ``_L1_TIMEOUT``.

Element actions retry with looser locators (partial names, labels,
placeholders, a similarity pass). Text checks fall back to the page's
rendered text (``body.innerText``: visible text only, case-insensitive,
whitespace collapsed) — never the raw HTML, where hidden elements and
scripts would make an absent text look present.
"""

from __future__ import annotations

import logging
import re

from app.layers.locator import _is_selector
from app.schemas.actions import FlowAction, StepResult

logger = logging.getLogger(__name__)

_SPACES = re.compile(r"\s+")


def _norm(text: str) -> str:
    return _SPACES.sub(" ", text or "").strip().lower()


class L2Handlers:
    """Fallback handlers; ``DeterministicRunner`` builds ``_l2_handlers`` from the ``_l2_`` names."""

    # ── Layer 2 — dispatch ────────────────────────────────────────

    def _layer2(self, action: FlowAction, original_error: str) -> StepResult:
        t, a = action.type, action.args
        logger.debug("[L2] Attempting fallback for '%s' target='%s'", t.value, a[0] if a else "")
        handler = self._l2_handlers.get(t)
        if handler:
            result = handler(action)
            if result is not None:
                return result
        raise RuntimeError(
            f"Layers 1+2 could not resolve step {action.step_num} "
            f"({t.value} {a}). Original: {original_error}"
        )

    def _visible_text_has(self, text: str) -> bool:
        """*text* appears in the page's rendered, visible text."""
        try:
            return _norm(text) in _norm(self.page.locator("body").inner_text(timeout=self._L1_TIMEOUT))
        except Exception:
            return False

    # ── element actions ───────────────────────────────────────────

    def _l2_press(self, action: FlowAction, verb: str, act) -> StepResult | None:
        """Click-like actions: act on the one control L2 resolves, and record
        what it was — the report says what was pressed, not the step's words."""
        res = self._locator.resolve_clickable(self.page, action.args[0])
        if res is None:
            return None
        act(res.locator)
        sr = self._ok(action, f'[L2] {verb} {res.role} "{res.name}" for "{action.args[0]}"', 2)
        sr.resolved = res.summary
        return sr

    def _l2_click(self, action: FlowAction) -> StepResult | None:
        return self._l2_press(action, "Clicked", lambda loc: loc.click(timeout=self._L1_TIMEOUT))

    _l2_click_link_text = _l2_click

    def _l2_double_click(self, action: FlowAction) -> StepResult | None:
        return self._l2_press(action, "Double-clicked", lambda loc: loc.dblclick(timeout=self._L1_TIMEOUT))

    def _l2_right_click(self, action: FlowAction) -> StepResult | None:
        return self._l2_press(action, "Right-clicked", lambda loc: loc.click(button="right", timeout=self._L1_TIMEOUT))

    def _l2_hover(self, action: FlowAction) -> StepResult | None:
        return self._l2_press(action, "Hovered", lambda loc: loc.hover(timeout=self._L1_TIMEOUT))

    def _l2_fill(self, action: FlowAction) -> StepResult | None:
        loc = self._locator.resolve_input(self.page, action.args[0])
        if loc:
            loc.fill(action.args[1] if len(action.args) > 1 else "", timeout=self._L1_TIMEOUT)
            return self._ok(action, f"[L2] Filled '{action.args[0]}'", 2)
        return None

    def _l2_type(self, action: FlowAction) -> StepResult | None:
        loc = self._locator.resolve_input(self.page, action.args[0])
        if loc:
            loc.press_sequentially(action.args[1] if len(action.args) > 1 else "", timeout=self._L1_TIMEOUT)
            return self._ok(action, f"[L2] Typed into '{action.args[0]}'", 2)
        return None

    def _l2_clear(self, action: FlowAction) -> StepResult | None:
        loc = self._locator.resolve_input(self.page, action.args[0])
        if loc:
            loc.fill("", timeout=self._L1_TIMEOUT)
            return self._ok(action, f'[L2] Cleared "{action.args[0]}"', 2)
        return None

    def _l2_focus(self, action: FlowAction) -> StepResult | None:
        loc = self._locator.resolve_input(self.page, action.args[0])
        if loc:
            loc.focus(timeout=self._L1_TIMEOUT)
            return self._ok(action, f'[L2] Focused "{action.args[0]}"', 2)
        return None

    def _l2_select(self, action: FlowAction) -> StepResult | None:
        loc = self._locator.resolve_input(self.page, action.args[0])
        if loc:
            loc.select_option(action.args[1] if len(action.args) > 1 else "", timeout=self._L1_TIMEOUT)
            return self._ok(action, f"[L2] Selected in '{action.args[0]}'", 2)
        return None

    def _l2_check(self, action: FlowAction) -> StepResult | None:
        loc = self._locator.resolve_checkbox(self.page, action.args[0])
        if loc:
            loc.check(timeout=self._L1_TIMEOUT)
            return self._ok(action, f"[L2] Checked '{action.args[0]}'", 2)
        return None

    def _l2_uncheck(self, action: FlowAction) -> StepResult | None:
        loc = self._locator.resolve_checkbox(self.page, action.args[0])
        if loc:
            loc.uncheck(timeout=self._L1_TIMEOUT)
            return self._ok(action, f"[L2] Unchecked '{action.args[0]}'", 2)
        return None

    def _l2_drag_to(self, action: FlowAction) -> StepResult | None:
        src = self._locator.resolve_clickable(self.page, action.args[0])
        dst = self._locator.resolve_clickable(self.page, action.args[1])
        if src and dst:
            src.locator.drag_to(dst.locator, timeout=self._L1_TIMEOUT)
            sr = self._ok(action, f'[L2] Dragged {src.role} "{src.name}" to {dst.role} "{dst.name}"', 2)
            sr.resolved = f"from {src.summary}; to {dst.summary}"
            return sr
        return None

    def _l2_scroll(self, action: FlowAction) -> StepResult | None:
        target = action.args[0] if action.args else ""
        # Only scroll-to-element (a text target) has a looser strategy.
        if not target or target.lower() in ("up", "down", "top", "bottom") or target.lstrip("-").isdigit():
            return None
        loc = self.page.locator(f':has-text("{target}")').last
        if loc.count() > 0:
            loc.scroll_into_view_if_needed()
            return self._ok(action, f'[L2] Scrolled to "{target}"', 2)
        return None

    # ── text checks: the rendered text, never the HTML ────────────

    def _l2_assert_text(self, action: FlowAction) -> StepResult | None:
        if self._visible_text_has(action.args[0]):
            return self._ok(action, f"[L2] Text '{action.args[0]}' found in the page's visible text", 2)
        return None

    _l2_wait_for_text = _l2_assert_text

    def _l2_assert_visible(self, action: FlowAction) -> StepResult | None:
        if _is_selector(action.args[0]):
            return None
        return self._l2_assert_text(action)

    def _l2_assert_not_text(self, action: FlowAction) -> StepResult | None:
        if not self._visible_text_has(action.args[0]):
            return self._ok(action, f'[L2] Text "{action.args[0]}" absent from the visible text', 2)
        return None
