"""
AI Planner — Sends structured page state + flow context to an LLM
and receives proposed actions.

Supports two modes:
  1. OpenAI-backed planner (requires OPENAI_API_KEY)
  2. Rule-based fallback planner (no API key needed, for demos)
"""

from __future__ import annotations

import json
import logging
import os
from typing import Optional

from agent.flow_parser import FlowDefinition
from agent.schemas import (
    ActionType,
    AgentAction,
    AgentResponse,
    PageState,
)

logger = logging.getLogger(__name__)

# ── System prompt for the LLM ──────────────────────────────────

SYSTEM_PROMPT = """\
You are a QA Web Agent. You receive structured page state from a browser and
a test flow with steps to execute. Your job is to decide the NEXT action(s)
to perform.

Respond ONLY with valid JSON matching this schema:
{
  "actions": [
    {
      "action": "click" | "fill" | "navigate" | "wait" | "assert_text" | "assert_url" | "screenshot" | "done" | "fail",
      "target": "element text or URL",
      "value": "value for fill actions, or expected text/url fragment for asserts",
      "reason": "why this action"
    }
  ],
  "is_complete": false,
  "summary": "brief status"
}

Rules:
- Only return actions that can be performed on the CURRENT page state.
- For 'fill' actions, target is the input label/name and value is what to type.
- For 'click' actions, target must match a visible button or link text.
- For 'assert_text', value is the text expected on the page.
- For 'assert_url', value is a substring expected in the URL.
- Return "done" action when the flow goal is achieved.
- Return "fail" action if you determine the goal cannot be achieved.
- Keep it to 1-3 actions per response.
"""


def build_user_prompt(
    flow: FlowDefinition,
    page_state: PageState,
    step_index: int,
    history: list[str],
) -> str:
    """Build the user message for the LLM from flow + page state."""
    remaining_steps = flow.steps[step_index:]
    history_text = "\n".join(history[-10:]) if history else "None yet"

    return f"""## Flow: {flow.name}
Goal: {flow.description}
Current step index: {step_index} of {len(flow.steps)}
Remaining steps:
{chr(10).join(f"  {i+1}. {s}" for i, s in enumerate(remaining_steps))}

## Credentials Available
{json.dumps(flow.credentials) if flow.credentials else "None"}

## Current Page State
{page_state.model_dump_json(indent=2)}

## Action History
{history_text}

## Expected Outcome
{chr(10).join(f"- {o}" for o in flow.expected_outcome)}

What is the next action?"""


# ── OpenAI-backed planner ──────────────────────────────────────


def plan_with_openai(
    flow: FlowDefinition,
    page_state: PageState,
    step_index: int = 0,
    history: list[str] | None = None,
) -> AgentResponse:
    """Use OpenAI to plan the next action(s)."""
    try:
        from openai import OpenAI
    except ImportError:
        raise RuntimeError("openai package not installed. pip install openai")

    client = OpenAI()
    user_msg = build_user_prompt(flow, page_state, step_index, history or [])

    response = client.chat.completions.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.1,
        max_tokens=1000,
    )

    raw = response.choices[0].message.content or "{}"
    # Strip markdown fences if present
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()

    try:
        data = json.loads(raw)
        return AgentResponse(**data)
    except (json.JSONDecodeError, Exception) as exc:
        logger.error(f"Failed to parse LLM response: {exc}\nRaw: {raw}")
        return AgentResponse(
            actions=[AgentAction(action=ActionType.FAIL, reason=f"Parse error: {exc}")],
            is_complete=False,
            summary="Failed to parse LLM response",
        )


# ── Rule-based fallback planner ────────────────────────────────


