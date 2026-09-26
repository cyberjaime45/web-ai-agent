"""
Flow Runner — orchestrates the 3-layer execution loop.

For every FlowAction in the flow:
  Layer 1 + 2 (DeterministicRunner) → if both fail →
  Layer 3 (AIResolver)              → if AI fails →
  Mark step as failed, collect evidence, stop the section.

Supports ``run_flow`` for composing reusable sub-flows. ``execute`` is the
public single-step entry point: skills and other Python callers run an action
through the same L1 → L2 → L3 chain, timing and evidence as a Markdown step.
"""

from __future__ import annotations

import logging
import os
import re
import time
from pathlib import Path

from playwright.sync_api import Page

from app.agent.safety import SafetyPolicy
from app.config.settings import settings
from app.execution import oracle
from app.observability import evidence as evidence_mod
from app.schemas.actions import (
    AI_ONLY_ACTIONS,
    SKILL_ACTIONS,
    ActionType,
    Evidence,
    FlowAction,
    FlowResult,
    RunContext,
    StepResult,
)
from app.flow.parser import parse_flow_file, resolve_flow_path
from app.layers.ai_resolver import AIResolver
from app.layers.deterministic import DeterministicRunner
from app.layers.providers import LLMProvider, get_provider
from app.skills import run_skill

logger = logging.getLogger(__name__)

_MAX_NESTING_DEPTH = 10
_RESOLVE_PROVIDER = object()   # sentinel: FlowRunner(provider=...) not given

# Layer names as they appear in Evidence.layers, in resolution order.
L1, L2, L3 = "L1 exact", "L2 fuzzy", "L3 AI"

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


def _fail(action: FlowAction, message: str, layer: int, layers: dict[str, str],
          error: str | None = None) -> StepResult:
    """A failed StepResult carrying what each layer did; evidence completes it."""
    return StepResult(
        action=action, success=False, message=message, layer_used=layer,
        error=error if error is not None else message,
        evidence=Evidence(layers=layers),
    )


