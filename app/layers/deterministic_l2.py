"""Layer 2 handlers — fuzzy fallbacks for the DeterministicRunner.

Mixed into ``DeterministicRunner``; every handler returns a ``StepResult``
on success or ``None`` when its looser strategy found nothing, and
``_layer2`` turns that ``None`` into the ``RuntimeError`` the engine expects.
Handlers use the runner's ``page``, ``_locator`` (FallbackLocator), ``_ok``
and ``_L1_TIMEOUT``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from app.schemas.actions import ActionType, FlowAction, StepResult

logger = logging.getLogger(__name__)


class L2Handlers:
    """Fallback-locator handlers, keyed by ActionType in ``_build_l2_handlers``."""

    def _build_l2_handlers(self) -> dict[ActionType, Callable[[FlowAction], StepResult | None]]:
        return {
            ActionType.CLICK:           self._l2_click,
            ActionType.CLICK_LINK_TEXT: self._l2_click,
            ActionType.DOUBLE_CLICK:    self._l2_double_click,
            ActionType.RIGHT_CLICK:     self._l2_right_click,
            ActionType.HOVER:           self._l2_hover,
            ActionType.FILL:            self._l2_fill,
            ActionType.TYPE:            self._l2_type,
            ActionType.CLEAR:           self._l2_clear_focus,
            ActionType.FOCUS:           self._l2_clear_focus,
            ActionType.SELECT:          self._l2_select,
            ActionType.CHECK:           self._l2_check,
            ActionType.UNCHECK:         self._l2_uncheck,
            ActionType.DRAG_TO:         self._l2_drag_to,
            ActionType.ASSERT_TEXT:     self._l2_assert_text,
            ActionType.ASSERT_NOT_TEXT: self._l2_assert_not_text,
            ActionType.ASSERT_VISIBLE:  self._l2_assert_visible,
            ActionType.ASSERT_HIDDEN:   self._l2_assert_hidden,
            ActionType.WAIT_FOR_TEXT:   self._l2_wait_for_text,
            ActionType.SCROLL:          self._l2_scroll,
        }

    # ── Layer 2 — fallback locators ───────────────────────────────

    def _layer2(self, action: FlowAction, original_error: str) -> StepResult:
        t, a = action.type, action.args
        logger.debug(f"[L2] Attempting fallback for '{t.value}' target='{a[0] if a else ''}'")

        handler = self._l2_handlers.get(t)
        if handler:
            result = handler(action)
            if result is not None:
                return result

        raise RuntimeError(
            f"Layers 1+2 could not resolve step {action.step_num} "
            f"({t.value} {a}). Original: {original_error}"
        )

    # ── L2 handlers ───────────────────────────────────────────────

    def _l2_click(self, action: FlowAction) -> StepResult | None:
        loc = self._locator.resolve_clickable(self.page, action.args[0])
        if loc:
            loc.click(timeout=self._L1_TIMEOUT)
            return self._ok(action, f"[L2] Clicked '{action.args[0]}'", 2)
        return None

    def _l2_double_click(self, action: FlowAction) -> StepResult | None:
        loc = self._locator.resolve_clickable(self.page, action.args[0])
        if loc:
            loc.dblclick(timeout=self._L1_TIMEOUT)
            return self._ok(action, f'[L2] Double-clicked "{action.args[0]}"', 2)
        return None

    def _l2_right_click(self, action: FlowAction) -> StepResult | None:
        loc = self._locator.resolve_clickable(self.page, action.args[0])
        if loc:
            loc.click(button="right", timeout=self._L1_TIMEOUT)
            return self._ok(action, f'[L2] Right-clicked "{action.args[0]}"', 2)
        return None

    def _l2_hover(self, action: FlowAction) -> StepResult | None:
        loc = self._locator.resolve_clickable(self.page, action.args[0])
        if loc:
            loc.hover(timeout=self._L1_TIMEOUT)
            return self._ok(action, f'[L2] Hovered "{action.args[0]}"', 2)
        return None

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

    def _l2_clear_focus(self, action: FlowAction) -> StepResult | None:
        loc = self._locator.resolve_input(self.page, action.args[0])
        if loc:
            if action.type == ActionType.CLEAR:
                loc.fill("", timeout=self._L1_TIMEOUT)
                return self._ok(action, f'[L2] Cleared "{action.args[0]}"', 2)
            else:
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
            src.drag_to(dst, timeout=self._L1_TIMEOUT)
            return self._ok(action, f'[L2] Dragged "{action.args[0]}" to "{action.args[1]}"', 2)
        return None

    def _l2_assert_text(self, action: FlowAction) -> StepResult | None:
        if action.args[0].lower() in self.page.content().lower():
            return self._ok(action, f"[L2] Text '{action.args[0]}' found in HTML", 2)
        return None

    def _l2_assert_not_text(self, action: FlowAction) -> StepResult | None:
        if action.args[0].lower() not in self.page.content().lower():
            return self._ok(action, f'[L2] Text "{action.args[0]}" absent from HTML', 2)
        return None

    def _l2_assert_visible(self, action: FlowAction) -> StepResult | None:
        if action.args[0].lower() in self.page.content().lower():
            return self._ok(action, f'[L2] Element "{action.args[0]}" found in HTML', 2)
        return None

    def _l2_assert_hidden(self, action: FlowAction) -> StepResult | None:
        loc = self.page.get_by_text(action.args[0], exact=False)
        if loc.count() == 0 or loc.first.is_hidden():
            return self._ok(action, f'[L2] Element "{action.args[0]}" is not visible', 2)
        return None

    def _l2_wait_for_text(self, action: FlowAction) -> StepResult | None:
        if action.args[0].lower() in self.page.content().lower():
            return self._ok(action, f'[L2] Text "{action.args[0]}" found in HTML', 2)
        return None

    def _l2_scroll(self, action: FlowAction) -> StepResult | None:
        if not action.args:
            return None
        target = action.args[0]
        # Only fallback for scroll-to-element (text targets)
        if target.lower() not in ("up", "down", "top", "bottom") and not target.lstrip("-").isdigit():
            loc = self.page.locator(f':has-text("{target}")').last
            if loc.count() > 0:
                loc.scroll_into_view_if_needed()
                return self._ok(action, f'[L2] Scrolled to "{target}"', 2)
        return None
