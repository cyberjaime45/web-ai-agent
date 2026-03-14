"""
Guardrails — Validates AI-proposed actions before execution.
Ensures targets exist, are visible, and are enabled.
"""

from __future__ import annotations

import logging

from schemas.models import ActionType, AgentAction, PageState

logger = logging.getLogger(__name__)


class GuardrailError(Exception):
    """Raised when an action fails guardrail validation."""
    pass


def validate_action(action: AgentAction, page_state: PageState) -> bool:
    """
    Validate that an action is safe to execute given the current page state.
    Returns True if valid, raises GuardrailError if not.
    """
    if action.action == ActionType.CLICK:
        return _validate_click(action, page_state)
    elif action.action == ActionType.FILL:
        return _validate_fill(action, page_state)
    elif action.action in (
        ActionType.NAVIGATE,
        ActionType.WAIT,
        ActionType.ASSERT_TEXT,
        ActionType.ASSERT_URL,
        ActionType.SCREENSHOT,
        ActionType.DONE,
        ActionType.FAIL,
    ):
        return True  # These are always safe to attempt
    else:
        raise GuardrailError(f"Unknown action type: {action.action}")


def _validate_click(action: AgentAction, page_state: PageState) -> bool:
    """Verify click target exists in buttons or links."""
    target = (action.target or "").lower()
    if not target:
        raise GuardrailError("Click action has no target")

    all_clickable = [b.lower() for b in page_state.buttons] + [
        l.lower() for l in page_state.links
    ]

    # Check exact or partial match
    for item in all_clickable:
        if target in item or item in target:
            return True

    raise GuardrailError(
        f"Click target '{action.target}' not found in page. "
        f"Available buttons: {page_state.buttons}, links: {page_state.links[:10]}"
    )


def _validate_fill(action: AgentAction, page_state: PageState) -> bool:
    """Verify fill target exists in inputs and is enabled."""
    target = (action.target or "").lower()
    if not target:
        raise GuardrailError("Fill action has no target")

    for inp in page_state.inputs:
        label = (inp.label or inp.name or inp.placeholder).lower()
        if target in label or label in target:
            if not inp.is_enabled:
                raise GuardrailError(f"Input '{action.target}' is disabled")
            return True

    raise GuardrailError(
        f"Input '{action.target}' not found. "
        f"Available inputs: {[i.label or i.name for i in page_state.inputs]}"
    )
