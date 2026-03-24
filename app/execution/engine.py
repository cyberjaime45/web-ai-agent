"""
Flow Runner — orchestrates the 3-layer execution loop.

For every FlowAction in the flow:
  Layer 1 + 2 (DeterministicRunner) → if both fail →
  Layer 3 (AIResolver)              → if AI fails →
  Mark step as failed, stop flow.

Supports ``run_flow`` for composing reusable sub-flows.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

from playwright.sync_api import Page

from app.schemas.actions import (
    AI_ONLY_ACTIONS,
    ActionType,
    FlowAction,
    FlowResult,
    StepResult,
)
from app.flow.parser import parse_flow_file, resolve_flow_path
from app.layers.ai_resolver import AIResolver
from app.layers.deterministic import DeterministicRunner

logger = logging.getLogger(__name__)

_DEFAULT_IMAGES_DIR = Path("reports") / os.getenv("ENVIRONMENT", "staging") / "images"
_MAX_NESTING_DEPTH = 10


class FlowRunner:
    def __init__(
        self,
        artifacts_dir: str | Path = _DEFAULT_IMAGES_DIR,
        flows_dir: str | Path = "flows",
    ):
        self.artifacts_dir = Path(artifacts_dir)
        self.flows_dir = Path(flows_dir)
        self._ai = AIResolver()
        self._seen_flows: set[str] = set()
        self._nesting_depth: int = 0

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
            # ── Sub-flow execution ──
            if action.type == ActionType.RUN_FLOW:
                sub_results = self._run_sub_flow(action, page, runner)
                for sr in sub_results:
                    result.steps.append(sr)
                    if sr.screenshot_path:
                        result.last_screenshot = sr.screenshot_path
                    if not sr.success:
                        result.error = sr.message
                        logger.error(
                            f"Flow '{flow.name}' failed in sub-flow at step "
                            f"{sr.action.step_num}: {sr.action.raw!r} — {sr.message}"
                        )
                        return result
                continue

            t0 = time.monotonic()
            step_result = self._run_step(action, page, runner)
            step_result.duration = round(time.monotonic() - t0, 3)
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

    # ── Sub-flow handling ──────────────────────────────────────────

    def _run_sub_flow(
        self,
        action: FlowAction,
        page: Page,
        runner: DeterministicRunner,
    ) -> list[StepResult]:
        """Resolve and execute a referenced sub-flow, returning its StepResults."""
        ref = action.args[0]

        # Nesting depth check
        if self._nesting_depth >= _MAX_NESTING_DEPTH:
            return [StepResult(
                action=action, success=False,
                message=f"Max nesting depth ({_MAX_NESTING_DEPTH}) exceeded for '{ref}'",
                layer_used=0,
            )]

        # Circular dependency check
        if ref in self._seen_flows:
            return [StepResult(
                action=action, success=False,
                message=f"Circular flow reference detected: '{ref}'",
                layer_used=0,
            )]

        # Resolve and parse
        try:
            flow_path = resolve_flow_path(ref, self.flows_dir)
            sub_flow = parse_flow_file(flow_path)
        except Exception as exc:
            return [StepResult(
                action=action, success=False,
                message=f"Failed to load sub-flow '{ref}': {exc}",
                layer_used=0, error=str(exc),
            )]

        logger.info(
            f"[run_flow] Executing sub-flow '{sub_flow.name}' "
            f"({len(sub_flow.actions)} actions)"
        )

        # Marker step for the report
        marker = StepResult(
            action=action, success=True,
            message=f"Running sub-flow: {sub_flow.name}",
            layer_used=0, duration=0.0,
        )

        self._seen_flows.add(ref)
        self._nesting_depth += 1
        results: list[StepResult] = [marker]

        for sub_action in sub_flow.actions:
            # Support nested run_flow
            if sub_action.type == ActionType.RUN_FLOW:
                nested = self._run_sub_flow(sub_action, page, runner)
                for sr in nested:
                    sr.sub_flow = sr.sub_flow or sub_flow.name
                    results.append(sr)
                    if not sr.success:
                        self._nesting_depth -= 1
                        self._seen_flows.discard(ref)
                        return results
                continue

            t0 = time.monotonic()
            sr = self._run_step(sub_action, page, runner)
            sr.duration = round(time.monotonic() - t0, 3)
            sr.sub_flow = sub_flow.name
            results.append(sr)
            if not sr.success:
                break

        self._nesting_depth -= 1
        self._seen_flows.discard(ref)
        return results

    # ── Single step execution ─────────────────────────────────────

    def _run_step(
        self,
        action: FlowAction,
        page: Page,
        runner: DeterministicRunner,
    ) -> StepResult:
        # AI-native actions bypass L1/L2 entirely
        if action.type in AI_ONLY_ACTIONS:
            ai_result = self._ai.resolve_ai_action(action, page)
            if ai_result is not None:
                return ai_result
            return StepResult(
                action=action, success=False,
                message=f"AI action failed: {action.type.value}",
                layer_used=3,
                error="AI resolver returned None (missing API key or LLM error)",
            )

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
