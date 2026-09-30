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
import time
from pathlib import Path

from playwright.sync_api import Page

from app.agent import explainer
from app.agent.safety import SafetyPolicy
from app.config.settings import PROJECT_ROOT, settings
from app.execution import oracle
from app.flow.parser import parse_flow_file, resolve_flow_path
from app.flow.placeholders import resolve_env_placeholders
from app.layers import stability
from app.layers.ai_resolver import AIResolver
from app.layers.deterministic import DeterministicRunner
from app.layers.providers import LLMProvider, get_provider
from app.observability import diagnosis
from app.observability import evidence as evidence_mod
from app.schemas.actions import (
    AI_ONLY_ACTIONS,
    SKILL_ACTIONS,
    ActionType,
    Check,
    Evidence,
    FlowAction,
    FlowResult,
    RunContext,
    StepResult,
)
from app.skills import run_skill

logger = logging.getLogger(__name__)

_MAX_NESTING_DEPTH = 10
_RESOLVE_PROVIDER = object()   # sentinel: FlowRunner(provider=...) not given

# Layer names as they appear in Evidence.layers, in resolution order.
L1, L2, L3 = "L1 exact", "L2 fuzzy", "L3 AI"
_SETTLE_MS = 10_000            # the one bounded wait a still-loading page gets before L1 runs again
SETTLED_CHECK = "page settled in time"

def _append_error(result, msg: str) -> None:
    result.error = f"{result.error}\n{msg}" if result.error else msg