class FlowRunner:
    def __init__(
        self,
        artifacts_dir: str | Path | None = None,
        flows_dir: str | Path = "tests",
        provider: LLMProvider | None | object = _RESOLVE_PROVIDER,
        profile: str = "desktop",
    ):
        """*provider*: an LLMProvider to share across runs (one client per
        session), ``None`` to disable L3, or omitted to resolve from settings.
        *profile*: the device profile name, used to label evidence files."""
        self.artifacts_dir = Path(artifacts_dir) if artifacts_dir else settings.images_dir
        self.flows_dir = Path(flows_dir)
        self.profile = profile
        if provider is _RESOLVE_PROVIDER:
            provider = get_provider()
        self.provider = provider           # shared by L3 and the skills' planner
        self._ai = AIResolver(provider=provider)
        # Created once here; evidence capture only formats names.
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self._artifacts_abs = self.artifacts_dir.resolve()
        self._seen_flows: set[str] = set()
        self._nesting_depth: int = 0
        self._recorder = None          # PageRecorder for the current run (optional)
        self._flow_slug = "flow"
        self._n_failures = 0           # numbers the evidence files of one run
        self._ignore = oracle.IgnoreRules()
        self._policy = SafetyPolicy()

    def run(self, flow, page: Page, recorder=None) -> FlowResult:
        """
        Execute all actions in *flow* against *page*.
        Each section (## heading) is independent: a failure stops the remaining
        steps in that section but execution resumes at the next section boundary.
        *recorder* (a PageRecorder attached to *page*) lets failure evidence and
        the oracle see the console errors and failed requests of each step.
        """
        result = FlowResult(flow_name=flow.name)
        ctx = RunContext()
        self._recorder = recorder
        self._flow_slug = evidence_mod.slugify(flow.name)
        self._ignore = oracle.IgnoreRules(list(getattr(flow, "ignore_console", [])),
                                          list(getattr(flow, "ignore_network", [])))
        runner = DeterministicRunner(page, artifacts_dir=self.artifacts_dir, ctx=ctx,
                                     recorder=recorder, ignore_network=tuple(self._ignore.network))
        allow = getattr(flow, "allow_destructive", None)
        self._policy = SafetyPolicy(
            destructive_allowed=settings.allow_destructive if allow is None else allow,
            allow=tuple(getattr(flow, "allow_actions", [])),
        )

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

            # ── Record remaining steps of a failed section as skipped ──
            if section_failed:
                result.steps.append(StepResult(
                    action=action, success=False, skipped=True,
                    message="skipped — earlier step in this section failed",
                    layer_used=0,
                ))
                continue

            # ── Sub-flow and skill execution: a marker step plus child steps ──
            if action.type == ActionType.RUN_FLOW or action.type in SKILL_ACTIONS:
                sub_results = self._run_group(action, page, runner, ctx)
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

            step_result = self.execute(action, page, runner, ctx)
            result.steps.append(step_result)
            if step_result.screenshot_path:
                result.last_screenshot = step_result.screenshot_path
            if not step_result.success:
                _append_error(result, step_result.message)
                logger.error(
                    "Flow '%s' failed at step %s: %r — %s",
                    flow.name, action.step_num, step_result.action.raw, step_result.message,
                )
                section_failed = True

        result.success = result.failed == 0
        return result

    # ── Grouped steps: run_flow and skills ─────────────────────────

    def run_group(self, action, page, runner, ctx) -> list[StepResult]:
        """Run a run_flow or skill action: marker step + child steps. Skills
        composing other skills (test_page) call this through SkillContext."""
        return self._run_group(action, page, runner, ctx)

    def _run_group(self, action, page, runner, ctx) -> list[StepResult]:
        if action.type == ActionType.RUN_FLOW:
            return self._run_sub_flow(action, page, runner, ctx)
        return run_skill(self, action, page, runner, ctx, recorder=self._recorder,
                         ignore=self._ignore, profile=self.profile, policy=self._policy,
                         provider=self.provider)

    def evidence_path(self, name: str) -> Path:
        """Where a skill keeps an extra screenshot: ``images/<flow>__<profile>__<name>``."""
        return self._artifacts_abs / f"{self._flow_slug}__{self.profile}__{name}"

    def generated_path(self, name: str) -> Path:
        """Where a skill writes a generated flow: ``reports/<env>/generated/<flow>__<profile>__<name>.md``."""
        folder = self._artifacts_abs.parent / "generated"
        folder.mkdir(parents=True, exist_ok=True)
        return folder / f"{self._flow_slug}__{self.profile}__{name}.md"

    # ── Failure evidence ───────────────────────────────────────────

    def attach_evidence(self, sr: StepResult, page: Page,
                        runner: DeterministicRunner | None = None,
                        since_seq: int = 0) -> StepResult:
        """Complete a failed step's evidence bundle (screenshots, page state,
        diagnostics). Safe to call twice — captures already present are kept.
        conftest uses it for the flow-end fallback when the failure site could
        not be captured (page navigating, crash)."""
        if sr.success or sr.skipped:
            return sr
        if sr.evidence is None:
            sr.evidence = Evidence(layers={f"L{sr.layer_used}": "failed"} if sr.layer_used else {})
        if not sr.evidence.screenshots:
            self._n_failures += 1
        stem = f"{self._flow_slug}__{self.profile}__{self._n_failures:02d}"
        locator = runner.locate(sr.action) if runner is not None else None
        evidence_mod.collect(
            page, self._artifacts_abs, stem, evidence=sr.evidence, profile=self.profile,
            recorder=self._recorder, since_seq=since_seq, locator=locator,
        )
        if not sr.screenshot_path:
            sr.screenshot_path = sr.evidence.screenshots.get("viewport")
        return sr

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
        not_attempted = {L1: "not attempted (sub-flow could not start)"}

        # Nesting depth check
        if self._nesting_depth >= _MAX_NESTING_DEPTH:
            return [self.attach_evidence(_fail(
                action, f"Max nesting depth ({_MAX_NESTING_DEPTH}) exceeded for '{ref}'",
                0, not_attempted), page)]

        # Circular dependency check
        if ref in self._seen_flows:
            return [self.attach_evidence(_fail(
                action, f"Circular flow reference detected: '{ref}'", 0, not_attempted), page)]

        # Resolve and parse
        try:
            flow_path = resolve_flow_path(ref, self.flows_dir)
            sub_flow = parse_flow_file(flow_path)
        except Exception as exc:
            return [self.attach_evidence(_fail(
                action, f"Failed to load sub-flow '{ref}': {exc}", 0, not_attempted,
                error=str(exc)), page)]

        logger.info(
            f"[run_flow] Executing sub-flow '{sub_flow.name}' "
            f"({len(sub_flow.actions)} actions)"
        )

        # Marker step for the report
        marker = StepResult(
            action=action, success=True,
            message=f"Running sub-flow: {sub_flow.name}",
            layer_used=0, duration=0.0, group=True,
            started_at=time.time(), ended_at=time.time(),
        )

        self._seen_flows.add(ref)
        self._nesting_depth += 1
        results: list[StepResult] = [marker]

        for sub_action in sub_flow.actions:
            # Support nested run_flow and skills inside a sub-flow
            if sub_action.type == ActionType.RUN_FLOW or sub_action.type in SKILL_ACTIONS:
                nested = self._run_group(sub_action, page, runner, ctx)
                for sr in nested:
                    sr.sub_flow = sr.sub_flow or sub_flow.name
                    results.append(sr)
                    if not sr.success:
                        self._nesting_depth -= 1
                        self._seen_flows.discard(ref)
                        return results
                continue

            sr = self.execute(sub_action, page, runner, ctx)
            sr.sub_flow = sub_flow.name
            results.append(sr)
            if not sr.success:
                break

        self._nesting_depth -= 1
        self._seen_flows.discard(ref)
        return results

    # ── Single step execution ─────────────────────────────────────

    def execute(
        self,
        action: FlowAction,
        page: Page,
        runner: DeterministicRunner,
        ctx: RunContext,
    ) -> StepResult:
        """Run one action through L1 → L2 → L3 and return its StepResult.

        The one place a step is resolved, timed, recorded and — on failure —
        given its evidence bundle. Top-level steps, sub-flow steps and skills
        all go through here so their results carry the same fields.
        """
        w0 = time.time()
        since_seq = self._recorder.seq if self._recorder is not None else 0
        try:
            resolved = _resolve_env_placeholders(action)
        except RuntimeError as exc:
            sr = _fail(action, str(exc), 0, {L1: "not attempted (placeholder unresolved)"})
            sr.started_at, sr.ended_at = w0, time.time()
            return self.attach_evidence(sr, page, runner, since_seq)

        t0 = time.monotonic()
        sr = self._run_step(resolved, page, runner, ctx)
        if sr.success:
            self._oracle(sr, page, since_seq)
        sr.duration = round(time.monotonic() - t0, 3)
        sr.started_at = w0
        sr.ended_at = time.time()
        try:
            sr.url = page.url
        except Exception:
            sr.url = ""
        if not sr.success:
            self.attach_evidence(sr, page, runner, since_seq)
        ctx.record(action, sr, sr.url)
        return sr

    def _oracle(self, sr: StepResult, page: Page, since_seq: int) -> None:
        """Automatic checks after a navigation-class step (ORACLE=warn|strict)."""
        if settings.oracle == "off" or sr.action.type not in oracle.ORACLE_AFTER:
            return
        sr.checks = [*sr.checks, *oracle.run_checks(page, self._recorder, since_seq, self._ignore)]
        errors = oracle.failed(sr.checks)
        if errors and settings.oracle == "strict":
            sr.success = False
            sr.layer_used = sr.layer_used or 1
            sr.error = "; ".join(f"{c.name}: {c.detail}" if c.detail else c.name for c in errors)
            sr.message = f"{sr.message} — oracle: {oracle.summary(sr.checks)}"
            sr.evidence = Evidence(layers={"oracle": "strict check failed"})

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
                return _fail(
                    action,
                    f"AI action '{action.type.value}' requires AI_PROVIDER, LLM_KEY and LLM_MODEL "
                    "(L3 skipped: provider not configured)",
                    3, {L3: "skipped: provider not configured"},
                    error="LLM provider not configured",
                )
            ai_result = self._ai.resolve_ai_action(action, page, ctx)
            if ai_result is not None:
                if not ai_result.success and ai_result.evidence is None:
                    ai_result.evidence = Evidence(layers={L3: "failed"})
                return ai_result
            return _fail(action, f"AI action failed: {action.type.value}", 3,
                         {L3: "failed"}, error="AI resolver returned no result")

        try:
            return runner.execute(action)   # Layer 1 → Layer 2 internally
        except Exception as exc:
            error_msg = str(exc)
            logger.warning(
                f"[L1+L2] Step {action.step_num} ({action.type.value} {action.args}) "
                f"failed: {error_msg}"
            )
            layers = {L1: "failed", L2: "failed"}

            # Layer 3 — AI fallback, only for actions L3 can actually perform
            # (element interactions). Assertions/waits/keys have no L3 path:
            # sending them would cost two LLM calls and could not change the
            # outcome.
            if self._ai.available and self._ai.supports(action.type):
                ai_result = self._ai.resolve(action, page, error_msg, ctx)
                if ai_result is not None:
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
                    return ai_retry

                # Both L3 attempts failed
                layers[L3] = "failed"
                return _fail(action, f"All layers failed: {error_msg}", 3, layers, error=error_msg)

            # L3 skipped — report as L2 failure
            why = "provider not configured" if not self._ai.available else "no L3 path for this action"
            logger.info("[L3] Skipped — %s", why)
            layers[L3] = f"skipped: {why}"
            return _fail(action, f"L1+L2 failed (L3 skipped: {why}): {error_msg}", 2, layers,
                         error=error_msg)
