"""
AI Resolver (Layer 3) — last-resort LLM invocation.

Only called when both deterministic (L1) and fallback (L2) strategies
fail. Sends a minimal page snapshot to an LLM and asks for an
alternative locator strategy.

Also handles AI-native actions (ai_click, ai_extract, ai_assert,
ai_summarize) that bypass L1/L2 entirely.

Skipped entirely when no LLM provider is configured.
"""

from __future__ import annotations

import json
from typing import Callable
import logging

from playwright.sync_api import Locator, Page

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
    ) -> StepResult | None:
        if self._provider is None:
            return None

        try:
            user_msg = _USER_TMPL.format(
                url=page.url,
                title=page.title(),
                action_type=action.type.value,
                args=action.args,
                error=error,
            ) + _history_block(ctx)

            raw = self._provider.complete(
                _SYSTEM, user_msg,
                temperature=0.0, max_tokens=_RESOLVE_MAX_TOKENS,
            ).strip() or "{}"

            suggestion = json.loads(raw)
            loc = self._build_locator(page, suggestion)
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
            user_msg = prompts["user"].format(
                url=page.url,
                title=page.title(),
                page_text=page_text,
                target=target,
            ) + _history_block(ctx)

            raw_response = self._provider.complete(
                prompts["system"], user_msg,
                temperature=0.0, max_tokens=_AI_ACTION_MAX_TOKENS,
            ).strip()

            if action.type == ActionType.AI_CLICK:
                return self._handle_ai_click(action, page, raw_response)
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
        self, action: FlowAction, page: Page, raw: str
    ) -> StepResult | None:
        try:
            suggestion = json.loads(raw)
            loc = self._build_locator(page, suggestion)
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
    def _build_locator(page: Page, s: dict):
        strategy = s.get("strategy", "css")
        value    = s.get("value", "")
        role     = s.get("role", "")
        try:
            if strategy == "css":
                loc = page.locator(value)
            elif strategy == "text":
                loc = page.get_by_text(value)
            elif strategy == "role" and role:
                loc = page.get_by_role(role, name=value)
            elif strategy == "label":
                loc = page.get_by_label(value)
            elif strategy == "placeholder":
                loc = page.get_by_placeholder(value)
            else:
                loc = page.locator(value)

            return loc.first if loc.count() > 0 else None
        except Exception:
            return None