def _first_line(text: str) -> str:
    """Log lines carry the message, not Playwright's multi-KB call log (it is in the report)."""
    return (text or "").split("\nCall log:", 1)[0].splitlines()[0] if text else ""


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
        attempt: int = 1,
    ):
        """*provider*: an LLMProvider to share across runs (one client per
        session), ``None`` to disable L3, or omitted to resolve from settings.
        *profile*: the device profile name, used to label evidence files.
        *attempt*: 2 for a RERUN_FAILED rerun — its evidence files get a
        ``__retry`` suffix so they do not overwrite the first attempt's."""
        self.artifacts_dir = Path(artifacts_dir) if artifacts_dir else settings.images_dir
        self.flows_dir = Path(flows_dir)
        self.profile = profile
        self.attempt = attempt
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
        self._n_shots = 0              # numbers skill screenshots: a skill run twice keeps both sets
        self._section_seq = 0          # recorder mark at the current section's start (diagnosis)
        self._last_state: dict = {}    # page state after the last navigation-class step (effect checks)
        self._last_effect = ""         # note for the next diagnosis: the last press changed nothing
        self._ctx = RunContext()
        self._goal, self._expected = "", []
        self._ai_explanations = 0      # explainer calls this run (≤ explainer.MAX_CALLS)
        self._step_seq = 0             # recorder mark at the current step's start (triage)
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
        self._ctx = ctx
        self._recorder = recorder
        self._goal = flow.title or flow.name          # intent, for the report and the explainer
        self._expected = list(getattr(flow, "expected", []))
        self._ai_explanations = 0
        self._flow_slug = evidence_mod.slugify(flow.name) + ("__retry" if self.attempt > 1 else "")
        self._last_state, self._last_effect = {}, ""
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
                self._section_seq = recorder.seq if recorder is not None else 0

            # ── Record remaining steps of a failed section as skipped ──
            if section_failed:
                result.steps.append(StepResult(
                    action=action, success=False, skipped=True,
                    message="skipped — earlier step in this section failed",
                    layer_used=0,
                ))
                continue

            for sr in self.run_action(action, page, runner, ctx):
                result.steps.append(sr)
                if sr.fails_flow:
                    _append_error(result, sr.message)
                    logger.error("Flow '%s' failed at step %s: %r — %s", flow.name,
                                 sr.action.step_num, sr.action.raw, _first_line(sr.message))
                    section_failed = True

        result.success = result.failed == 0
        return result

    # ── One flow line: a step, or a group (run_flow / skill) ───────

    def run_action(self, action, page, runner, ctx, budget=None) -> list[StepResult]:
        """What one flow line produced: ``[step]``, or a marker step followed by
        its children for ``run_flow`` and skills. The top-level loop, sub-flows
        and skills composing other skills (``SkillContext.run_skill``) all
        dispatch through here. *budget* is the calling skill's (a nested skill
        spends from it); a flow line has none."""
        if action.type == ActionType.RUN_FLOW:
            return self._run_sub_flow(action, page, runner, ctx)
        if action.type in SKILL_ACTIONS:
            return run_skill(self, action, page, runner, ctx, recorder=self._recorder,
                             ignore=self._ignore, profile=self.profile, policy=self._policy,
                             provider=self.provider, parent_budget=budget)
        return [self.execute(action, page, runner, ctx)]

    def evidence_path(self, name: str) -> Path:
        """Where a skill keeps an extra screenshot:
        ``images/<flow>__<profile>__shot<NN>__<name>`` — numbered per run, so a
        skill that runs twice in a flow never overwrites the first step's files."""
        self._n_shots += 1
        return self._artifacts_abs / f"{self._flow_slug}__{self.profile}__shot{self._n_shots:02d}__{name}"

    def generated_path(self, name: str) -> Path:
        """Where a skill writes a generated flow: ``reports/<env>/generated/<flow>__<profile>__<name>.md``."""
        folder = self._artifacts_abs.parent / "generated"
        folder.mkdir(parents=True, exist_ok=True)
        return folder / f"{self._flow_slug}__{self.profile}__{name}.md"

    def baseline_path(self, name: str) -> Path:
        """Where snapshot_page keeps a baseline: ``<flow folder>/baselines/<name>__<profile>.json``,
        reviewed with the flow; ``reports/<env>/baselines/`` for a flow from outside the project."""
        root = self.flows_dir.resolve()
        inside = root != PROJECT_ROOT and root.is_relative_to(PROJECT_ROOT)
        folder = (root if inside else settings.report_dir) / "baselines"
        folder.mkdir(parents=True, exist_ok=True)
        return folder / f"{evidence_mod.slugify(name)}__{self.profile}.json"

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
        if not sr.evidence.diagnosis and not sr.group:
            section: tuple[list, list] = ([], [])
            if self._recorder is not None:
                section = ([c for c in self._recorder.errors_since(self._section_seq, 50)
                            if self._ignore.keeps_console(c)],
                           [n for n in self._recorder.failures_since(self._section_seq, 50)
                            if self._ignore.keeps_network(n)])
            sr.evidence.diagnosis = diagnosis.diagnose(sr, page, section, notes=[self._last_effect] if self._last_effect else None)
            self._explain(sr, page)
        return sr

    def _explain(self, sr: StepResult, page: Page) -> None:
        """One optional LLM call (app/agent/explainer.py) when the deterministic
        diagnosis is unclassified — at most ``explainer.MAX_CALLS`` per flow run.
        The answer is recorded as ``diagnosis["ai"]``; it never changes the verdict
        or the result."""
        d = sr.evidence.diagnosis if sr.evidence else {}
        if (self.provider is None or d.get("verdict") != "unclassified" or "ai" in d
                or self._ai_explanations >= explainer.MAX_CALLS):
            return
        self._ai_explanations += 1
        try:
            from app.agent.observer import observe  # failures only pay for it
            observation = observe(page).to_prompt(2500)
        except Exception:
            observation = ""
        history = [f"{h['action']}({h['target']}) → {h['result']}" for h in self._ctx.recent_history(5)]
        answer = explainer.explain_failure(
            self.provider, goal=self._goal, expected=self._expected, step=sr.action.raw,
            diagnosis=d, layers=dict(sr.evidence.layers), history=history, observation=observation)
        if answer:
            d["ai"] = answer

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

        if self._nesting_depth >= _MAX_NESTING_DEPTH:
            return [self.attach_evidence(_fail(
                action, f"Max nesting depth ({_MAX_NESTING_DEPTH}) exceeded for '{ref}'",
                0, not_attempted), page)]

        if ref in self._seen_flows:
            return [self.attach_evidence(_fail(
                action, f"Circular flow reference detected: '{ref}'", 0, not_attempted), page)]

        try:
            flow_path = resolve_flow_path(ref, self.flows_dir)
            sub_flow = parse_flow_file(flow_path)
        except Exception as exc:
            return [self.attach_evidence(_fail(
                action, f"Failed to load sub-flow '{ref}': {exc}", 0, not_attempted,
                error=str(exc)), page)]

        logger.info("[run_flow] Executing sub-flow '%s' (%d actions)", sub_flow.name, len(sub_flow.actions))

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
        try:
            for sub_action in sub_flow.actions:
                produced = self.run_action(sub_action, page, runner, ctx)
                for sr in produced:
                    sr.sub_flow = sr.sub_flow or sub_flow.name
                results += produced
                if any(sr.fails_flow for sr in produced):
                    break                      # a sub-flow stops at its first failure (a soft one does not count)
        finally:
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
            resolved = resolve_env_placeholders(action)
        except RuntimeError as exc:
            sr = _fail(action, str(exc), 0, {L1: "not attempted (placeholder unresolved)"})
            sr.started_at, sr.ended_at = w0, time.time()
            return self.attach_evidence(sr, page, runner, since_seq)

        t0 = time.monotonic()
        self._step_seq = since_seq
        sr = self._run_step(resolved, page, runner, ctx)
        if sr.success:
            self._verify(sr, page, runner, since_seq)
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

    def _verify(self, sr: StepResult, page: Page, runner: DeterministicRunner, since_seq: int) -> None:
        """Verify stage (ORACLE=warn|strict): execution success is not test success.
        After a navigation-class step one probe gives ``sr.after`` and the oracle
        checks, and a press is compared with the state before it (``effect_check``);
        after an input step the control is read back (``readback_check``). Those are
        warnings; only an oracle ``error`` check fails the step, in strict mode."""
        if settings.oracle == "off":
            return
        t = sr.action.type
        if t in oracle.ORACLE_AFTER:
            if t in oracle.EFFECT_AFTER and self._last_state:      # a re-render may still be on its way
                oracle.wait_for_change(page, self._last_state)
            after, checks = oracle.observe_after(page, self._recorder, since_seq, self._ignore)
            sr.after = after
            requests = self._recorder.requests_since(since_seq) if self._recorder is not None else 0
            if effect := oracle.effect_check(sr.action, self._last_state, after, requests):
                checks.append(effect)
            # A press that changed nothing is what the next failure most often
            # traces back to; keep it as a note for that step's diagnosis.
            self._last_effect = f"the step before, {sr.action.raw}, changed nothing visible on the page" \
                if effect is not None and not effect.passed else ""
            if after:
                self._last_state = after
            sr.checks = [*sr.checks, *checks]
        elif t in oracle.READBACK and sr.layer_used == 1 and runner is not None:   # L1 found it: read it back
            loc = runner.locate(sr.action)
            if loc is not None and (check := oracle.readback_check(sr.action, loc)):
                sr.checks = [*sr.checks, check]
            return
        else:
            return
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
                logger.warning("[L3] Skipped AI action '%s' — LLM provider not configured", action.type.value)
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

        # ── Layer 1 ──
        try:
            return runner.layer1(action)
        except Exception as exc:
            error_msg = str(exc)
        logger.debug("[L1] Step %s failed: %s", action.step_num, _first_line(error_msg))
        layers = {L1: "failed"}

        # ── Triage, then the one recovery that fits (diagnosis.triage): a page
        # still loading gets one bounded wait and a second L1 attempt; a locator
        # problem goes down the chain; a broken page, a sign-in redirect or a
        # covered control gets no retry that could hide it.
        prev_url = ctx.history[-1]["url"] if ctx.history else ""
        cause = diagnosis.triage(error_msg, action, page, self._recorder, self._step_seq,
                                 self._section_seq, self._ignore, prev_url)
        if cause in diagnosis.RETRY_AFTER_SETTLE:
            t0 = time.monotonic()
            unsettled = stability.wait_stable(page, self._recorder, tuple(self._ignore.network), _SETTLE_MS)
            waited = round((time.monotonic() - t0) * 1000)
            layers["recovery"] = f"waited {waited} ms for the page to settle" + (
                f" — it did not settle: {unsettled}" if unsettled else ", then retried L1")
            if not unsettled:
                try:
                    sr = runner.layer1(action)
                    sr.checks.append(Check(SETTLED_CHECK, False, "warn",
                                           f"the step passed only after waiting {waited} ms for the page to settle"))
                    return sr
                except Exception as exc:
                    error_msg = str(exc)
                cause = diagnosis.triage(error_msg, action, page, self._recorder, self._step_seq,
                                         self._section_seq, self._ignore, prev_url)
                cause = f"loading, then {cause}" if cause != "loading" else cause
        layers["triage"] = cause
        final = cause.rsplit(" ", 1)[-1]
        logger.warning("[L1] Step %s (%s %s) failed — %s: %s",
                       action.step_num, action.type.value, action.args, final, _first_line(error_msg))

        # ── Layer 2 ──
        if final not in diagnosis.FULL_CHAIN | diagnosis.L2_ONLY:
            layers[L2] = layers[L3] = f"skipped: {final}"
            return _fail(action, f"L1 failed ({final}): {error_msg}", 1, layers, error=error_msg)
        try:
            return runner.layer2(action, original_error=error_msg)
        except Exception as exc:
            error_msg = str(exc)
        layers[L2] = "failed"

        # ── Layer 3 — AI fallback, only for element interactions (assertions,
        # waits and keys have no L3 path) and only for a locator problem. One
        # call: the prompt carries the URL, title, error and every control.
        if final in diagnosis.L2_ONLY:
            why = f"{final} error on the page"
        elif not self._ai.available:
            why = "provider not configured"
        elif not self._ai.supports(action.type):
            why = "no L3 path for this action"
        else:
            ai_result = self._ai.resolve(action, page, error_msg, ctx, cause=final)
            if ai_result is not None:
                return ai_result
            layers[L3] = "failed"
            return _fail(action, f"All layers failed: {error_msg}", 3, layers, error=error_msg)
        logger.info("[L3] Skipped — %s", why)
        layers[L3] = f"skipped: {why}"
        return _fail(action, f"L1+L2 failed (L3 skipped: {why}): {error_msg}", 2, layers,
                     error=error_msg)
