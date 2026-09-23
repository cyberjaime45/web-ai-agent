"""Prompts for the agent planner (app/agent/planner.py).

The model sees a compact observation (refs, roles, names — never HTML) and
returns a JSON plan of known actions on observed targets. Anything else is
dropped by the validator before execution.
"""

SYSTEM = (
    "You are a QA engineer planning safe, non-destructive checks of a web page. "
    "You may only use the actions listed and only target elements that appear "
    "in the observation, by their ref. Never invent selectors, never write code. "
    "Prefer the page's primary features: navigation, search, filters, opening "
    "details, opening (not submitting) forms. Never plan actions that delete, "
    "pay, send, publish, cancel or otherwise change data for real. "
    "Respond ONLY with valid JSON — no markdown fences, no commentary."
)

CLASSIFY_SYSTEM = (
    "You classify web pages for QA planning. Answer with JSON only: "
    '{"type": "<one of the listed types>", "reason": "<one line>"}.'
)

CLASSIFY_TEMPLATE = """\
Types: {types}

Observation:
{observation}

Which type fits best?"""

USER_TEMPLATE = """\
Goal: {goal}

Observation:
{observation}

Already done on this page (do not repeat):
{history}

Allowed actions: {actions}
Plan at most {max_steps} steps. Respond with JSON:
{{
  "steps": [
    {{"action": "click", "ref": "e12", "reason": "opens the member details"}},
    {{"action": "fill", "ref": "e15", "value": "Smith", "reason": "exercise search"}},
    {{"action": "assert_text", "target": "Member Details", "reason": "details page loaded"}}
  ]
}}"""
