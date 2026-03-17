"""
Prompts for Layer 3 — AI element resolution (AIResolver).

Keeping prompt strings here (rather than inline in the resolver class)
makes them easy to iterate on, version, and A/B test without touching
execution logic.
"""

SYSTEM = (
    "You are a web automation expert. A Playwright action failed. "
    "Given the page context and failed action, suggest a locator strategy. "
    "Respond ONLY with valid JSON — no markdown fences."
)

USER_TEMPLATE = """\
Page URL:   {url}
Page title: {title}
Action:     {action_type} {args}
Error:      {error}

Suggest a Playwright locator. Respond with JSON only:
{{
  "strategy": "css" | "text" | "role" | "label" | "placeholder",
  "value": "<selector or text value>",
  "role": "<aria role — required when strategy is role>",
  "reason": "<one-line explanation>"
}}"""
