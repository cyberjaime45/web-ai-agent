"""Failure explainer: one budgeted LLM call, validated, never a result."""

from __future__ import annotations

from app.agent import explainer
from app.execution.engine import FlowRunner
from app.schemas.actions import ActionType, Evidence, FlowAction, StepResult
from tests._framework.test_ai_resolver import FakeProvider

DIAG = {"verdict": "unclassified", "summary": "The signals collected do not point to a single cause.",
        "signals": ["page at the failure: https://x.test/profile"],
        "expected": '"Save" can be pressed and the page reacts', "observed": "the page at https://x.test/profile"}


def test_prompt_carries_goal_expected_step_and_evidence():
    prompt = explainer.build_prompt(goal="Profile update", expected=["Profile saved"], step='click: "Save"',
                                    diagnosis=DIAG, layers={"L1 exact": "failed", "triage": "not_found"},
                                    history=["goto(https://x.test) → pass"], observation="url: https://x.test")
    for part in ("Test goal: Profile update", "- Profile saved", 'Failed step: click: "Save"',
                 "Deterministic verdict so far: unclassified", "L1 exact: failed · triage: not_found",
                 "- goto(https://x.test) → pass", "Causes: application, timing"):
        assert part in prompt, part


def test_answers_are_validated_and_trimmed():
    good = explainer.parse_answer('```json\n{"cause": "Application", "explanation": "Save posts to an API that 404s.", "next_step": "Check the profile endpoint."}\n```')
    assert good == {"cause": "application", "explanation": "Save posts to an API that 404s.",
                    "next_step": "Check the profile endpoint."}
    assert explainer.parse_answer('{"cause": "flaky", "explanation": "x"}') is None
    assert explainer.parse_answer("not json") is None
    assert len(explainer.parse_answer('{"cause": "test", "explanation": "%s"}' % ("x" * 900))["explanation"]) == 300


def test_explain_failure_never_raises_and_returns_none_without_a_provider():
    assert explainer.explain_failure(None, goal="", expected=[], step="", diagnosis={}, layers={},
                                     history=[], observation="") is None

    class Broken(FakeProvider):
        def complete(self, *a, **k):
            raise RuntimeError("down")
    assert explainer.explain_failure(Broken(""), goal="", expected=[], step="", diagnosis={}, layers={},
                                     history=[], observation="") is None
    answer = explainer.explain_failure(FakeProvider('{"cause": "test", "explanation": "e", "next_step": "n"}'),
                                       goal="", expected=[], step="", diagnosis={}, layers={}, history=[], observation="")
    assert answer["cause"] == "test"


class _Page:
    url = "https://x.test/"

    def title(self):
        return "t"


def _failed(verdict: str) -> StepResult:
    sr = StepResult(action=FlowAction(type=ActionType.CLICK, args=["Save"], raw='click: "Save"'), success=False,
                    message="boom", error="boom", evidence=Evidence(layers={"L1 exact": "failed"}))
    sr.evidence.diagnosis = {**DIAG, "verdict": verdict}
    return sr


def test_engine_asks_only_for_unclassified_failures_and_within_the_budget(tmp_path, monkeypatch):
    calls: list[dict] = []
    monkeypatch.setattr(explainer, "explain_failure",
                        lambda provider, **ctx: calls.append(ctx) or {"cause": "test", "explanation": "e", "next_step": "n"})
    runner = FlowRunner(artifacts_dir=str(tmp_path), flows_dir=tmp_path, provider=FakeProvider(""))
    runner._goal, runner._expected = "Profile update", ["Profile saved"]
    page = _Page()
    classified = _failed("application")
    runner._explain(classified, page)
    assert "ai" not in classified.evidence.diagnosis and calls == []
    answered = [_failed("unclassified") for _ in range(3)]
    for sr in answered:
        runner._explain(sr, page)
    assert [("ai" in sr.evidence.diagnosis) for sr in answered] == [True, True, False]   # MAX_CALLS = 2
    assert calls[0]["goal"] == "Profile update" and calls[0]["step"] == 'click: "Save"'
    assert answered[0].evidence.diagnosis["ai"]["cause"] == "test"
    assert FlowRunner(artifacts_dir=str(tmp_path), flows_dir=tmp_path, provider=None)._explain(_failed("unclassified"), page) is None
