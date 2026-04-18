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
import re
import time
import uuid
from pathlib import Path

from playwright.sync_api import Page

from app.schemas.actions import (
    AI_ONLY_ACTIONS,
    ActionType,
    FlowAction,
    FlowResult,
    RunContext,
    StepResult,
)
from app.flow.parser import parse_flow_file, resolve_flow_path
from app.layers.ai_resolver import AIResolver
from app.layers.deterministic import DeterministicRunner
from app.layers.providers import get_provider

logger = logging.getLogger(__name__)

_DEFAULT_IMAGES_DIR = Path("reports") / os.getenv("ENVIRONMENT", "staging") / "images"
_MAX_NESTING_DEPTH = 10

# ── Environment variable placeholder resolution ─────────────────────────────
_ENV_PLACEHOLDER_RE = re.compile(r"^<([A-Z_][A-Z0-9_]*)>$")
_SENSITIVE_KEYWORDS = {"PASSWORD", "SECRET", "KEY", "TOKEN"}
_MASK = "******"


def _is_sensitive(var_name: str) -> bool:
    """Return True if the env var name contains a sensitive keyword."""
    upper = var_name.upper()
    return any(kw in upper for kw in _SENSITIVE_KEYWORDS)


def _resolve_env_placeholders(action: FlowAction) -> FlowAction:
    """Return a copy of *action* with ``<ENV_VAR>`` placeholders resolved.

    - Resolved args contain real values (for execution).
    - ``action.raw`` is rewritten with sensitive values masked as ``******``.
    - Non-sensitive placeholders (e.g. ``<FMS_EMAIL>``) show the resolved value.
    - If the env var is not set, raises ``RuntimeError`` with a helpful message.
    """
    has_placeholder = False
    for arg in action.args:
        if _ENV_PLACEHOLDER_RE.match(arg):
            has_placeholder = True
            break

    if not has_placeholder:
        return action  # nothing to resolve — return original (no copy needed)

    resolved_args: list[str] = []
    masked_raw = action.raw

    for arg in action.args:
        m = _ENV_PLACEHOLDER_RE.match(arg)
        if not m:
            resolved_args.append(arg)
            continue

        var_name = m.group(1)
        value = os.environ.get(var_name)
        if value is None:
            raise RuntimeError(
                f"Environment variable '{var_name}' is not set "
                f"(referenced in step {action.step_num}: {action.raw!r})"
            )

        resolved_args.append(value)
        display = _MASK if _is_sensitive(var_name) else value
        masked_raw = masked_raw.replace(f"<{var_name}>", display)

    return FlowAction(
        type=action.type,
        args=resolved_args,
        raw=masked_raw,
        step_num=action.step_num,
        section=action.section,
    )


def _append_error(result, msg: str) -> None:
    result.error = f"{result.error}\n{msg}" if result.error else msg


