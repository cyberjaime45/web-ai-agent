"""Skill runtime — how a QA skill runs inside a flow.

A skill is a function ``fn(sc: SkillContext) -> list[Check]``. It looks at
the page through ``sc.observe()`` / ``sc.evaluate()``, acts only through
``sc.run(ActionType, *args)`` — the same ``FlowRunner.execute`` path (L1 →
L2 → L3, timing, evidence) every Markdown step takes — and reports what it
found as checks. ``run_skill`` wraps the call into one marker ``StepResult``
(``group=True``, carrying the checks) followed by the child steps, exactly
the shape ``run_flow`` produces, so the report nests them for free.

Child steps come in three kinds (``sc.run(..., kind=)``):

    action   the skill needs it to work; a failure fails the skill
    probe    trying it *is* the test; the skill turns the result into a check,
             and a failed probe is a soft step (a warning, never the flow's failure)
    cleanup  puts the page back (back, Escape, return goto); a failure is soft
             and adds one "page restored after the skill" warning

Every press (click, key, tick, select) counts against one budget shared with
the skills this skill starts — ``sc.run_skill`` hands its budget down through
``engine.run_action(budget=)``, so the chain lives in the call, not in shared
state: ``max_actions`` presses and ``timeout`` seconds
(default 300). Cleanup is never refused. Once a limit is reached ``sc.run``
returns a not-run result (``skipped``) and ``sc.stopped`` says why. Every click
passes the safety policy first, whoever chose it (skill or planner); a refused
click is not run and is listed in the ``blocked by safety`` check.

Verdict of the marker step: failed on a crash, a failed ``error`` check, a
failed action child or a failed nested skill; otherwise passed — with
warnings when a ``warn`` check or a soft child failed.
"""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.agent.observer import Observation, landmarks, observe
from app.agent.planner import PlannedStep, Planner
from app.agent.safety import SafetyPolicy
from app.execution import oracle
from app.observability.evidence import ELEMENT_TIMEOUT_MS
from app.schemas.actions import (
    SKILL_ACTIONS,
    ActionType,
    Check,
    Evidence,
    FlowAction,
    RunContext,
    StepResult,
    summarize,
)

logger = logging.getLogger(__name__)

SkillFn = Callable[["SkillContext"], list[Check]]
SKILLS: dict[ActionType, SkillFn] = {}

_TRUE = ("1", "true", "yes", "on")
DEFAULT_TIMEOUT_S = 300

# Presses count against max_actions; clicks also pass the safety policy first.
CLICKS = frozenset({ActionType.CLICK, ActionType.CLICK_LINK_TEXT, ActionType.DOUBLE_CLICK,
                    ActionType.RIGHT_CLICK})
PRESSES = CLICKS | {ActionType.TABLE_CLICK, ActionType.PRESS, ActionType.CHECK,
                    ActionType.UNCHECK, ActionType.SELECT}
KINDS = ("action", "probe", "cleanup")


def skill(action_type: ActionType) -> Callable[[SkillFn], SkillFn]:
    """Register *fn* as the implementation of a skill keyword."""
    def register(fn: SkillFn) -> SkillFn:
        SKILLS[action_type] = fn
        return fn
    return register


def parse_skill_args(args: list[str]) -> dict[str, str]:
    """``["submit=false", "form=Contact", "Members"]`` → options; a bare value is ``target``."""
    out: dict[str, str] = {}
    for arg in args:
        key, sep, value = arg.partition("=")
        if sep:
            out[key.strip().lower()] = value.strip()
        elif arg.strip():
            out.setdefault("target", arg.strip())
    return out


def info(name: str, detail: str = "") -> Check:
    """An observation — always passed, severity info."""
    return Check(name, True, "info", detail)


def read_number(args: dict[str, str], key: str, default: float, errors: list[str]) -> float:
    """A non-negative number option; a bad value keeps *default* and is noted in *errors*."""
    raw = args.get(key, "")
    if not raw:
        return default
    try:
        if math.isfinite(value := float(raw)) and value >= 0:
            return value
    except ValueError:
        pass
    errors.append(f"{key}={raw} is not a non-negative number; the default applies")
    return default


def skipped(name: str, why: str) -> Check:
    """Work the skill did not do — nothing to exercise, or a limit reached."""
    return Check(name, True, "skipped", why)


def inconclusive(name: str, why: str) -> Check:
    """The agent could not gather enough evidence (it could not press, fill or
    observe something): recorded with the reason, never an application defect."""
    return Check(name, True, "inconclusive", why)


def missing(sc: SkillContext, name: str, what: str, option: str) -> Check:
    """The thing a skill tests is not on the page: an error when the flow named
    it (``option=`` given), otherwise nothing to test here (skipped)."""
    if sc.option(option):
        return Check(name, False, "error", f"{what} matching {option}='{sc.option(option)}' not found")
    return skipped(name, f"no {what} on the page")


