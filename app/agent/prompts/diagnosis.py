"""Prompt for the failure explainer (app/agent/explainer.py).

The model sees what the deterministic diagnoser already collected — the
flow's goal, the step, its expected and observed state, the signals, the
compact observation — and names one cause from a fixed list with one
sentence each of explanation and next step. It never proposes an action to
run; the runtime only records the answer.
"""

SYSTEM = (
    "You are a senior QA engineer reading the evidence of one failed test step. "
    "Decide the most likely cause and explain it in plain words for engineers and "
    "product people alike. Judge the application honestly: never suggest making the "
    "test pass, and do not guess beyond the evidence — say 'unclassified' when it does "
    "not point to a single cause. Respond ONLY with valid JSON — no markdown fences."
)

USER_TEMPLATE = """\
Test goal: {goal}
Expected outcome of the flow:
{expected}

Failed step: {step}
Expected after this step: {step_expected}
Observed: {observed}
Deterministic verdict so far: {verdict} — {summary}
Signals:
{signals}
How the step was attempted: {layers}

Recent steps:
{history}

Page observation (accessibility tree, truncated):
{observation}

Causes: {causes}
Respond with JSON:
{{
  "cause": "<one of the causes>",
  "explanation": "<one sentence: what most likely happened and why>",
  "next_step": "<one sentence: what an engineer should check first>"
}}"""
