"""
Deterministic Runner (Layer 1 + Layer 2).

Layer 1 uses exact Playwright role/label/placeholder locators.
On failure, Layer 2 (FallbackLocator) is tried automatically.
Raises if both fail — caller may then try Layer 3 (AI).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from playwright.sync_api import Locator, Page

from app.config.settings import settings
from app.layers.blockers import dismiss_blockers
from app.layers.deterministic_l2 import L2Handlers
from app.layers.locator import FallbackLocator, _is_selector
from app.schemas.actions import ActionType, FlowAction, RunContext, StepResult

logger = logging.getLogger(__name__)


class DeterministicRunner(L2Handlers):
    # L1 action timeout (ms) — caps Playwright's auto-wait for action calls
    # (click, fill, check, etc.) so L2/L3 can be tried quickly on failure.
    # Playwright still performs all actionability checks (visible, stable,
    # enabled, receives events) within this window — it returns as soon as
    # the element is ready, only hitting the ceiling when the element is
    # truly missing.  The page's default_timeout (30s) is preserved for
    # explicit waits and assertions.
    _L1_TIMEOUT = 5000
    # Playwright already polls actionability for the whole _L1_TIMEOUT window,
    # so a second identical window rarely changes the outcome and doubled the
    # cost of every genuinely missing element (10.5 s before L2 could start).
    _MAX_L1_RETRIES = 1
    _RETRY_PAUSE_MS = 500

    def __init__(
        self,
        page: Page,
        artifacts_dir: str | Path | None = None,
        ctx: RunContext | None = None,
    ):
        self.page = page
        self.artifacts_dir = Path(artifacts_dir) if artifacts_dir else settings.images_dir
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self._locator = FallbackLocator()
        self._shot_counter = 0
        self._ctx = ctx

        # ── L1 dispatch table: one `_h_<keyword>` method per ActionType ──
        # (AI-native actions live in AIResolver, run_flow in the engine.)
        # tests/_framework/test_deterministic_registry.py checks coverage.
        self._l1_handlers: dict[ActionType, Callable[[FlowAction], StepResult]] = {
            t: getattr(self, f"_h_{t.value}")
            for t in ActionType if hasattr(self, f"_h_{t.value}")
        }

        # ── L2 dispatch table (handlers live in deterministic_l2.py) ──
        self._l2_handlers = self._build_l2_handlers()

    # ── Public entry point ────────────────────────────────────────

    def execute(self, action: FlowAction) -> StepResult:
        """Execute action with Layer 1 (bounded retry); auto-fallback to Layer 2."""
        last_exc: Exception | None = None

        for attempt in range(1, self._MAX_L1_RETRIES + 1):
            try:
                if settings.dismiss_blockers:
                    dismiss_blockers(self.page)
                return self._layer1(action)
            except Exception as exc:
                last_exc = exc
                if attempt < self._MAX_L1_RETRIES:
                    logger.debug("[L1] Step %s attempt %s failed, retrying in %sms: %s",
                                 action.step_num, attempt, self._RETRY_PAUSE_MS, exc)
                    self.page.wait_for_timeout(self._RETRY_PAUSE_MS)

        # %-style: Playwright errors carry multi-KB call logs — only format at DEBUG.
        logger.debug("[L1] Step %s failed after %s attempt(s): %s",
                     action.step_num, self._MAX_L1_RETRIES, last_exc)
        return self._layer2(action, original_error=str(last_exc))

    # ── Layer 1 — dispatch ────────────────────────────────────────

    def _layer1(self, action: FlowAction) -> StepResult:
        handler = self._l1_handlers.get(action.type)
        if not handler:
            raise ValueError(f"No L1 handler for {action.type.value}")
        return handler(action)

    # Which L1 resolver an action's first argument goes through — for locate().
    _CLICKABLE = frozenset({ActionType.CLICK, ActionType.CLICK_LINK_TEXT,
                            ActionType.DOUBLE_CLICK, ActionType.RIGHT_CLICK, ActionType.HOVER})
    _INPUT = frozenset({ActionType.FILL, ActionType.TYPE, ActionType.CLEAR,
                        ActionType.FOCUS, ActionType.SELECT})
    _CHECKABLE = frozenset({ActionType.CHECK, ActionType.UNCHECK, ActionType.ASSERT_CHECKED})
    _TEXTUAL = frozenset({ActionType.ASSERT_TEXT, ActionType.ASSERT_VISIBLE,
                          ActionType.ASSERT_HIDDEN, ActionType.WAIT_FOR_TEXT,
                          ActionType.ASSERT_ENABLED, ActionType.ASSERT_DISABLED})

    def locate(self, action: FlowAction) -> Locator | None:
        """The element *action* targets, when L1's exact resolver still finds one.

        No waiting — one ``count()`` round-trip. Used for the failed-element
        screenshot: a click on a covered or disabled button fails, but the
        button is there to photograph. ``None`` when the action has no
        element target or nothing matches.
        """
        if not action.args:
            return None
        target, t = action.args[0], action.type
        try:
            if t in self._CLICKABLE:
                loc = self._resolve_clickable_l1(target)
            elif t in self._INPUT:
                loc = self._resolve_input_l1(target)
            elif t in self._CHECKABLE:
                loc = self._resolve_checkable_l1(target)
            elif t in self._TEXTUAL:
                loc = self._resolve_text_target(target)
            else:
                return None
            return loc.first if loc.count() > 0 else None
        except Exception:
            return None

    # ── L1 handlers: Navigation ───────────────────────────────────

    def _h_goto(self, action: FlowAction) -> StepResult:
        self.page.goto(action.args[0], wait_until="domcontentloaded")
        return self._ok(action, f"Opened {action.args[0]}", 1)

    def _h_reload(self, action: FlowAction) -> StepResult:
        self.page.reload(wait_until="domcontentloaded")
        return self._ok(action, "Page reloaded", 1)

    def _h_back(self, action: FlowAction) -> StepResult:
        self.page.go_back(wait_until="domcontentloaded")
        return self._ok(action, "Navigated back", 1)

    def _h_wait_load(self, action: FlowAction) -> StepResult:
        state = action.args[0] if action.args else "domcontentloaded"
        self.page.wait_for_load_state(state)
        return self._ok(action, f"Waited for load state '{state}'", 1)

    def _h_switch_tab(self, action: FlowAction) -> StepResult:
        idx = int(action.args[0])
        pages = self.page.context.pages
        if idx >= len(pages):
            raise ValueError(f"Tab index {idx} out of range (have {len(pages)} tabs)")
        self.page = pages[idx]
        return self._ok(action, f"Switched to tab {idx}", 1)

    def _h_scroll(self, action: FlowAction) -> StepResult:
        direction = action.args[0].lower() if action.args else "down"
        if direction in ("down", "bottom"):
            self.page.keyboard.press("End")
        elif direction in ("up", "top"):
            self.page.keyboard.press("Home")
        elif direction.lstrip("-").isdigit():
            self.page.mouse.wheel(0, int(direction))
        elif _is_selector(direction):
            # Scroll to element by CSS/XPath selector
            self.page.locator(direction).first.scroll_into_view_if_needed()
        else:
            # Scroll to element by text
            loc = self.page.get_by_text(direction, exact=False)
            if loc.count() == 0:
                raise AssertionError(f'Element with text "{direction}" not found for scroll.')
            loc.first.scroll_into_view_if_needed()
        return self._ok(action, f"Scrolled {direction}", 1)

    # ── L1 handlers: Click ────────────────────────────────────────

    def _resolve_clickable_l1(self, target: str):
        """Selector, else exact button → link → text (shared by click variants)."""
        if _is_selector(target):
            return self.page.locator(target)
        loc = self.page.get_by_role("button", name=target, exact=True)
        if loc.count() == 0:
            loc = self.page.get_by_role("link", name=target, exact=True)
        if loc.count() == 0:
            loc = self.page.get_by_text(target, exact=True)
        return loc

    def _h_click(self, action: FlowAction) -> StepResult:
        target = action.args[0]
        self._resolve_clickable_l1(target).first.click(timeout=self._L1_TIMEOUT)
        return self._ok(action, f"Clicked '{target}'", 1)

    def _h_click_link_text(self, action: FlowAction) -> StepResult:
        target = action.args[0]
        self.page.get_by_role("link", name=target, exact=True).first.click(timeout=self._L1_TIMEOUT)
        return self._ok(action, f"Clicked link '{target}'", 1)

    def _h_double_click(self, action: FlowAction) -> StepResult:
        target = action.args[0]
        self._resolve_clickable_l1(target).first.dblclick(timeout=self._L1_TIMEOUT)
        return self._ok(action, f'Double-clicked "{target}"', 1)

    def _h_right_click(self, action: FlowAction) -> StepResult:
        target = action.args[0]
        self._resolve_clickable_l1(target).first.click(button="right", timeout=self._L1_TIMEOUT)
        return self._ok(action, f'Right-clicked "{target}"', 1)

    def _h_hover(self, action: FlowAction) -> StepResult:
        target = action.args[0]
        if _is_selector(target):
            self.page.locator(target).first.hover(timeout=self._L1_TIMEOUT)
        else:
            self.page.get_by_text(target, exact=True).first.hover(timeout=self._L1_TIMEOUT)
        return self._ok(action, f"Hovered '{target}'", 1)

    # ── L1 handlers: Input ────────────────────────────────────────

    def _resolve_input_l1(self, target: str):
        """Resolve an input/textarea by label, placeholder, or CSS selector."""
        if _is_selector(target):
            return self.page.locator(target)
        loc = self.page.get_by_label(target, exact=True)
        if loc.count() == 0:
            loc = self.page.get_by_placeholder(target, exact=True)
        return loc

    def _h_fill(self, action: FlowAction) -> StepResult:
        label = action.args[0]
        value = action.args[1] if len(action.args) > 1 else ""
        self._resolve_input_l1(label).first.fill(value, timeout=self._L1_TIMEOUT)
        return self._ok(action, f"Filled '{label}' = '{value}'", 1)

    def _h_type(self, action: FlowAction) -> StepResult:
        label = action.args[0]
        value = action.args[1] if len(action.args) > 1 else ""
        self._resolve_input_l1(label).first.press_sequentially(value, timeout=self._L1_TIMEOUT)
        return self._ok(action, f"Typed '{value}' into '{label}'", 1)

    def _h_clear(self, action: FlowAction) -> StepResult:
        label = action.args[0]
        self._resolve_input_l1(label).first.clear(timeout=self._L1_TIMEOUT)
        return self._ok(action, f'Cleared "{label}"', 1)

    def _h_focus(self, action: FlowAction) -> StepResult:
        label = action.args[0]
        self._resolve_input_l1(label).first.focus(timeout=self._L1_TIMEOUT)
        return self._ok(action, f'Focused "{label}"', 1)

    def _h_select(self, action: FlowAction) -> StepResult:
        label = action.args[0]
        option = action.args[1] if len(action.args) > 1 else ""
        if _is_selector(label):
            self.page.locator(label).first.select_option(option, timeout=self._L1_TIMEOUT)
        else:
            loc = self.page.get_by_label(label, exact=True)
            if loc.count() == 0:
                loc = self.page.get_by_role("combobox", name=label, exact=True)
            loc.first.select_option(option, timeout=self._L1_TIMEOUT)
        return self._ok(action, f"Selected '{option}' in '{label}'", 1)

    def _resolve_checkable_l1(self, target: str):
        """Resolve a checkbox or radio by CSS selector, label, or role."""
        if _is_selector(target):
            return self.page.locator(target)
        loc = self.page.get_by_label(target, exact=True)
        if loc.count() == 0:
            loc = self.page.get_by_role("radio", name=target, exact=True)
        if loc.count() == 0:
            loc = self.page.get_by_role("checkbox", name=target, exact=True)
        return loc

    def _h_check(self, action: FlowAction) -> StepResult:
        target = action.args[0]
        self._resolve_checkable_l1(target).first.check(timeout=self._L1_TIMEOUT)
        return self._ok(action, f"Checked '{target}'", 1)

    def _h_uncheck(self, action: FlowAction) -> StepResult:
        target = action.args[0]
        self._resolve_checkable_l1(target).first.uncheck(timeout=self._L1_TIMEOUT)
        return self._ok(action, f"Unchecked '{target}'", 1)

    # ── L1 handlers: Advanced ─────────────────────────────────────

    def _h_drag_to(self, action: FlowAction) -> StepResult:
        source, target = action.args[0], action.args[1]
        src_loc = self.page.locator(source).first if _is_selector(source) else self.page.get_by_text(source).first
        tgt_loc = self.page.locator(target).first if _is_selector(target) else self.page.get_by_text(target).first
        src_loc.drag_to(tgt_loc, timeout=self._L1_TIMEOUT)
        return self._ok(action, f'Dragged "{source}" to "{target}"', 1)

    def _h_upload(self, action: FlowAction) -> StepResult:
        selector, filepath = action.args[0], action.args[1]
        self.page.locator(selector).set_input_files(filepath)
        return self._ok(action, f'Uploaded "{filepath}" to "{selector}"', 1)

    # ── L1 handlers: Table/Data ───────────────────────────────────

    def _h_read_row(self, action: FlowAction) -> StepResult:
        text = action.args[0]
        row = self.page.locator(f'tr:has-text("{text}")').first
        row.wait_for(state="visible", timeout=5000)
        cells = row.locator("td, th").all_text_contents()
        cell_str = " | ".join(cells)
        if self._ctx is not None:
            self._ctx.store(f"row_{text}", cell_str)
        return self._ok(action, f"Row [{text}]: {cells}", 1)

    def _h_table_click(self, action: FlowAction) -> StepResult:
        row_text = action.args[0]
        click_target = action.args[1] if len(action.args) > 1 else None
        row = self.page.locator(f'tr:has-text("{row_text}")').first
        row.wait_for(state="visible", timeout=5000)
        if click_target:
            row.get_by_text(click_target).first.click()
        else:
            row.click()
        msg = f'Clicked in row "{row_text}"'
        if click_target:
            msg += f' on "{click_target}"'
        return self._ok(action, msg, 1)

    def _h_find_row(self, action: FlowAction) -> StepResult:
        text = action.args[0]
        loc = self.page.locator(f'tr:has-text("{text}")')
        if loc.count() == 0:
            raise AssertionError(f'No table row containing "{text}" found.')
        return self._ok(action, f'Found row with "{text}"', 1)

    def _h_count_elements(self, action: FlowAction) -> StepResult:
        selector = action.args[0]
        count = self.page.locator(selector).count()
        if self._ctx is not None:
            self._ctx.store(f"count_{selector}", str(count))
        return self._ok(action, f'Count("{selector}") = {count}', 1)

    def _h_get_attribute(self, action: FlowAction) -> StepResult:
        selector, attr_name = action.args[0], action.args[1]
        value = self.page.locator(selector).first.get_attribute(attr_name)
        if self._ctx is not None and value is not None:
            self._ctx.store(f"attr_{attr_name}", value)
        return self._ok(action, f'{selector}[{attr_name}] = "{value}"', 1)

    # ── L1 handlers: Assertions ───────────────────────────────────

    def _h_assert_text(self, action: FlowAction) -> StepResult:
        expected = action.args[0]
        self.page.get_by_text(expected).first.wait_for(state="visible", timeout=5000)
        return self._ok(action, f"Text '{expected}' visible", 1)

    def _h_assert_not_text(self, action: FlowAction) -> StepResult:
        text = action.args[0]
        loc = self.page.get_by_text(text, exact=False)
        if loc.count() == 0 or loc.first.is_hidden():
            return self._ok(action, f'Text "{text}" is absent/hidden', 1)
        raise AssertionError(f'Text "{text}" is still visible on the page.')

    def _resolve_text_target(self, target: str):
        """Selector, else partial text match (visibility assertions)."""
        return (self.page.locator(target) if _is_selector(target)
                else self.page.get_by_text(target, exact=False))

    def _h_assert_visible(self, action: FlowAction) -> StepResult:
        target = action.args[0]
        self._resolve_text_target(target).first.wait_for(state="visible", timeout=5000)
        return self._ok(action, f'Element "{target}" is visible', 1)

    def _h_assert_hidden(self, action: FlowAction) -> StepResult:
        target = action.args[0]
        loc = self._resolve_text_target(target)
        if loc.count() == 0 or loc.first.is_hidden():
            return self._ok(action, f'Element "{target}" is not visible', 1)
        raise AssertionError(f'Element "{target}" is still visible.')

    def _h_assert_url(self, action: FlowAction) -> StepResult:
        fragment = action.args[0]
        url = self.page.url
        if fragment.lower() not in url.lower():
            raise AssertionError(f"URL '{url}' does not contain '{fragment}'")
        return self._ok(action, f"URL contains '{fragment}'", 1)

    def _assert_disabled_state(self, action: FlowAction, expect_disabled: bool) -> StepResult:
        """Shared body of assert_enabled / assert_disabled."""
        target = action.args[0]
        if _is_selector(target):
            loc = self.page.locator(target)
        else:
            loc = self.page.get_by_role("button", name=target)
            if loc.count() == 0:
                loc = self.page.get_by_text(target, exact=True)
        loc.first.wait_for(state="visible", timeout=5000)
        disabled = loc.first.is_disabled()
        if disabled != expect_disabled:
            state = "disabled" if disabled else "enabled"
            raise AssertionError(f'Element "{target}" is {state}.')
        return self._ok(action, f'Element "{target}" is {"disabled" if disabled else "enabled"}', 1)

    def _h_assert_enabled(self, action: FlowAction) -> StepResult:
        return self._assert_disabled_state(action, expect_disabled=False)

    def _h_assert_disabled(self, action: FlowAction) -> StepResult:
        return self._assert_disabled_state(action, expect_disabled=True)

    def _h_assert_checked(self, action: FlowAction) -> StepResult:
        target = action.args[0]
        if _is_selector(target):
            loc = self.page.locator(target)
        else:
            loc = self.page.get_by_label(target, exact=True)
            if loc.count() == 0:
                loc = self.page.get_by_role("checkbox", name=target, exact=True)
        loc.first.wait_for(state="visible", timeout=5000)
        if not loc.first.is_checked():
            raise AssertionError(f'Checkbox "{target}" is not checked.')
        return self._ok(action, f'Checkbox "{target}" is checked', 1)

    # ── L1 handlers: Waits ────────────────────────────────────────

    def _h_wait(self, action: FlowAction) -> StepResult:
        ms = int(action.args[0]) if action.args and action.args[0].isdigit() else 1000
        self.page.wait_for_timeout(ms)
        return self._ok(action, f"Waited {ms} ms", 1)

    def _h_wait_for_element(self, action: FlowAction) -> StepResult:
        selector = action.args[0]
        self.page.locator(selector).first.wait_for(state="visible")
        return self._ok(action, f"Element '{selector}' visible", 1)

    def _h_wait_for_text(self, action: FlowAction) -> StepResult:
        text = action.args[0]
        self.page.get_by_text(text, exact=False).first.wait_for(state="visible", timeout=10000)
        return self._ok(action, f'Text "{text}" appeared', 1)

    def _h_wait_for_url(self, action: FlowAction) -> StepResult:
        fragment = action.args[0]
        self.page.wait_for_url(lambda url: fragment.lower() in url.lower(), timeout=10000)
        return self._ok(action, f'URL contains "{fragment}"', 1)

    # ── L1 handlers: Utilities ────────────────────────────────────

    def _h_screenshot(self, action: FlowAction) -> StepResult:
        name = action.args[0] if action.args else f"step_{action.step_num}"
        path = self._screenshot(name)
        return self._ok(action, f"Screenshot saved: {path}", 1, screenshot=path)

    def _h_press(self, action: FlowAction) -> StepResult:
        key = action.args[0] if action.args else "Enter"
        self.page.keyboard.press(key)
        return self._ok(action, f'Pressed key "{key}"', 1)

    # ── helpers ───────────────────────────────────────────────────

    def _ok(
        self,
        action: FlowAction,
        message: str,
        layer: int,
        screenshot: str | None = None,
    ) -> StepResult:
        logger.info(f"[L{layer}] Step {action.step_num}: {message}")
        return StepResult(
            action=action, success=True, message=message,
            layer_used=layer, screenshot_path=screenshot,
        )

    def _screenshot(self, name: str) -> str:
        self._shot_counter += 1
        safe = name.replace("/", "_").replace(" ", "_")
        path = self.artifacts_dir.resolve() / f"{self._shot_counter:03d}_{safe}.png"
        self.page.screenshot(path=str(path), full_page=False)
        return str(path)
