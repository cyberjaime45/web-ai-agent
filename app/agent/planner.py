"""Planner — turns an observation into a validated list of known actions.

The LLM decides *what* is worth doing; the runtime decides *how*. A plan is
JSON with steps of the form ``{"action", "ref" | "target", "value", "reason"}``
and is validated before anything runs:

  - the action must be one of ``ALLOWED_ACTIONS`` (flow keywords, no code)
  - an element action must name a ref or a name present in the observation
    (or a form field the observer listed) — never a free selector
  - the safety policy must allow it
  - the plan is cut at ``max_steps``

Steps that fail validation are dropped and listed in ``Plan.rejected``.
Every call counts against ``max_calls``; without a provider ``plan`` returns
``None`` and callers fall back to their deterministic order.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from app.agent.observer import PAGE_TYPES, Observation
from app.agent.prompts.planner import CLASSIFY_SYSTEM, CLASSIFY_TEMPLATE, SYSTEM, USER_TEMPLATE
from app.agent.safety import SafetyPolicy

logger = logging.getLogger(__name__)

ELEMENT_ACTIONS = frozenset({"click", "click_link_text", "hover", "fill", "select", "check", "uncheck"})
FREE_ACTIONS = frozenset({"assert_text", "assert_visible", "assert_url", "press", "inspect_page",
                          "test_form", "test_responsive", "check_console_network"})
ALLOWED_ACTIONS = ELEMENT_ACTIONS | FREE_ACTIONS
MAX_TOKENS = 800

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


@dataclass
class PlannedStep:
    action: str
    target: str = ""
    value: str = ""
    reason: str = ""
    ref: str = ""

    @property
    def args(self) -> list[str]:
        if self.action in ELEMENT_ACTIONS and self.action in ("fill", "select"):
            return [self.target, self.value]
        if self.action in ("assert_text", "assert_visible", "assert_url", "press") or self.action in ELEMENT_ACTIONS:
            return [self.target] if self.target else []
        return [self.value] if self.value else []


@dataclass
class Plan:
    steps: list[PlannedStep] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    raw: str = ""

    def __bool__(self) -> bool:
        return bool(self.steps)


def _loads(raw: str) -> Any:
    text = _FENCE_RE.sub("", (raw or "").strip())
    start, end = text.find("{"), text.rfind("}")
    if start == -1:
        start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in the response")
    return json.loads(text[start:end + 1])


def parse_plan(raw: str, ob: Observation, policy: SafetyPolicy, max_steps: int = 10) -> Plan:
    """Validate the model's JSON against the observation and the policy."""
    plan = Plan(raw=raw)
    try:
        data = _loads(raw)
    except (ValueError, json.JSONDecodeError) as exc:
        plan.rejected.append(f"unparseable plan: {exc}")
        return plan
    items = data.get("steps") if isinstance(data, dict) else data
    if not isinstance(items, list):
        plan.rejected.append("plan has no 'steps' list")
        return plan

    by_ref = {n.ref: n for n in ob.nodes}
    by_name = {n.name.lower(): n for n in ob.nodes if n.name}
    fields = {f.label.lower(): f for form in ob.forms for f in form.fields}

    for item in items:
        if len(plan.steps) >= max_steps:
            plan.rejected.append("plan cut at max_steps")
            break
        if not isinstance(item, dict):
            plan.rejected.append(f"not an object: {item!r}")
            continue
        action = str(item.get("action", "")).strip().lower()
        if action not in ALLOWED_ACTIONS:
            plan.rejected.append(f"unknown action '{action}'")
            continue
        ref = str(item.get("ref", "") or "")
        target = str(item.get("target", "") or "")
        value = str(item.get("value", "") or "")
        reason = str(item.get("reason", "") or "")[:200]
        if action in ELEMENT_ACTIONS:
            node = by_ref.get(ref) or by_name.get(target.lower())
            fld = fields.get(target.lower()) if node is None else None
            if node is not None:
                target, role, container = node.name, node.role, node.container
            elif fld is not None:
                target, role, container = fld.target, "textbox", ""
            else:
                plan.rejected.append(f"{action}: target '{ref or target}' is not on the page")
                continue
            if not target:
                plan.rejected.append(f"{action}: element {ref} has no accessible name")
                continue
            verdict = policy.verdict(target, role=role, container=container, url=ob.url)
            if not verdict.allowed:
                plan.rejected.append(f"{action} '{target}' blocked by safety: {verdict.reason}")
                continue
        elif action in ("assert_text", "assert_visible", "assert_url", "press") and not target:
            plan.rejected.append(f"{action}: missing target")
            continue
        plan.steps.append(PlannedStep(action=action, target=target, value=value, reason=reason, ref=ref))
    return plan


class Planner:
    """One LLM-backed planner per skill run, with a call budget."""

    def __init__(self, provider: Any | None, max_calls: int = 3) -> None:
        self._provider = provider
        self.max_calls = max_calls
        self.calls = 0

    @property
    def available(self) -> bool:
        return self._provider is not None and self.calls < self.max_calls

    def plan(self, ob: Observation, goal: str, policy: SafetyPolicy, *,
             history: list[str] | None = None, max_steps: int = 10) -> Plan | None:
        if not self.available:
            return None
        self.calls += 1
        user = USER_TEMPLATE.format(
            goal=goal, observation=ob.to_prompt(),
            history="\n".join(f"- {h}" for h in (history or [])) or "- (nothing yet)",
            actions=", ".join(sorted(ALLOWED_ACTIONS)), max_steps=max_steps,
        )
        try:
            raw = self._provider.complete(SYSTEM, user, temperature=0.0, max_tokens=MAX_TOKENS)
        except Exception as exc:
            logger.warning("[planner] provider call failed: %s", exc)
            return Plan(rejected=[f"provider error: {exc}"])
        plan = parse_plan(raw, ob, policy, max_steps)
        logger.info("[planner] %d step(s) accepted, %d rejected", len(plan.steps), len(plan.rejected))
        return plan

    def classify(self, ob: Observation) -> str | None:
        """AI tie-break for the page type; ``None`` without budget or on a bad answer."""
        if not self.available:
            return None
        self.calls += 1
        try:
            raw = self._provider.complete(
                CLASSIFY_SYSTEM,
                CLASSIFY_TEMPLATE.format(types=", ".join(PAGE_TYPES), observation=ob.to_prompt()),
                temperature=0.0, max_tokens=100)
            answer = str(_loads(raw).get("type", "")).strip().upper()
        except Exception as exc:
            logger.warning("[planner] classification failed: %s", exc)
            return None
        return answer if answer in PAGE_TYPES else None
