"""
Agent Runner — Orchestrates the full execution cycle:
  1. Parse flow
  2. Extract page state
  3. Plan next action(s)
  4. Validate via guardrails
  5. Execute
  6. Repeat until done or max steps
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from agent.executor import execute_action
from agent.flow_parser import FlowDefinition
from agent.guardrails import GuardrailError, validate_action
from agent.brain import AgentResponse, get_planner
from schemas.models import ActionResult, ActionType
from tools.browser.driver import BrowserDriver
from tools.browser.extractors import extract_page_state

logger = logging.getLogger(__name__)


@dataclass
class RunResult:
    """Result of running a complete flow."""

    flow_name: str
    success: bool = False
    steps_executed: int = 0
    action_log: list[ActionResult] = field(default_factory=list)
    error: str = ""


def run_flow(
    flow: FlowDefinition,
    driver: BrowserDriver,
    max_steps: int = 20,
    planner_fn: Callable | None = None,
) -> RunResult:
    """
    Execute a complete flow using the agent loop.

    Args:
        flow: Parsed flow definition
        driver: Browser driver instance
        max_steps: Safety limit on iteration count
        planner_fn: Optional override for the planner function
    """
    planner = planner_fn or get_planner()
    result = RunResult(flow_name=flow.name)
    step_index = 0
    history: list[str] = []

    for iteration in range(max_steps):
        logger.info(f"\n{'='*60}")
        logger.info(f"Iteration {iteration + 1} | Step index: {step_index}")

        # 1. Extract page state
        page_state = extract_page_state(driver)
        logger.info(f"Page: {page_state.url} | Title: {page_state.title}")

        # 2. Plan next action(s)
        response: AgentResponse = planner(flow, page_state, step_index, history)
        logger.info(f"Planner summary: {response.summary}")

        if response.is_complete:
            result.success = True
            logger.info("Flow marked as complete by planner")
            break

        # 3. Execute each action
        for action in response.actions:
            logger.info(f"Action: {action.action.value} | Target: {action.target} | Reason: {action.reason}")

            # 3a. Guardrail check
            try:
                validate_action(action, page_state)
            except GuardrailError as exc:
                logger.warning(f"Guardrail blocked action: {exc}")
                history.append(f"BLOCKED: {action.action.value} {action.target} — {exc}")
                result.action_log.append(
                    ActionResult(action=action, success=False, message=str(exc))
                )
                continue

            # 3b. Execute
            action_result = execute_action(action, driver)
            result.action_log.append(action_result)
            result.steps_executed += 1
            history.append(
                f"{'OK' if action_result.success else 'FAIL'}: "
                f"{action.action.value} {action.target or ''} — {action_result.message}"
            )

            logger.info(f"Result: {'OK' if action_result.success else 'FAIL'} — {action_result.message}")

            # Check for terminal actions
            if action.action == ActionType.DONE:
                result.success = True
                return result
            if action.action == ActionType.FAIL:
                result.success = False
                result.error = action_result.message
                return result

            # If an assertion failed, don't mark as success
            if not action_result.success and action.action in (
                ActionType.ASSERT_TEXT,
                ActionType.ASSERT_URL,
            ):
                result.success = False
                result.error = action_result.message

        # Advance step index
        step_index += 1
        if step_index >= len(flow.steps):
            result.success = result.error == ""
            logger.info("All flow steps processed")
            break

    # Capture final screenshot
    driver.capture_screenshot(f"{flow.name}_final")
    return result