@dataclass
class Budget:
    """Presses and time a skill may still spend; a nested skill's budget has
    the caller's as parent, so a limit bounds everything under it."""
    limit: int | None = None             # presses; None = only the parent's limit
    deadline: float | None = None        # time.monotonic() value
    parent: Budget | None = None
    used: int = 0

    def left(self) -> int | None:
        own = None if self.limit is None else self.limit - self.used
        up = self.parent.left() if self.parent else None
        return up if own is None else own if up is None else min(own, up)

    def expired(self) -> bool:
        return (self.deadline is not None and time.monotonic() > self.deadline) or \
            (self.parent is not None and self.parent.expired())

    def take(self) -> None:
        self.used += 1
        if self.parent:
            self.parent.take()


@dataclass
class SkillContext:
    action:   FlowAction
    page:     Any
    runner:   Any                      # DeterministicRunner
    ctx:      RunContext
    engine:   Any                      # FlowRunner
    args:     dict[str, str]
    recorder: Any = None
    ignore:   oracle.IgnoreRules = field(default_factory=oracle.IgnoreRules)
    profile:  str = "desktop"
    policy:   SafetyPolicy = field(default_factory=SafetyPolicy)
    planner:  Planner = field(default_factory=lambda: Planner(None, 0))
    budget:   Budget = field(default_factory=Budget)
    steps:    list[StepResult] = field(default_factory=list)   # child steps, in order
    shots:    dict[str, str] = field(default_factory=dict)     # label → screenshot path
    files:    dict[str, str] = field(default_factory=dict)     # label → other artifact (generated flow)
    agent:    dict[str, Any] = field(default_factory=dict)     # facts for the report's agent panel
    blocked:  list[str] = field(default_factory=list)          # "control — reason" the policy refused
    stopped:  str = ""                                         # why the skill stopped early
    option_errors: list[str] = field(default_factory=list)
    cleanup_failed: list[str] = field(default_factory=list)
    _ob:      Observation | None = None

    # ── options (validated: a bad value is an error check, never a crash) ──
    def option(self, key: str, default: str = "") -> str:
        return self.args.get(key, default)

    def flag(self, key: str, default: bool = False) -> bool:
        value = self.args.get(key)
        return default if value is None else value.lower() in _TRUE

    def number(self, key: str, default: float) -> float:
        return read_number(self.args, key, default, self.option_errors)

    def count(self, key: str, default: int) -> int:
        return int(self.number(key, default))

    # ── acting: always through the engine ──
    def _step(self, action_type: ActionType, args: tuple[str, ...]) -> FlowAction:
        quoted = " | ".join(f'"{a}"' for a in args)
        return FlowAction(type=action_type, args=list(args),
                          raw=f"{action_type.value}: {quoted}" if args else action_type.value,
                          step_num=self.action.step_num, section=self.action.section)

    def _not_run(self, fa: FlowAction, why: str, group: bool = False) -> StepResult:
        """A step that was refused before it ran — returned, never recorded."""
        return StepResult(action=fa, success=False, message=why, layer_used=0,
                          skipped=True, soft=True, group=group)

    def _refuse(self, fa: FlowAction) -> str:
        """Why *fa* must not run now (limits, safety), or ``""``."""
        if not self.stopped:
            if self.budget.expired():
                self.stopped = "time budget reached (timeout)"
            elif fa.type in PRESSES and (left := self.budget.left()) is not None and left <= 0:
                self.stopped = "action limit reached (max_actions)"
        if self.stopped:
            return f"not run — {self.stopped}"
        return self._unsafe(fa)

    def _unsafe(self, fa: FlowAction) -> str:
        """The safety gate every click passes — cleanup included (a dialog's
        "Cancel" can be destructive); ``""`` when allowed."""
        if fa.type not in CLICKS or not fa.args:
            return ""
        verdict = self.policy.verdict(fa.args[0], url=self.page.url)
        if verdict.allowed:
            return ""
        self.block(fa.args[0], verdict.reason)
        return f"not pressed — {verdict.reason}"

    def run(self, action_type: ActionType, *args: str, kind: str = "action") -> StepResult:
        """Execute one action as a child step of this skill (see the module doc for *kind*)."""
        assert kind in KINDS, kind
        fa = self._step(action_type, args)
        if why := (self._unsafe(fa) if kind == "cleanup" else self._refuse(fa)):   # cleanup is never budgeted
            return self._not_run(fa, why)
        if kind != "cleanup" and action_type in PRESSES:
            self.budget.take()
        sr = self.engine.execute(fa, self.page, self.runner, self.ctx)
        sr.sub_flow = self.action.type.value
        if kind == "probe":         # a dialog, or no change, is often what the probe tests; the skill judges it
            sr.checks = [c for c in sr.checks if c.name not in (oracle.DIALOG_CHECK, oracle.EFFECT_CHECK)]
        if not sr.success and kind != "action":
            sr.soft = True
            if kind == "cleanup":
                self.cleanup_failed.append(f"{fa.raw}: {(sr.message or '').splitlines()[0][:120]}")
        if sr.success and kind != "cleanup" and action_type in oracle.ORACLE_AFTER and not sr.after:
            sr.after = landmarks(self.page)      # ORACLE=off: the engine recorded nothing after the step
        self.steps.append(sr)
        self._ob = None          # the page may have changed
        return sr

    def run_skill(self, action_type: ActionType, *args: str) -> StepResult:
        """Run another skill as a nested group; returns its marker step.

        The nested marker is tagged with this skill's name and its children
        with ``<this>/<nested>``, so the report nests them two levels deep.
        Shares this run's recorder, policy, provider and budget.
        """
        fa = self._step(action_type, args)
        if self.stopped or self.budget.expired():
            self.stopped = self.stopped or "time budget reached (timeout)"
            return self._not_run(fa, f"not run — {self.stopped}", group=True)
        results = self.engine.run_action(fa, self.page, self.runner, self.ctx, budget=self.budget)
        outer = self.action.type.value
        for sr in results:
            sr.sub_flow = f"{outer}/{sr.sub_flow}" if sr.sub_flow else outer
        self.steps.extend(results)
        self._ob = None
        # the nested skill's AI calls spend this skill's budget too
        self.planner.calls += int((results[0].agent or {}).get("ai_calls", 0))
        return results[0]

    def run_planned(self, steps: list[PlannedStep]) -> list[tuple[PlannedStep, StepResult]]:
        """Run validated planner steps in order as probes (skills nest as groups,
        always with their safe defaults — a model never passes skill options).
        Stops at the first failure or a limit. Returns what ran."""
        ran: list[tuple[PlannedStep, StepResult]] = []
        for step in steps:
            try:
                action_type = ActionType(step.action)
            except ValueError:
                continue
            if action_type in SKILL_ACTIONS:
                mark = len(self.steps)
                result = self.run_skill(action_type)
                for sr in self.steps[mark:]:    # a model chose it: its failure is a warning, not the flow's
                    sr.soft = sr.soft or sr.fails_flow
            else:
                result = self.run(action_type, *step.args, kind="probe")
            if result.skipped:
                break
            ran.append((step, result))
            if not result.success:
                break
        return ran

    def fail_step(self, sr: StepResult, reason: str, since_seq: int = 0) -> None:
        """The skill judged a step that ran as a defect (a click that led to a
        broken page): that step fails — not soft — with *reason* and its own
        evidence, so the report points at the step where it happened. Evidence
        goes through ``engine.attach_evidence``, the one failure-capture path."""
        sr.success, sr.soft = False, False
        sr.message = sr.error = reason
        sr.evidence = Evidence(layers={self.action.type.value: f"judged a defect: {reason}"[:300]})
        self.engine.attach_evidence(sr, self.page, self.runner, since_seq)

    def out_of_time(self) -> bool:
        """For loops that do not press anything (requests, probes): has the time budget run out?"""
        if not self.stopped and self.budget.expired():
            self.stopped = "time budget reached (timeout)"
        return bool(self.stopped)

    def allowed(self, name: str, **context: str) -> bool:
        """Safety verdict for a control the skill is choosing; a refusal is recorded."""
        verdict = self.policy.verdict(name, url=self.page.url, **context)
        if not verdict.allowed:
            self.block(name, verdict.reason)
        return verdict.allowed

    def block(self, name: str, reason: str) -> None:
        """Record a control the safety policy kept this skill from pressing."""
        entry = f"{name} — {reason}"
        if entry not in self.blocked:
            self.blocked.append(entry)

    def failures_since(self, mark: int) -> list[StepResult]:
        """Child steps recorded after ``mark = len(sc.steps)`` that ran and failed."""
        return [s for s in self.steps[mark:] if not s.success and not s.skipped]

    @property
    def leaf_steps(self) -> list[StepResult]:
        """Child steps that are real actions (no nested markers)."""
        return [s for s in self.steps if not s.group]

    @property
    def child_failed(self) -> bool:
        """A child failed in a way that fails the skill (an action, or a nested skill)."""
        return any(s.fails_flow for s in self.steps)

    # ── looking ──
    def observe(self, fresh: bool = False) -> Observation:
        if self._ob is None or fresh:
            self._ob = observe(self.page)
        return self._ob

    def evaluate(self, js: str, arg: Any = None) -> Any:
        """Best-effort ``page.evaluate``; ``None`` when the page cannot answer."""
        try:
            return self.page.evaluate(js, arg) if arg is not None else self.page.evaluate(js)
        except Exception as exc:
            logger.debug("[skill] evaluate failed: %s", exc)
            return None

    def mark(self) -> int:
        return self.recorder.seq if self.recorder is not None else 0

    def diagnostics(self, since_seq: int) -> list[Check]:
        if self.recorder is None:
            return []
        return oracle.diagnostics_checks(self.recorder, since_seq, self.ignore, explicit=True)

    def screenshot(self, label: str) -> str | None:
        """Viewport shot kept on the skill step as evidence (``label`` → path)."""
        safe = "".join(ch if ch.isalnum() else "_" for ch in label).strip("_") or "shot"
        path = self.engine.evidence_path(f"{self.action.type.value}__{safe}.png")
        try:
            self.page.screenshot(path=str(path), full_page=False, timeout=ELEMENT_TIMEOUT_MS * 2)
        except Exception as exc:
            logger.debug("[skill] screenshot skipped: %s", exc)
            return None
        self.shots[label] = str(path)
        return str(path)


