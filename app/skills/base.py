"""Skill runtime — how a QA skill runs inside a flow.

A skill is a function ``fn(sc: SkillContext) -> list[Check]``. It looks at
the page through ``sc.observe()`` / ``sc.evaluate()``, acts only through
``sc.run(ActionType, *args)`` — the same ``FlowRunner.execute`` path (L1 →
L2 → L3, timing, evidence) every Markdown step takes — and reports what it
found as checks. ``run_skill`` wraps the call into one marker ``StepResult``
(``group=True``, carrying the checks) followed by the child steps, exactly
the shape ``run_flow`` produces, so the report nests them for free.

A skill step fails when a child step failed or an error-severity check did
not pass; warnings never fail it.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.agent.observer import Observation, observe
from app.agent.planner import Planner
from app.agent.safety import SafetyPolicy
from app.execution import oracle
from app.observability.evidence import ELEMENT_TIMEOUT_MS
from app.schemas.actions import ActionType, Check, Evidence, FlowAction, RunContext, StepResult

logger = logging.getLogger(__name__)

SkillFn = Callable[["SkillContext"], list[Check]]
SKILLS: dict[ActionType, SkillFn] = {}

_TRUE = ("1", "true", "yes", "on")


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
    steps:    list[StepResult] = field(default_factory=list)   # child steps, in order
    shots:    dict[str, str] = field(default_factory=dict)     # label → screenshot path
    files:    dict[str, str] = field(default_factory=dict)     # label → other artifact (generated flow)
    agent:    dict[str, Any] = field(default_factory=dict)     # facts for the report's agent panel
    _ob:      Observation | None = None

    # ── options ──
    def option(self, key: str, default: str = "") -> str:
        return self.args.get(key, default)

    def flag(self, key: str, default: bool = False) -> bool:
        value = self.args.get(key)
        return default if value is None else value.lower() in _TRUE

    # ── acting: always through the engine ──
    def run(self, action_type: ActionType, *args: str) -> StepResult:
        """Execute one action as a child step of this skill."""
        quoted = " | ".join(f'"{a}"' for a in args)
        fa = FlowAction(type=action_type, args=list(args),
                        raw=f"{action_type.value}: {quoted}" if args else action_type.value,
                        step_num=self.action.step_num, section=self.action.section)
        sr = self.engine.execute(fa, self.page, self.runner, self.ctx)
        sr.sub_flow = self.action.type.value
        self.steps.append(sr)
        self._ob = None          # the page may have changed
        return sr

    def run_skill(self, action_type: ActionType, *args: str) -> StepResult:
        """Run another skill as a nested group; returns its marker step.

        The nested marker is tagged with this skill's name and its children
        with ``<this>/<nested>``, so the report nests them two levels deep.
        Shares this run's recorder, policy and provider through the engine.
        """
        quoted = " | ".join(f'"{a}"' for a in args)
        fa = FlowAction(type=action_type, args=list(args),
                        raw=f"{action_type.value}: {quoted}" if args else action_type.value,
                        step_num=self.action.step_num, section=self.action.section)
        results = self.engine.run_group(fa, self.page, self.runner, self.ctx)
        outer = self.action.type.value
        for sr in results:
            sr.sub_flow = f"{outer}/{sr.sub_flow}" if sr.sub_flow else outer
        self.steps.extend(results)
        self._ob = None
        return results[0]

    @property
    def leaf_steps(self) -> list[StepResult]:
        """Child steps that are real actions (no nested markers)."""
        return [s for s in self.steps if not s.group]

    @property
    def child_failed(self) -> bool:
        return any(not s.success for s in self.steps)

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
        return oracle.diagnostics_checks(self.recorder, since_seq, self.ignore)

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


def run_skill(engine: Any, action: FlowAction, page: Any, runner: Any, ctx: RunContext, *,
              recorder: Any = None, ignore: oracle.IgnoreRules | None = None,
              profile: str = "desktop", policy: SafetyPolicy | None = None,
              provider: Any = None) -> list[StepResult]:
    """Marker step (checks, verdict) followed by the child steps the skill ran."""
    fn = SKILLS.get(action.type)
    w0, t0 = time.time(), time.monotonic()
    since = recorder.seq if recorder is not None else 0
    args = parse_skill_args(action.args)
    sc = SkillContext(action=action, page=page, runner=runner, ctx=ctx, engine=engine,
                      args=args, recorder=recorder, ignore=ignore or oracle.IgnoreRules(),
                      profile=profile, policy=policy or SafetyPolicy(),
                      planner=Planner(provider, int(args.get("max_ai_calls", "3") or 0)))
    marker = StepResult(action=action, success=True, message="", layer_used=0, group=True)
    crashed = ""
    checks: list[Check] = []
    if fn is None:
        crashed = f"no implementation registered for '{action.type.value}'"
    else:
        try:
            checks = fn(sc)
        except Exception as exc:
            crashed = f"{type(exc).__name__}: {exc}"
            logger.warning("[skill] %s crashed: %s", action.type.value, crashed)

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