def plan_with_rules(
    flow: FlowDefinition,
    page_state: PageState,
    step_index: int = 0,
    history: list[str] | None = None,
) -> AgentResponse:
    """
    Simple rule-based planner that maps flow steps to actions
    by keyword matching. Works without an API key for demos.
    """
    if step_index >= len(flow.steps):
        return AgentResponse(
            actions=[AgentAction(action=ActionType.DONE, reason="All steps completed")],
            is_complete=True,
            summary="Flow complete",
        )

    step = flow.steps[step_index].lower()
    actions: list[AgentAction] = []

    # Navigate
    if "navigate" in step and flow.url:
        actions.append(
            AgentAction(action=ActionType.NAVIGATE, target=flow.url, reason=step)
        )

    # Fill username
    elif "username" in step and "enter" in step:
        username = flow.credentials.get("username", "")
        target = _find_input_label(page_state, ["username", "user", "email"])
        actions.append(
            AgentAction(action=ActionType.FILL, target=target, value=username, reason=step)
        )

    # Fill password
    elif "password" in step and "enter" in step:
        password = flow.credentials.get("password", "")
        target = _find_input_label(page_state, ["password", "pass"])
        actions.append(
            AgentAction(action=ActionType.FILL, target=target, value=password, reason=step)
        )

    # Click
    elif "click" in step:
        # Try to extract button name from the step text
        for btn in page_state.buttons:
            if btn.lower() in step:
                actions.append(
                    AgentAction(action=ActionType.CLICK, target=btn, reason=step)
                )
                break
        if not actions:
            # Try links
            for link in page_state.links:
                if link.lower() in step:
                    actions.append(
                        AgentAction(action=ActionType.CLICK, target=link, reason=step)
                    )
                    break
        if not actions:
            # Fallback: click first button
            if page_state.buttons:
                actions.append(
                    AgentAction(
                        action=ActionType.CLICK,
                        target=page_state.buttons[0],
                        reason=f"Fallback click for: {step}",
                    )
                )

    # Verify URL
    elif "verify" in step and ("url" in step or "navigate" in step or "page" in step):
        # Try to extract expected URL fragment from expected outcomes
        expected_fragment = ""
        for outcome in flow.expected_outcome:
            if "url" in outcome.lower() and "contain" in outcome.lower():
                # Extract quoted text
                import re
                match = re.search(r'"([^"]+)"', outcome)
                if match:
                    expected_fragment = match.group(1)
                    break
        if expected_fragment:
            actions.append(
                AgentAction(
                    action=ActionType.ASSERT_URL,
                    value=expected_fragment,
                    reason=step,
                )
            )

    # Verify text on page
    elif "verify" in step and ("contain" in step or "text" in step or "message" in step):
        # Extract quoted text from the step
        import re
        matches = re.findall(r'"([^"]+)"', flow.steps[step_index])
        if matches:
            for match in matches:
                actions.append(
                    AgentAction(
                        action=ActionType.ASSERT_TEXT, value=match, reason=step
                    )
                )
        else:
            # Check expected outcomes
            for outcome in flow.expected_outcome:
                if "message" in outcome.lower() or "text" in outcome.lower():
                    actions.append(
                        AgentAction(
                            action=ActionType.ASSERT_TEXT,
                            value=outcome,
                            reason=step,
                        )
                    )
                    break

    # Default: try to match broadly
    if not actions:
        actions.append(
            AgentAction(
                action=ActionType.WAIT,
                value="1000",
                reason=f"No rule matched for step: {step}",
            )
        )

    return AgentResponse(
        actions=actions,
        is_complete=False,
        summary=f"Step {step_index + 1}: {flow.steps[step_index]}",
    )


def _find_input_label(page_state: PageState, keywords: list[str]) -> str:
    """Find an input label matching any of the keywords."""
    for inp in page_state.inputs:
        label_lower = (inp.label or inp.name or inp.placeholder).lower()
        for kw in keywords:
            if kw in label_lower:
                return inp.label or inp.name or inp.placeholder
    # Fallback to first keyword
    return keywords[0] if keywords else ""


# ── Planner factory ────────────────────────────────────────────


def get_planner():
    """Return the appropriate planner function based on available config."""
    if os.getenv("OPENAI_API_KEY"):
        logger.info("Using OpenAI-backed planner")
        return plan_with_openai
    else:
        logger.info("No OPENAI_API_KEY set — using rule-based fallback planner")
        return plan_with_rules