def _runtime_checks(sc: SkillContext) -> list[Check]:
    """What the runtime itself observed: bad options, safety blocks, limits, cleanup."""
    checks: list[Check] = []
    if sc.option_errors:
        checks.append(Check.listing("options valid", sc.option_errors, "error"))
    if sc.blocked:
        checks.append(Check("blocked by safety", True, "blocked", summarize(sc.blocked, 8), len(sc.blocked)))
    if sc.stopped:
        timed_out = "time" in sc.stopped
        checks.append(Check("finished within limits", True, "inconclusive" if timed_out else "skipped",
                            f"stopped early: {sc.stopped}; the remaining checks did not run"))
    if sc.cleanup_failed:       # the agent's own housekeeping, not the application
        checks.append(Check.listing("page restored after the skill", sc.cleanup_failed, "inconclusive"))
    return checks


def run_skill(engine: Any, action: FlowAction, page: Any, runner: Any, ctx: RunContext, *,
              recorder: Any = None, ignore: oracle.IgnoreRules | None = None,
              profile: str = "desktop", policy: SafetyPolicy | None = None,
              provider: Any = None, parent_budget: Budget | None = None) -> list[StepResult]:
    """Marker step (checks, verdict) followed by the child steps the skill ran.
    *parent_budget* is the calling skill's: this skill's limits chain to it."""
    fn = SKILLS.get(action.type)
    w0, t0 = time.time(), time.monotonic()
    since = recorder.seq if recorder is not None else 0
    args = parse_skill_args(action.args)
    errors: list[str] = []
    limit = read_number(args, "max_actions", float("inf"), errors)
    budget = Budget(limit=None if limit == float("inf") else int(limit), parent=parent_budget,
                    deadline=time.monotonic() + read_number(args, "timeout", DEFAULT_TIMEOUT_S, errors))
    sc = SkillContext(action=action, page=page, runner=runner, ctx=ctx, engine=engine,
                      args=args, recorder=recorder, ignore=ignore or oracle.IgnoreRules(),
                      profile=profile, policy=policy or SafetyPolicy(),
                      planner=Planner(provider, int(read_number(args, "max_ai_calls", 3, errors))),
                      budget=budget, option_errors=errors)
    marker = StepResult(action=action, success=True, message="", layer_used=0, group=True)
    crashed = ""
    checks: list[Check] = []
    try:
        if fn is None:
            crashed = f"no implementation registered for '{action.type.value}'"
        else:
            checks = fn(sc)
    except Exception as exc:
        crashed = f"{type(exc).__name__}: {exc}"
        logger.warning("[skill] %s crashed: %s", action.type.value, crashed)

    checks = [*checks, *_runtime_checks(sc)]
    marker.checks = checks
    errors = oracle.failed(checks)
    marker.success = not crashed and not errors and not sc.child_failed
    parts = [oracle.summary(checks)]
    if sc.child_failed:
        parts.append("a child step failed")
    if crashed:
        parts.append(f"skill error: {crashed}")
    if sc.planner.calls:
        parts.append(f"{sc.planner.calls} AI call(s)")
    marker.message = f"{action.type.value}: {'; '.join(parts)}"
    if not marker.success:
        marker.error = "; ".join(
            [c.name + (f" — {c.detail}" if c.detail else "") for c in errors] + parts[1:])
    if sc.shots or sc.files:
        marker.evidence = Evidence(screenshots=dict(sc.shots), files=dict(sc.files))
    if sc.agent or sc.planner.calls:
        marker.agent = {**sc.agent, "ai_calls": sc.planner.calls}
    marker.duration = round(time.monotonic() - t0, 3)
    marker.started_at, marker.ended_at = w0, time.time()
    if not marker.success:
        engine.attach_evidence(marker, page, runner, since)
    logger.info("[skill] %s", marker.message)
    return [marker, *sc.steps]
