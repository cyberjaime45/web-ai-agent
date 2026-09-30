"""
Prompts for Layer 3 — AI element resolution (AIResolver).

Keeping prompt strings here (rather than inline in the resolver class)
makes them easy to iterate on, version, and A/B test without touching
execution logic.
"""

SYSTEM = (
    "You are a web automation expert. A Playwright action could not find its target. "
    "Given the page's controls, say which one the step meant — by its ref. "
    "Never invent selectors or code; if no listed control fits, answer {\"ref\": \"\"}. "
    "Respond ONLY with valid JSON — no markdown fences."
)

USER_TEMPLATE = """\
Page URL:   {url}
Page title: {title}
Action:     {action_type} {args}
Error:      {error}
Why it failed (triage): {cause}

Controls on the page ([ref] role "accessible name", form fields by label):
{elements}

Which control above did the step mean? Respond with JSON only:
{{
  "ref": "<ref of the control, e.g. e12 — preferred>",
  "strategy": "label" | "placeholder",
  "value": "<a form field's exact label or placeholder — only when there is no ref>",
  "reason": "<one-line explanation>"
}}"""

# ── AI-native action prompts ──────────────────────────────────────────────────

PROMPTS: dict[str, dict[str, str]] = {
    "ai_click": {
        "system": (
            "You are a web automation expert. Given a page's controls and a "
            "natural-language target description, name the control to click by "
            "its ref. Never invent selectors or code. "
            "Respond ONLY with valid JSON — no markdown fences."
        ),
        "user": """\
Page URL:   {url}
Page title: {title}
Controls on the page ([ref] role "accessible name"):
{elements}
Visible text (truncated): {page_text}

Target to click: {target}

Return JSON naming one of the controls above by its ref:
{{
  "ref": "<ref, e.g. e12>",
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
            "summarize what the page is and what a visitor can do there; "
            "the summary appears as one entry in a test report, so keep it brief. "
            "Respond with plain text only."
        ),
        "user": """\
Page URL:   {url}
Page title: {title}
Page text (truncated): {page_text}

Summarize the page.""",
    },
}
