"""
Flow Runner — orchestrates the 3-layer execution loop.

For every FlowAction in the flow:
  Layer 1 + 2 (DeterministicRunner) → if both fail →
  Layer 3 (AIResolver)              → if AI fails →
  Mark step as failed, stop flow.
"""

from __future__ import annotations

import logging
from pathlib import Path

from playwright.sync_api import Page

from runner.actions import FlowAction, FlowResult, StepResult
from runner.ai_resolver import AIResolver
from runner.deterministic import DeterministicRunner

logger = logging.getLogger(__name__)


class FlowRunner:
    def __init__(self, artifacts_dir: str | Path = "reports/staging"):
        self.artifacts_dir = Path(artifacts_dir)
        self._ai = AIResolver()

    def run(self, flow, page: Page) -> FlowResult:
        """
        Execute all actions in *flow* against *page*.
        Stops on the first failed step.
        """
        result = FlowResult(flow_name=flow.name)
        runner = DeterministicRunner(page, artifacts_dir=self.artifacts_dir)

        if not flow.actions:
            result.error = "No parsed actions — check flow file format"
            return result

        for action in flow.actions:
            step_result = self._run_step(action, page, runner)
            result.steps.append(step_result)

            if step_result.screenshot_path:
                result.last_screenshot = step_result.screenshot_path

            if not step_result.success:
                result.error = step_result.message
                logger.error(
                    f"Flow '{flow.name}' failed at step {action.step_num}: "
                    f"{action.raw!r} — {step_result.message}"
                )
                return result

        result.success = True
        return result

    def _run_step(
        self,
        action: FlowAction,
        page: Page,
        runner: DeterministicRunner,
    ) -> StepResult:
        try:
            return runner.execute(action)   # Layer 1 → Layer 2 internally
        except Exception as exc:
            error_msg = str(exc)
            logger.warning(
                f"[L1+L2] Step {action.step_num} ({action.type.value} {action.args}) "
                f"failed: {error_msg}"
            )

            # Layer 3 — AI
            ai_result = self._ai.resolve(action, page, error_msg)
            if ai_result is not None:
                return ai_result

            return StepResult(
                action=action,
                success=False,
                message=f"All layers failed: {error_msg}",
                layer_used=3,
                error=error_msg,
            )
