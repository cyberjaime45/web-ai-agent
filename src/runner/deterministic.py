"""
Deterministic Runner (Layer 1 + Layer 2).

Layer 1 uses exact Playwright role/label/placeholder locators.
On failure, Layer 2 (FallbackLocator) is tried automatically.
Raises if both fail — caller may then try Layer 3 (AI).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout

from runner.actions import ActionType, FlowAction, StepResult
from runner.locator import FallbackLocator

logger = logging.getLogger(__name__)

_DEFAULT_IMAGES_DIR = Path("reports") / os.getenv("ENVIRONMENT", "staging") / "images"


class DeterministicRunner:
    def __init__(self, page: Page, artifacts_dir: str | Path = _DEFAULT_IMAGES_DIR):
        self.page = page
        self.artifacts_dir = Path(artifacts_dir)
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self._locator = FallbackLocator()
        self._shot_counter = 0

    # ── Public entry point ────────────────────────────────────────

    def execute(self, action: FlowAction) -> StepResult:
        """Execute action with Layer 1; auto-fallback to Layer 2 on failure."""
        try:
            return self._layer1(action)
        except (PlaywrightTimeout, AssertionError, Exception) as exc:
            logger.debug(f"[L1] Step {action.step_num} failed: {exc}")
            return self._layer2(action, original_error=str(exc))

    # ── Layer 1 — exact locators ──────────────────────────────────

    def _layer1(self, action: FlowAction) -> StepResult:
        t, a = action.type, action.args

        if t == ActionType.OPEN:
            self.page.goto(a[0], wait_until="domcontentloaded")
            return self._ok(action, f"Opened {a[0]}", 1)

        if t in (ActionType.CLICK, ActionType.CLICK_BUTTON):
            target = a[0]
            loc = self.page.get_by_role("button", name=target, exact=True)
            if loc.count() == 0:
                loc = self.page.get_by_role("link", name=target, exact=True)
            loc.first.click()
            return self._ok(action, f"Clicked '{target}'", 1)

        if t == ActionType.CLICK_LINK:
            target = a[0]
            self.page.get_by_role("link", name=target, exact=True).first.click()
            return self._ok(action, f"Clicked link '{target}'", 1)

        if t == ActionType.FILL:
            label, value = a[0], a[1] if len(a) > 1 else ""
            loc = self.page.get_by_label(label, exact=True)
            if loc.count() == 0:
                loc = self.page.get_by_placeholder(label, exact=True)
            loc.first.fill(value)
            return self._ok(action, f"Filled '{label}' = '{value}'", 1)

        if t == ActionType.SELECT:
            label, option = a[0], a[1] if len(a) > 1 else ""
            loc = self.page.get_by_label(label, exact=True)
            if loc.count() == 0:
                loc = self.page.get_by_role("combobox", name=label, exact=True)
            loc.first.select_option(option)
            return self._ok(action, f"Selected '{option}' in '{label}'", 1)

        if t == ActionType.CHECK:
            target = a[0]
            loc = self.page.get_by_label(target, exact=True)
            if loc.count() == 0:
                loc = self.page.get_by_role("checkbox", name=target, exact=True)
            loc.first.check()
            return self._ok(action, f"Checked '{target}'", 1)

        if t == ActionType.UNCHECK:
            target = a[0]
            loc = self.page.get_by_label(target, exact=True)
            if loc.count() == 0:
                loc = self.page.get_by_role("checkbox", name=target, exact=True)
            loc.first.uncheck()
            return self._ok(action, f"Unchecked '{target}'", 1)

        if t == ActionType.ASSERT_TEXT:
            expected = a[0]
            self.page.get_by_text(expected).first.wait_for(state="visible", timeout=5000)
            return self._ok(action, f"Text '{expected}' visible", 1)

        if t == ActionType.ASSERT_TITLE:
            expected = a[0]
            title = self.page.title()
            if expected.lower() not in title.lower():
                raise AssertionError(f"Title '{title}' does not contain '{expected}'")
            return self._ok(action, f"Title contains '{expected}'", 1)

        if t == ActionType.ASSERT_URL:
            fragment = a[0]
            url = self.page.url
            if fragment.lower() not in url.lower():
                raise AssertionError(f"URL '{url}' does not contain '{fragment}'")
            return self._ok(action, f"URL contains '{fragment}'", 1)

        if t == ActionType.WAIT:
            ms = int(a[0]) if a and a[0].isdigit() else 1000
            self.page.wait_for_timeout(ms)
            return self._ok(action, f"Waited {ms} ms", 1)

        if t == ActionType.WAIT_FOR_LOAD:
            self.page.wait_for_load_state("domcontentloaded")
            return self._ok(action, "Page load complete", 1)

        if t == ActionType.WAIT_FOR_ELEMENT:
            selector = a[0]
            self.page.locator(selector).first.wait_for(state="visible")
            return self._ok(action, f"Element '{selector}' visible", 1)

        if t == ActionType.SCREENSHOT:
            name = a[0] if a else f"step_{action.step_num}"
            path = self._screenshot(name)
            return self._ok(action, f"Screenshot saved: {path}", 1, screenshot=path)

        if t == ActionType.SCROLL:
            direction = a[0].lower() if a else "down"
            if direction in ("down", "bottom"):
                self.page.keyboard.press("End")
            elif direction in ("up", "top"):
                self.page.keyboard.press("Home")
            elif direction.lstrip("-").isdigit():
                self.page.mouse.wheel(0, int(direction))
            return self._ok(action, f"Scrolled {direction}", 1)

        if t == ActionType.HOVER:
            target = a[0]
            self.page.get_by_text(target, exact=True).first.hover()
            return self._ok(action, f"Hovered '{target}'", 1)

        raise ValueError(f"Unsupported action: {t}")

    # ── Layer 2 — fallback locators ───────────────────────────────

    def _layer2(self, action: FlowAction, original_error: str) -> StepResult:
        t, a = action.type, action.args
        logger.debug(f"[L2] Attempting fallback for '{t.value}' target='{a[0] if a else ''}'")

        if t in (ActionType.CLICK, ActionType.CLICK_BUTTON, ActionType.CLICK_LINK):
            loc = self._locator.resolve_clickable(self.page, a[0])
            if loc:
                loc.click()
                return self._ok(action, f"[L2] Clicked '{a[0]}'", 2)

        elif t == ActionType.FILL:
            loc = self._locator.resolve_input(self.page, a[0])
            if loc:
                loc.fill(a[1] if len(a) > 1 else "")
                return self._ok(action, f"[L2] Filled '{a[0]}'", 2)

        elif t == ActionType.ASSERT_TEXT:
            # Content search — look in raw HTML
            if a[0].lower() in self.page.content().lower():
                return self._ok(action, f"[L2] Text '{a[0]}' found in HTML", 2)

        raise RuntimeError(
            f"Layers 1+2 could not resolve step {action.step_num} "
            f"({t.value} {a}). Original: {original_error}"
        )

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
        path = self.artifacts_dir / f"{self._shot_counter:03d}_{safe}.png"
        self.page.screenshot(path=str(path), full_page=False)
        return str(path)
