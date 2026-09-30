"""
AI Resolver (Layer 3) — last-resort LLM invocation.

Only called when both deterministic (L1) and fallback (L2) strategies
fail and the engine's triage says the cause is a locator problem. Sends
the observation (refs, roles, names — never HTML) to an LLM and asks which
observed control the step meant. The answer is grounded before it runs: a
ref or a role / label / placeholder / text that names an observed control;
a CSS or XPath selector from the model is never executed.

Also handles AI-native actions (ai_click, ai_extract, ai_assert,
ai_summarize) that bypass L1/L2 entirely.

Skipped entirely when no LLM provider is configured.
"""

from __future__ import annotations

import json
from typing import Callable
import logging

from playwright.sync_api import Locator, Page

from app.agent.observer import Observation, observe
from app.agent.prompts.resolver import (
    SYSTEM as _SYSTEM,
    USER_TEMPLATE as _USER_TMPL,
    PROMPTS as _AI_PROMPTS,
)
from app.layers.providers import LLMProvider
from app.schemas.actions import ActionType, FlowAction, RunContext, StepResult

logger = logging.getLogger(__name__)

_MAX_PAGE_TEXT = 4000
_RESOLVE_MAX_TOKENS = 200
_AI_ACTION_MAX_TOKENS = 500


def _get_page_text(page: Page) -> str:
    try:
        text = page.inner_text("body")
        return text[:_MAX_PAGE_TEXT] if text else ""
    except Exception:
        return ""


_MAX_ELEMENTS = 120


def _observe(page: Page) -> Observation:
    try:
        return observe(page)
    except Exception:
        return Observation()


def _elements_block(ob: Observation) -> str:
    """The page's interactive controls from the observer — refs, roles, names —
    so a locator suggestion is grounded in what is actually there."""
    lines = [f'- [ref={n.ref}] {n.role} "{n.name}"' + (f" in {n.container}" if n.container else "")
             for n in ob.nodes[:_MAX_ELEMENTS]]
    for form in ob.forms:
        lines += [f'- field "{f.label}" ({f.type})' + (f' placeholder "{f.placeholder}"' if f.placeholder else "")
                  for f in form.fields]
    return "\n".join(lines) or "(none found)"


def _history_block(ctx: RunContext | None) -> str:
    if not ctx or not ctx.history:
        return ""
    recent = ctx.recent_history(5)
    lines = [
        f"  - {h['action']}({h['target']}) → {h['result']} [L{h['layer']}]"
        for h in recent
    ]
    return "\n\nRecent execution history (last steps):\n" + "\n".join(lines)


# Element interactions L3 can carry out once it has a locator. Anything else
# (assertions, waits, key presses, navigation) has no L3 execution path.
_LOCATOR_ACTIONS: dict[ActionType, Callable[[Locator, str], None]] = {
    ActionType.CLICK:           lambda loc, _v: loc.click(),
    ActionType.CLICK_LINK_TEXT: lambda loc, _v: loc.click(),
    ActionType.DOUBLE_CLICK:    lambda loc, _v: loc.dblclick(),
    ActionType.RIGHT_CLICK:     lambda loc, _v: loc.click(button="right"),
    ActionType.HOVER:           lambda loc, _v: loc.hover(),
    ActionType.FILL:            lambda loc, v: loc.fill(v),
    ActionType.TYPE:            lambda loc, v: loc.press_sequentially(v),
    ActionType.SELECT:          lambda loc, v: loc.select_option(v),
    ActionType.CHECK:           lambda loc, _v: loc.check(),
    ActionType.UNCHECK:         lambda loc, _v: loc.uncheck(),
    ActionType.CLEAR:           lambda loc, _v: loc.clear(),
    ActionType.FOCUS:           lambda loc, _v: loc.focus(),
}


