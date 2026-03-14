"""
Executor — Takes validated AgentActions and executes them
through the BrowserDriver.
"""

from __future__ import annotations

import logging
import time

from schemas.models import ActionResult, ActionType, AgentAction
from tools.browser.driver import BrowserDriver

logger = logging.getLogger(__name__)


def execute_action(action: AgentAction, driver: BrowserDriver) -> ActionResult:
    """Execute a single validated action and return the result."""
    try:
        if action.action == ActionType.NAVIGATE:
            driver.open_page(action.target or "")
            return ActionResult(
                action=action,
                success=True,
                message=f"Navigated to {action.target}",
            )

        elif action.action == ActionType.CLICK:
            driver.click_button(action.target or "")
            # Brief wait for page to settle after click
            time.sleep(0.5)
            return ActionResult(
                action=action,
                success=True,
                message=f"Clicked '{action.target}'",
            )

        elif action.action == ActionType.FILL:
            driver.fill_input(action.target or "", action.value or "")
            return ActionResult(
                action=action,
                success=True,
                message=f"Filled '{action.target}'",
            )

        elif action.action == ActionType.WAIT:
            wait_ms = int(action.value or "1000")
            time.sleep(wait_ms / 1000)
            return ActionResult(
                action=action,
                success=True,
                message=f"Waited {wait_ms}ms",
            )

        elif action.action == ActionType.ASSERT_TEXT:
            page_text = driver.extract_visible_text()
            expected = action.value or ""
            found = expected.lower() in page_text.lower()
            return ActionResult(
                action=action,
                success=found,
                message=f"Text '{ expected}' {'found' if found else 'NOT found'} on page",
            )

        elif action.action == ActionType.ASSERT_URL:
            current_url = driver.get_current_url()
            expected = action.value or ""
            found = expected.lower() in current_url.lower()
            return ActionResult(
                action=action,
                success=found,
                message=f"URL fragment '{expected}' {'found' if found else 'NOT found'} in {current_url}",
            )

        elif action.action == ActionType.SCREENSHOT:
            path = driver.capture_screenshot(action.target)
            return ActionResult(
                action=action,
                success=True,
                message=f"Screenshot saved to {path}",
                screenshot_path=path,
            )

        elif action.action == ActionType.DONE:
            return ActionResult(
                action=action, success=True, message="Flow completed successfully"
            )

        elif action.action == ActionType.FAIL:
            return ActionResult(
                action=action, success=False, message=f"Flow failed: {action.reason}"
            )

        else:
            return ActionResult(
                action=action,
                success=False,
                message=f"Unhandled action type: {action.action}",
            )

    except Exception as exc:
        logger.error(f"Action execution failed: {exc}")
        screenshot_path = driver.capture_screenshot(f"error_{action.action.value}")
        return ActionResult(
            action=action,
            success=False,
            message=str(exc),
            screenshot_path=screenshot_path,
        )
