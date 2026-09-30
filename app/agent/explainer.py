"""Failure explainer — one optional LLM call when the deterministic diagnosis
could not classify a failed step.

The model is a diagnostician, never an actor: it receives the evidence the
engine already collected (goal, step, expected / observed, signals, layer
attempts, recent steps, the compact observation) and returns a cause from
the fixed verdict list with one sentence of explanation and one of next
step. The runtime validates the JSON, keeps the answer on the step's
diagnosis as ``ai`` and the report labels it *AI diagnosis, unverified*.
``FlowRunner`` calls it at most ``MAX_CALLS`` times per flow run, only with
a provider configured and only for an ``unclassified`` verdict.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.agent.prompts.diagnosis import SYSTEM, USER_TEMPLATE

logger = logging.getLogger(__name__)

CAUSES = ("application", "timing", "test", "environment", "framework", "unclassified")
MAX_CALLS = 2               # per flow run
MAX_TOKENS = 300
_MAX_SENTENCE = 300
_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def build_prompt(*, goal: str, expected: list[str], step: str, diagnosis: dict,
                 layers: dict[str, str], history: list[str], observation: str) -> str:
    return USER_TEMPLATE.format(
        goal=goal or "(not stated)",
        expected="\n".join(f"- {e}" for e in expected) or "- (not stated)",
        step=step,
        step_expected=diagnosis.get("expected") or "(unknown)",
        observed=diagnosis.get("observed") or "(nothing recorded)",
        verdict=diagnosis.get("verdict") or "unclassified",
        summary=diagnosis.get("summary") or "",
        signals="\n".join(f"- {s}" for s in diagnosis.get("signals") or []) or "- (none)",
        layers=" · ".join(f"{k}: {v}" for k, v in layers.items()) or "(none)",
        history="\n".join(f"- {h}" for h in history[-5:]) or "- (nothing yet)",
        observation=observation or "(unavailable)",
        causes=", ".join(CAUSES),
    )


def parse_answer(raw: str) -> dict | None:
    """``{"cause", "explanation", "next_step"}`` from the model's JSON, or
    ``None`` when it is not valid or names an unknown cause."""
    text = _FENCE_RE.sub("", (raw or "").strip())
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    cause = str(data.get("cause", "")).strip().lower()
    if cause not in CAUSES:
        return None
    return {"cause": cause,
            "explanation": str(data.get("explanation", "")).strip()[:_MAX_SENTENCE],
            "next_step": str(data.get("next_step", "")).strip()[:_MAX_SENTENCE]}


def explain_failure(provider: Any, **context: Any) -> dict | None:
    """Ask *provider* once (see ``build_prompt`` for the keyword arguments).
    ``None`` without a provider, on a provider error or on an unusable answer.
    Never raises."""
    if provider is None:
        return None
    try:
        raw = provider.complete(SYSTEM, build_prompt(**context), temperature=0.0, max_tokens=MAX_TOKENS)
    except Exception as exc:
        logger.warning("[explainer] provider call failed: %s", exc)
        return None
    answer = parse_answer(raw)
    if answer is None:
        logger.info("[explainer] unusable answer: %.200s", raw)
    return answer
