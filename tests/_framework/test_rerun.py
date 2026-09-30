"""RERUN_FAILED: merging a failed flow with its rerun, section by section."""

from __future__ import annotations

from app.execution import rerun
from app.schemas.actions import ActionType, Evidence, FlowAction, FlowResult, StepResult


def _step(section: str, ok: bool, t: float, raw: str = "click: \"x\"", sub_flow: str = "",
          skipped: bool = False) -> StepResult:
    return StepResult(action=FlowAction(type=ActionType.CLICK, args=["x"], raw=raw, section=section),
                      success=ok, skipped=skipped, message="ok" if ok else f"{section} failed",
                      sub_flow=sub_flow, started_at=t, ended_at=t + 0.5)


def _result(steps: list[StepResult]) -> FlowResult:
    return FlowResult(flow_name="Flow", steps=steps,
                      success=all(s.success or s.skipped for s in steps))


def _entry(ts_s: float, text: str) -> dict:
    return {"ts": round(ts_s * 1000), "text": text}


def test_section_runs_keep_sub_flow_steps_in_their_section():
    steps = [_step("Login", True, 1), _step("components", True, 2, sub_flow="login"),
             _step("Home", True, 3)]
    assert [(n, len(s)) for n, s in rerun.section_runs(steps)] == [("Login", 2), ("Home", 1)]


def test_failed_sections_ignore_skipped_steps():
    result = _result([_step("A", True, 1), _step("B", False, 2), _step("B", False, 3, skipped=True),
                      _step("C", True, 4)])
    assert rerun.failed_sections(result) == [1]


def test_flaky_section_takes_the_rerun_and_passed_sections_keep_the_first_attempt():
    first = _result([_step("A", True, 1), _step("B", False, 2), _step("C", True, 3)])
    second = _result([_step("A", False, 11), _step("B", True, 12), _step("C", True, 13)])
    merged = rerun.merge(first, ([_entry(1.2, "a1"), _entry(2.2, "b1")], []),
                         second, ([_entry(11.2, "a2"), _entry(12.2, "b2")], []))
    assert merged.result.success
    assert [s.started_at for s in merged.result.steps] == [1, 12, 3]   # A never replaced by its failed rerun
    assert merged.retried == {1: "B failed"} and merged.passed_on_retry == 1
    assert [e["text"] for e in merged.console] == ["a1", "b2"]         # each section's own attempt


def test_consistent_failure_stays_failed():
    first = _result([_step("A", True, 1), _step("B", False, 2)])
    second = _result([_step("A", True, 11), _step("B", False, 12)])
    merged = rerun.merge(first, ([], []), second, ([], []))
    assert not merged.result.success and merged.result.error == "B failed"
    assert merged.retried == {1: "B failed"} and merged.passed_on_retry == 0


def test_rerun_that_crashed_early_keeps_the_first_attempt():
    first = _result([_step("A", True, 1), _step("B", False, 2)])
    second = _result([_step("A", False, 11)])
    merged = rerun.merge(first, ([_entry(2.1, "b1")], []), second, ([], []))
    assert merged.result is first and merged.retried == {1: "B failed"}
    assert [e["text"] for e in merged.console] == ["b1"]


def _diagnosed(section: str, t: float, verdict: str) -> StepResult:
    s = _step(section, False, t)
    s.evidence = Evidence(diagnosis={"verdict": verdict, "summary": "", "signals": []})
    return s


def test_a_framework_failure_is_not_worth_rerunning_but_a_server_failure_is():
    own = _result([_step("A", True, 1), _diagnosed("B", 2, "framework")])
    assert rerun.failed_sections(own) == [1] and rerun.worth_rerunning(own) == []
    mixed = _result([_diagnosed("A", 1, "framework"), _diagnosed("B", 2, "application"), _step("C", False, 3)])
    assert rerun.verdicts(mixed) == {0: "framework", 1: "application", 2: ""}
    assert rerun.worth_rerunning(mixed) == [1, 2]            # an undiagnosed failure is still retried


def test_merge_keeps_the_first_attempts_verdict_for_the_report():
    first = _result([_step("A", True, 1), _diagnosed("B", 2, "application")])
    second = _result([_step("A", True, 11), _step("B", True, 12)])
    merged = rerun.merge(first, ([], []), second, ([], []))
    assert merged.passed_on_retry == 1 and merged.first_verdicts == {1: "application"}
    crashed = rerun.merge(first, ([], []), _result([_step("A", False, 11)]), ([], []))
    assert crashed.first_verdicts == {1: "application"}
