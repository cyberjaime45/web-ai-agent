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

# ── AI-native action prompts ──────────────────────────────────────────────────

PROMPTS: dict[str, dict[str, str]] = {
    "ai_click": {
        "system": (
            "You are a web automation expert. Given a page's visible text "
            "and a natural-language target description, return a Playwright "
            "locator strategy to click the described element. "
            "Respond ONLY with valid JSON — no markdown fences."
        ),
        "user": """\
Page URL:   {url}
Page title: {title}
Visible text (truncated): {page_text}

Target to click: {target}

Return JSON:
{{
  "strategy": "css" | "text" | "role",
  "value": "<selector or text>",
  "role": "<aria role if strategy is role>",
  "reason": "<one-line explanation>"
}}""",
    },
    "ai_extract": {
        "system": (
            "You are a web data extraction expert. Given page text, "
            "answer the user's question by extracting the relevant data. "
            "Respond with plain text — no JSON, no markdown."
        ),
        "user": """\
Page URL:   {url}
Page title: {title}
Page text (truncated): {page_text}

Question: {target}

Extract and return the answer as plain text.""",
    },
    "ai_assert": {
        "system": (
            "You are a web testing expert. Given page text and an assertion, "
            "evaluate whether the assertion holds. "
            'Respond ONLY with JSON: {{"result": true/false, "reason": "..."}}'
        ),
        "user": """\
Page URL:   {url}
Page title: {title}
Page text (truncated): {page_text}

Assertion: {target}

Evaluate and return JSON:
{{
  "result": true | false,
  "reason": "<one-line explanation>"
}}""",
    },
    "ai_summarize": {
        "system": (
            "You are a web content summarizer. Given the visible page text, "
            "provide a concise summary (2-4 sentences). "
            "Respond with plain text only."
        ),
        "user": """\
Page URL:   {url}
Page title: {title}
Page text (truncated): {page_text}

Summarize the page content in 2-4 sentences.""",
    },
}
