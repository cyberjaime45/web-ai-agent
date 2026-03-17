"""
AI Resolver (Layer 3) — last-resort LLM invocation.

Only called when both deterministic (L1) and fallback (L2) strategies
fail. Sends a minimal page snapshot to an LLM and asks for an
alternative locator strategy.

Skipped entirely when OPENAI_API_KEY is not set.
"""

from __future__ import annotations

import json
import logging
import os

from playwright.sync_api import Page

from app.schemas.actions import FlowAction, StepResult
from app.agent.prompts.resolver import SYSTEM as _SYSTEM, USER_TEMPLATE as _USER_TMPL

logger = logging.getLogger(__name__)


class AIResolver:
    """Layer 3: LLM-based element resolution as a last resort."""

    def resolve(self, action: FlowAction, page: Page, error: str) -> StepResult | None:
        """Ask the LLM for an alternative locator. Returns StepResult or None."""
        if not os.getenv("OPENAI_API_KEY"):
            logger.warning("[L3] Skipped — no OPENAI_API_KEY")
            return None

        try:
            from openai import OpenAI

            client = OpenAI()
            user_msg = _USER_TMPL.format(
                url=page.url,
                title=page.title(),
                action_type=action.type.value,
                args=action.args,
                error=error,
            )

            resp = client.chat.completions.create(
                model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                messages=[
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user",   "content": user_msg},
                ],
                temperature=0,
                max_tokens=200,
            )

            raw = (resp.choices[0].message.content or "{}").strip()
            suggestion = json.loads(raw)
            loc = self._build_locator(page, suggestion)

            if loc is None:
                logger.warning(f"[L3] Suggestion yielded no match: {suggestion}")
                return None

            # Execute the action with the AI-resolved locator
            value = action.args[1] if len(action.args) > 1 else ""
            if action.type.value in ("click", "click_button", "click_link"):
                loc.click()
            elif action.type.value == "fill":
                loc.fill(value)
            else:
                return None

            reason = suggestion.get("reason", "AI resolved")
            logger.info(f"[L3] Step {action.step_num}: {reason}")
            return StepResult(
                action=action, success=True,
                message=f"[L3] {reason}", layer_used=3,
            )

        except Exception as exc:
            logger.warning(f"[L3] AI resolver failed: {exc}")
            return None

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