class FlowRunner:
    def __init__(
        self,
        artifacts_dir: str | Path = _DEFAULT_IMAGES_DIR,
        flows_dir: str | Path = "flows",
    ):
        self.artifacts_dir = Path(artifacts_dir)
        self.flows_dir = Path(flows_dir)
        self._ai = AIResolver(provider=get_provider())
        self._seen_flows: set[str] = set()
        self._nesting_depth: int = 0

    def run(self, flow, page: Page) -> FlowResult:
        """
        Execute all actions in *flow* against *page*.
        Each section (## heading) is independent: a failure stops the remaining
        steps in that section but execution resumes at the next section boundary.
        """
        result = FlowResult(flow_name=flow.name)
        ctx = RunContext()
        runner = DeterministicRunner(page, artifacts_dir=self.artifacts_dir, ctx=ctx)

        if not flow.actions:
            result.error = "No parsed actions — check flow file format"
            return result

        current_section: str | None = None
        section_failed = False

        for action in flow.actions:
            # ── Section boundary: reset failure flag for fresh section ──
            if action.section != current_section:
                current_section = action.section
                section_failed = False

            # ── Silently skip remaining steps in a failed section ──
            if section_failed:
                continue

            # ── Sub-flow execution ──
            if action.type == ActionType.RUN_FLOW:
                sub_results = self._run_sub_flow(action, page, runner, ctx)
                for sr in sub_results:
                    result.steps.append(sr)
                    if sr.screenshot_path:
                        result.last_screenshot = sr.screenshot_path
                    if not sr.success:
                        _append_error(result, sr.message)
                        logger.error(
                            f"Flow '{flow.name}' failed in sub-flow at step "
                            f"{sr.action.step_num}: {sr.action.raw!r} — {sr.message}"
                        )
                        section_failed = True
                continue

            # ── Resolve env var placeholders before execution ──
            try:
                resolved = _resolve_env_placeholders(action)
            except RuntimeError as exc:
                sr = StepResult(
                    action=action, success=False,
                    message=str(exc), layer_used=0, error=str(exc),
                    screenshot_path=self._capture_failure_screenshot(page),
                )
                result.steps.append(sr)
                _append_error(result, str(exc))
                section_failed = True
                continue

            t0 = time.monotonic()
            step_result = self._run_step(resolved, page, runner, ctx)
            step_result.duration = round(time.monotonic() - t0, 3)
            result.steps.append(step_result)
            ctx.record(action, step_result, page.url, page.title())

            if step_result.screenshot_path:
                result.last_screenshot = step_result.screenshot_path

            if not step_result.success:
                _append_error(result, step_result.message)
                logger.error(
                    f"Flow '{flow.name}' failed at step {action.step_num}: "
                    f"{resolved.raw!r} — {step_result.message}"
                )
                section_failed = True

        result.success = result.failed == 0
        return result

    # ── Failure screenshot ─────────────────────────────────────────

    def _capture_failure_screenshot(self, page: Page) -> str | None:
        """Take a screenshot on step failure. Returns the file path or None."""
        try:
            self.artifacts_dir.mkdir(parents=True, exist_ok=True)
            path = str(
                self.artifacts_dir.resolve() / f"fail_{uuid.uuid4().hex[:12]}.png"
            )
            page.screenshot(path=path, full_page=False)
            logger.debug(f"[Screenshot] Captured failure screenshot: {path}")
            return path
        except Exception as exc:
            logger.warning(f"[Screenshot] Failed to capture screenshot: {exc}")
            return None

    # ── Sub-flow handling ──────────────────────────────────────────

    def _run_sub_flow(
        self,
        action: FlowAction,
        page: Page,
        runner: DeterministicRunner,
        ctx: RunContext,
    ) -> list[StepResult]:
        """Resolve and execute a referenced sub-flow, returning its StepResults."""
        ref = action.args[0]

        # Nesting depth check
        if self._nesting_depth >= _MAX_NESTING_DEPTH:
            return [StepResult(
                action=action, success=False,
                message=f"Max nesting depth ({_MAX_NESTING_DEPTH}) exceeded for '{ref}'",
                layer_used=0,
                screenshot_path=self._capture_failure_screenshot(page),
            )]

        # Circular dependency check
        if ref in self._seen_flows:
            return [StepResult(
                action=action, success=False,
                message=f"Circular flow reference detected: '{ref}'",
                layer_used=0,
                screenshot_path=self._capture_failure_screenshot(page),
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
                screenshot_path=self._capture_failure_screenshot(page),
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
                nested = self._run_sub_flow(sub_action, page, runner, ctx)
                for sr in nested:
                    sr.sub_flow = sr.sub_flow or sub_flow.name
                    results.append(sr)
                    if not sr.success:
                        self._nesting_depth -= 1
                        self._seen_flows.discard(ref)
                        return results
                continue

            # Resolve env var placeholders
            try:
                resolved = _resolve_env_placeholders(sub_action)
            except RuntimeError as exc:
                sr = StepResult(
                    action=sub_action, success=False,
                    message=str(exc), layer_used=0, error=str(exc),
                    screenshot_path=self._capture_failure_screenshot(page),
                )
                sr.sub_flow = sub_flow.name
                results.append(sr)
                break

            t0 = time.monotonic()
            sr = self._run_step(resolved, page, runner, ctx)
            sr.duration = round(time.monotonic() - t0, 3)
            sr.sub_flow = sub_flow.name
            results.append(sr)

            # Record sub-flow step in short-term memory
            ctx.record(sub_action, sr, page.url, page.title())

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
        ctx: RunContext,
    ) -> StepResult:
        # AI-native actions bypass L1/L2 entirely
        if action.type in AI_ONLY_ACTIONS:
            if not self._ai.available:
                logger.warning(
                    f"[L3] Skipped AI action '{action.type.value}' — "
                    "LLM provider not configured"
                )
                return StepResult(
                    action=action, success=False,
                    message=(
                        f"AI action '{action.type.value}' requires AI_PROVIDER, LLM_KEY and LLM_MODEL "
                        "(L3 skipped: provider not configured)"
                    ),
                    layer_used=3,
                    error="LLM provider not configured",
                    screenshot_path=self._capture_failure_screenshot(page),
                )
            ai_result = self._ai.resolve_ai_action(action, page, ctx)
            if ai_result is not None:
                if not ai_result.success and not ai_result.screenshot_path:
                    ai_result.screenshot_path = self._capture_failure_screenshot(page)
                return ai_result
            return StepResult(
                action=action, success=False,
                message=f"AI action failed: {action.type.value}",
                layer_used=3,
                error="AI resolver returned no result",
                screenshot_path=self._capture_failure_screenshot(page),
            )

        try:
            return runner.execute(action)   # Layer 1 → Layer 2 internally
        except Exception as exc:
            error_msg = str(exc)
            logger.warning(
                f"[L1+L2] Step {action.step_num} ({action.type.value} {action.args}) "
                f"failed: {error_msg}"
            )

            # Layer 3 — AI fallback (only if API key is available)
            if self._ai.available:
                ai_result = self._ai.resolve(action, page, error_msg, ctx)
                if ai_result is not None:
                    if not ai_result.success and not ai_result.screenshot_path:
                        ai_result.screenshot_path = self._capture_failure_screenshot(page)
                    return ai_result

                # Single re-prompt with enriched context
                enriched = (
                    f"{error_msg}\n"
                    f"L3 first attempt returned no match. "
                    f"Page URL: {page.url}, Title: {page.title()}"
                )
                logger.debug("[L3] Re-prompting with enriched context")
                ai_retry = self._ai.resolve(action, page, enriched, ctx)
                if ai_retry is not None:
                    if not ai_retry.success and not ai_retry.screenshot_path:
                        ai_retry.screenshot_path = self._capture_failure_screenshot(page)
                    return ai_retry

                # Both L3 attempts failed
                return StepResult(
                    action=action, success=False,
                    message=f"All layers failed: {error_msg}",
                    layer_used=3,
                    error=error_msg,
                    screenshot_path=self._capture_failure_screenshot(page),
                )

            # L3 skipped — report as L2 failure
            logger.info("[L3] Skipped — LLM provider not configured")
            return StepResult(
                action=action, success=False,
                message=f"L1+L2 failed (L3 skipped: provider not configured): {error_msg}",
                layer_used=2,
                error=error_msg,
                screenshot_path=self._capture_failure_screenshot(page),
            )