class AIResolver:
    """Layer 3: LLM-based element resolution as a last resort."""

    def __init__(self, provider: LLMProvider | None) -> None:
        self._provider = provider

    @staticmethod
    def supports(action_type: ActionType) -> bool:
        """True when ``resolve`` can execute this action with a locator."""
        return action_type in _LOCATOR_ACTIONS

    @property
    def available(self) -> bool:
        return self._provider is not None

    def resolve(
        self,
        action: FlowAction,
        page: Page,
        error: str,
        ctx: RunContext | None = None,
        cause: str = "not_found",
    ) -> StepResult | None:
        """*cause* is the engine's triage of the L1 failure, for the prompt."""
        if self._provider is None:
            return None

        try:
            ob = _observe(page)
            user_msg = _USER_TMPL.format(
                url=page.url,
                title=page.title(),
                action_type=action.type.value,
                args=action.args,
                error=_first_line(error),
                cause=cause.replace("_", " "),
                elements=_elements_block(ob),
            ) + _history_block(ctx)

            raw = self._provider.complete(
                _SYSTEM, user_msg,
                temperature=0.0, max_tokens=_RESOLVE_MAX_TOKENS,
            ).strip() or "{}"

            suggestion = json.loads(raw)
            loc = self._build_locator(page, suggestion, ob)
            if loc is None:
                logger.warning(f"[L3] Suggestion yielded no match: {suggestion}")
                return None

            self._execute_with_locator(action, loc)
            reason = suggestion.get("reason", "AI resolved")
            logger.info(f"[L3] Step {action.step_num}: {reason}")
            return StepResult(
                action=action, success=True,
                message=f"[L3] {reason}", layer_used=3,
            )

        except Exception as exc:
            logger.warning(f"[L3] AI resolver failed: {exc}")
            return None

    def resolve_ai_action(
        self,
        action: FlowAction,
        page: Page,
        ctx: RunContext | None = None,
    ) -> StepResult | None:
        if self._provider is None:
            return None

        action_key = action.type.value
        prompts = _AI_PROMPTS.get(action_key)
        if not prompts:
            logger.warning(f"[L3] No prompt template for AI action: {action_key}")
            return None

        try:
            target = action.args[0] if action.args else ""
            page_text = _get_page_text(page)
            ob = _observe(page) if action.type == ActionType.AI_CLICK else Observation()
            user_msg = prompts["user"].format(
                url=page.url,
                title=page.title(),
                page_text=page_text,
                target=target,
                elements=_elements_block(ob) if action.type == ActionType.AI_CLICK else "",
            ) + _history_block(ctx)

            raw_response = self._provider.complete(
                prompts["system"], user_msg,
                temperature=0.0, max_tokens=_AI_ACTION_MAX_TOKENS,
            ).strip()

            if action.type == ActionType.AI_CLICK:
                return self._handle_ai_click(action, page, raw_response, ob)
            if action.type == ActionType.AI_EXTRACT:
                if ctx is not None:
                    ctx.store("last_extract", raw_response)
                    if target:
                        ctx.store(f"extract_{target}", raw_response)
                return StepResult(
                    action=action, success=True,
                    message=f"[L3] Extracted: {raw_response}", layer_used=3,
                )
            if action.type == ActionType.AI_ASSERT:
                return self._handle_ai_assert(action, raw_response)
            if action.type == ActionType.AI_SUMMARIZE:
                return StepResult(
                    action=action, success=True,
                    message=f"[L3] Summary: {raw_response}", layer_used=3,
                )

        except Exception as exc:
            logger.warning(f"[L3] AI action failed: {exc}")

        return None

    def _handle_ai_click(
        self, action: FlowAction, page: Page, raw: str, ob: Observation
    ) -> StepResult | None:
        try:
            suggestion = json.loads(raw)
            loc = self._build_locator(page, suggestion, ob)
            if loc is None:
                return None
            loc.click()
            reason = suggestion.get("reason", "AI-resolved click")
            return StepResult(
                action=action, success=True,
                message=f"[L3] {reason}", layer_used=3,
            )
        except Exception as exc:
            logger.warning(f"[L3] AI click failed: {exc}")
            return None

    def _handle_ai_assert(
        self, action: FlowAction, raw: str
    ) -> StepResult | None:
        try:
            data = json.loads(raw)
            passed = data.get("result", False)
            reason = data.get("reason", "AI assertion")
            return StepResult(
                action=action, success=passed,
                message=f"[L3] {reason}", layer_used=3,
            )
        except Exception as exc:
            logger.warning(f"[L3] AI assert parse failed: {exc}")
            return None

    @staticmethod
    def _execute_with_locator(action: FlowAction, loc: Locator) -> None:
        """Perform *action* on *loc*; raises for action types without an L3 path
        so a suggestion for an assertion can never be reported as a pass."""
        try:
            perform = _LOCATOR_ACTIONS[action.type]
        except KeyError:
            raise ValueError(f"L3 cannot execute '{action.type.value}'") from None
        perform(loc, action.args[1] if len(action.args) > 1 else "")

    @staticmethod
    def _build_locator(page: Page, s: dict, ob: Observation):
        """A locator grounded in the observation the model was shown: a ``ref``,
        or a role / text value that names an observed control, or a label /
        placeholder that names an observed form field. Anything else — a CSS
        or XPath selector in particular — is refused and logged."""
        strategy = str(s.get("strategy", "") or "").lower()
        value = str(s.get("value", "") or "").strip()
        role = str(s.get("role", "") or "").lower()
        ref = str(s.get("ref", "") or "").strip()
        wanted = value.lower()
        try:
            node = next((n for n in ob.nodes if n.ref == ref), None) if ref else None
            if node is None and value and strategy in ("role", "text", ""):
                node = next((n for n in ob.nodes if n.name.lower() == wanted and (not role or n.role == role)), None)
            if node is not None:
                loc = node.locator(page)
                return loc if loc.count() > 0 else None
            if value and strategy in ("label", "placeholder"):
                fields = [f for form in ob.forms for f in form.fields]
                if strategy == "label" and any(f.label.lower() == wanted for f in fields):
                    loc = page.get_by_label(value, exact=True)
                elif strategy == "placeholder" and any(f.placeholder.lower() == wanted for f in fields):
                    loc = page.get_by_placeholder(value, exact=True)
                else:
                    loc = None
                if loc is not None:
                    return loc.first if loc.count() > 0 else None
        except Exception:
            return None
        logger.info("[L3] suggestion not grounded in the observation, refused: %s", s)
        return None


def _first_line(text: str) -> str:
    return (text or "").split("\nCall log:", 1)[0].splitlines()[0] if text else ""
