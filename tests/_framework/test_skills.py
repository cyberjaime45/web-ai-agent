"""Skill runtime: option parsing, marker + child steps, engine dispatch, oracle wiring."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.execution import oracle
from app.execution.engine import FlowRunner
from app.flow.parser import parse_flow_markdown
from app.schemas.actions import SKILL_ACTIONS, ActionType, Check, FlowAction, StepResult
from app.skills import SKILLS, parse_skill_args, run_skill
from app.skills.base import SkillContext, info, skill


class FakePage:
    url = "https://x.test/"
    viewport_size = {"width": 1280, "height": 800}

    def title(self):
        return "t"

    def screenshot(self, path, **kw):
        from pathlib import Path
        Path(path).write_bytes(b"png")


@pytest.fixture
def runner(tmp_path):
    return FlowRunner(artifacts_dir=str(tmp_path), flows_dir=tmp_path, provider=None)


def _patch_run_step(monkeypatch, fail_raws=()):
    def fake(self, action, page, runner, ctx):
        ok = action.raw not in fail_raws
        return StepResult(action=action, success=ok, message="" if ok else "boom", layer_used=1)
    monkeypatch.setattr(FlowRunner, "_run_step", fake)


def test_parse_skill_args():
    assert parse_skill_args(["submit=false", "form=Contact us", "Members"]) == {
        "submit": "false", "form": "Contact us", "target": "Members"}
    assert parse_skill_args([]) == {}


def test_every_skill_keyword_is_registered():
    assert set(SKILLS) == set(SKILL_ACTIONS)


def test_run_skill_marker_then_children(monkeypatch, runner):
    _patch_run_step(monkeypatch)

    @skill(ActionType.INSPECT_PAGE)   # temporarily replace for the test
    def fake_skill(sc: SkillContext):
        sc.run(ActionType.CLICK, "Add Member")
        sc.run(ActionType.FILL, "Email", "a@b.c")
        return [Check("looks fine", True), Check("minor", False, "warn", "meh")]

    try:
        action = FlowAction(type=ActionType.INSPECT_PAGE, args=["x=1"], raw='inspect_page: "x=1"', step_num=3, section="S")
        steps = run_skill(runner, action, FakePage(), None, __import__("app.schemas.actions", fromlist=["RunContext"]).RunContext())
    finally:
        from app.skills import inspect_page as real
        SKILLS[ActionType.INSPECT_PAGE] = real.inspect_page

    marker, click, fill = steps
    assert marker.group and marker.success and marker.action is action
    assert marker.message == "inspect_page: 1 warning"
    assert [c.name for c in marker.checks] == ["looks fine", "minor"]
    assert click.sub_flow == "inspect_page" and click.action.raw == 'click: "Add Member"'
    assert fill.action.args == ["Email", "a@b.c"] and fill.action.step_num == 3 and fill.action.section == "S"


def test_run_skill_fails_on_error_check_or_failed_child(monkeypatch, runner):
    _patch_run_step(monkeypatch, fail_raws=('click: "Save"',))

    def bad_skill(sc: SkillContext):
        return [Check("empty submission rejected", False, "error", "form posted")]

    def child_fails(sc: SkillContext):
        sc.run(ActionType.CLICK, "Save")
        return [Check("ok", True)]

    ctx = __import__("app.schemas.actions", fromlist=["RunContext"]).RunContext()
    action = FlowAction(type=ActionType.TEST_FORM, args=[], raw="test_form")
    real = SKILLS[ActionType.TEST_FORM]
    try:
        SKILLS[ActionType.TEST_FORM] = bad_skill
        (marker,) = run_skill(runner, action, FakePage(), None, ctx)
        assert not marker.success and marker.error == "empty submission rejected — form posted"
        assert marker.evidence is not None and marker.evidence.screenshots["viewport"]
        SKILLS[ActionType.TEST_FORM] = child_fails
        marker, child = run_skill(runner, action, FakePage(), None, ctx)
        assert not marker.success and "a child step failed" in marker.message and not child.success
    finally:
        SKILLS[ActionType.TEST_FORM] = real


def test_skill_crash_is_a_failed_marker_not_an_exception(runner):
    real = SKILLS[ActionType.CHECK_CONSOLE_NETWORK]
    SKILLS[ActionType.CHECK_CONSOLE_NETWORK] = lambda sc: 1 / 0
    try:
        ctx = __import__("app.schemas.actions", fromlist=["RunContext"]).RunContext()
        (marker,) = run_skill(runner, FlowAction(type=ActionType.CHECK_CONSOLE_NETWORK, args=[], raw="x"),
                              FakePage(), None, ctx)
        assert not marker.success and "ZeroDivisionError" in marker.message
    finally:
        SKILLS[ActionType.CHECK_CONSOLE_NETWORK] = real


def test_engine_dispatches_skills_like_run_flow(monkeypatch, runner):
    _patch_run_step(monkeypatch)
    calls = []

    def fake_skill(sc: SkillContext):
        calls.append(sc.args)
        sc.run(ActionType.CLICK, "Go")
        return [Check("fine", True)]

    real = SKILLS[ActionType.TEST_RESPONSIVE]
    SKILLS[ActionType.TEST_RESPONSIVE] = fake_skill
    try:
        md = '# T\n\n## Config\n- ignore_console: "noise"\n\n## S\n- goto: "https://x"\n- test_responsive: "viewports=390x664"\n- click: "after"\n'
        result = runner.run(parse_flow_markdown(md), FakePage())
    finally:
        SKILLS[ActionType.TEST_RESPONSIVE] = real
    assert result.success
    assert calls == [{"viewports": "390x664"}]
    assert [(s.action.raw, s.group, s.sub_flow) for s in result.steps] == [
        ('goto: "https://x"', False, ""),
        ('test_responsive: "viewports=390x664"', True, ""),
        ('click: "Go"', False, "test_responsive"),
        ('click: "after"', False, ""),
    ]
    assert runner._ignore.console == ["noise"]


def test_oracle_runs_after_navigation_steps(monkeypatch, runner):
    _patch_run_step(monkeypatch)
    monkeypatch.setattr(oracle, "observe_after",
                        lambda page, rec, since, ignore: ({}, [Check("page rendered", False, "error", "blank")]))
    flow = parse_flow_markdown('# T\n\n## S\n- goto: "https://x"\n- assert_text: "hi"\n')
    monkeypatch.setattr("app.execution.engine.settings", SimpleNamespace(oracle="warn", images_dir=None, allow_destructive=False))
    result = runner.run(flow, FakePage())
    goto, assertion = result.steps
    assert goto.success and [c.name for c in goto.checks] == ["page rendered"]   # warn: recorded only
    assert assertion.checks == []                                                # not a navigation step
    monkeypatch.setattr("app.execution.engine.settings", SimpleNamespace(oracle="strict", images_dir=None, allow_destructive=False))
    result = runner.run(flow, FakePage())
    assert not result.steps[0].success and result.steps[0].error == "page rendered: blank"
    assert result.steps[1].skipped
    monkeypatch.setattr("app.execution.engine.settings", SimpleNamespace(oracle="off", images_dir=None, allow_destructive=False))
    assert runner.run(flow, FakePage()).steps[0].checks == []


# ── outcome rules: child kinds, budget, safety gate ─────────────────────────

class _Skill:
    """Temporarily register *fn* as the implementation of *action_type*."""

    def __init__(self, action_type: ActionType, fn):
        self.action_type, self.fn = action_type, fn

    def __enter__(self):
        self.real = SKILLS[self.action_type]
        SKILLS[self.action_type] = self.fn

    def __exit__(self, *exc):
        SKILLS[self.action_type] = self.real


def _flow(runner, md: str):
    return runner.run(parse_flow_markdown(md), FakePage())


def test_check_outcome_names_every_result():
    assert [Check("a", True).outcome, Check("a", False).outcome, Check("a", False, "warn").outcome,
            Check("a", True, "info").outcome, Check("a", True, "skipped").outcome,
            Check("a", True, "blocked").outcome] == [
        "passed", "failed", "warning", "info", "skipped", "blocked"]


def test_a_failed_probe_is_soft_and_the_section_goes_on(monkeypatch, runner):
    _patch_run_step(monkeypatch, fail_raws=('click: "Tab B"',))

    def probe(sc: SkillContext):
        pressed = sc.run(ActionType.CLICK, "Tab B", kind="probe")
        return [Check("tabs select their panel", pressed.success, "warn", "could not press 'Tab B'")]

    with _Skill(ActionType.TEST_WIDGETS, probe):
        result = _flow(runner, '# T\n\n## S\n- test_widgets\n- click: "after"\n')
    marker, child, after = result.steps
    assert marker.success and child.soft and not child.success and not child.fails_flow
    assert after.success and not after.skipped            # the section was not stopped
    assert result.success and result.failed == 0


def test_a_failed_action_fails_the_skill_and_stops_the_section(monkeypatch, runner):
    _patch_run_step(monkeypatch, fail_raws=('fill: "Email" | "x"',))

    def needs_it(sc: SkillContext):
        sc.run(ActionType.FILL, "Email", "x")
        return [Check("fine", True)]

    with _Skill(ActionType.TEST_WIDGETS, needs_it):
        result = _flow(runner, '# T\n\n## S\n- test_widgets\n- click: "after"\n\n## Next\n- click: "next"\n')
    marker, child, after, nxt = result.steps
    assert not marker.success and "a child step failed" in marker.message
    assert child.fails_flow and after.skipped and nxt.success     # the next section still runs
    assert not result.success and result.failed == 2               # the marker and its action


def test_a_failed_cleanup_is_not_verified_never_a_warning(monkeypatch, runner):
    _patch_run_step(monkeypatch, fail_raws=("back",))

    def with_cleanup(sc: SkillContext):
        sc.run(ActionType.CLICK, "Open", kind="probe")
        sc.run(ActionType.BACK, kind="cleanup")
        return [Check("opens", True, "warn")]

    with _Skill(ActionType.TEST_TABLE, with_cleanup):
        marker, *_ = run_skill(runner, FlowAction(type=ActionType.TEST_TABLE, args=[], raw="test_table"),
                               FakePage(), None, __import__("app.schemas.actions", fromlist=["RunContext"]).RunContext())
    restored = {c.name: c for c in marker.checks}["page restored after the skill"]
    assert marker.success and restored.outcome == "inconclusive" and restored.detail.startswith("back: boom")
    assert marker.message.endswith("1 check passed, 1 not verified")      # the agent's housekeeping, not the app


def test_a_nested_skill_failure_fails_the_caller(monkeypatch, runner):
    _patch_run_step(monkeypatch)

    def inner(sc: SkillContext):
        return [Check("inner defect", False, "error")]

    def outer(sc: SkillContext):
        sc.run_skill(ActionType.TEST_WIDGETS)
        return [Check("outer fine", True)]

    with _Skill(ActionType.TEST_WIDGETS, inner), _Skill(ActionType.TEST_PAGE, outer):
        result = _flow(runner, '# T\n\n## S\n- test_page\n')
    outer_marker, inner_marker = result.steps
    assert not inner_marker.success and inner_marker.sub_flow == "test_page"
    assert not outer_marker.success and not result.success


def test_the_press_budget_is_shared_with_nested_skills_and_spares_cleanup(monkeypatch, runner):
    _patch_run_step(monkeypatch)

    def inner(sc: SkillContext):
        for name in ("a", "b", "c"):
            if sc.run(ActionType.CLICK, name, kind="probe").skipped:
                break
        sc.run(ActionType.PRESS, "Escape", kind="cleanup")     # always allowed
        return []

    def outer(sc: SkillContext):
        sc.run(ActionType.CLICK, "first", kind="probe")
        sc.run_skill(ActionType.TEST_WIDGETS)                  # its own default limit: none
        late = sc.run(ActionType.CLICK, "late", kind="probe")
        return [info("late", late.message)]

    with _Skill(ActionType.TEST_WIDGETS, inner), _Skill(ActionType.TEST_PAGE, outer):
        result = _flow(runner, '# T\n\n## S\n- test_page: "max_actions=3"\n')
    raws = [s.action.raw for s in result.steps if not s.group]
    assert raws == ['click: "first"', 'click: "a"', 'click: "b"', 'press: "Escape"']
    outer_marker = result.steps[0]
    checks = {c.name: c for c in outer_marker.checks}
    assert checks["late"].detail == "not run — action limit reached (max_actions)"
    assert checks["finished within limits"].outcome == "skipped"
    assert outer_marker.success and result.success           # a configured limit is not a failure


def test_the_time_budget_leaves_a_skill_not_verified(monkeypatch, runner):
    _patch_run_step(monkeypatch)

    def slow(sc: SkillContext):
        sc.run(ActionType.CLICK, "never", kind="probe")
        return []

    with _Skill(ActionType.TEST_WIDGETS, slow):
        result = _flow(runner, '# T\n\n## S\n- test_widgets: "timeout=0"\n')
    (marker,) = result.steps                                  # nothing ran
    limit = {c.name: c for c in marker.checks}["finished within limits"]
    assert limit.outcome == "inconclusive" and "time budget" in limit.detail
    assert marker.success


def test_every_click_passes_the_safety_policy_first(monkeypatch, runner):
    _patch_run_step(monkeypatch)

    def presses(sc: SkillContext):
        refused = sc.run(ActionType.CLICK, "Delete account", kind="probe")
        return [info("refused", refused.message)]

    with _Skill(ActionType.TEST_WIDGETS, presses):
        result = _flow(runner, '# T\n\n## S\n- test_widgets\n')
    (marker,) = result.steps                                  # the click never ran
    checks = {c.name: c for c in marker.checks}
    assert checks["refused"].detail == "not pressed — name contains 'delete'"
    assert checks["blocked by safety"].outcome == "blocked"
    assert checks["blocked by safety"].detail == "Delete account — name contains 'delete'"
    with _Skill(ActionType.TEST_WIDGETS, presses):
        result = _flow(runner, '# T\n\n## Config\n- allow_destructive: true\n\n## S\n- test_widgets\n')
    assert [s.action.raw for s in result.steps[1:]] == ['click: "Delete account"']


def test_planned_steps_are_probes_and_skills_run_with_safe_defaults(monkeypatch, runner):
    _patch_run_step(monkeypatch, fail_raws=('assert_text: "Invented"',))
    from app.agent.planner import PlannedStep
    seen = []

    def form(sc: SkillContext):
        seen.append(dict(sc.args))
        return []

    def outer(sc: SkillContext):
        ran = sc.run_planned([PlannedStep("test_form", value="submit=true"),
                              PlannedStep("assert_text", target="Invented"),
                              PlannedStep("click", target="Never reached")])
        return [info("ran", str(len(ran)))]

    with _Skill(ActionType.TEST_FORM, form), _Skill(ActionType.TEST_PAGE, outer):
        result = _flow(runner, '# T\n\n## S\n- test_page\n- click: "after"\n')
    assert seen == [{}]                                       # the model's "submit=true" was dropped
    failed = next(s for s in result.steps if s.action.raw == 'assert_text: "Invented"')
    assert failed.soft and not failed.fails_flow
    assert not any(s.action.raw == 'click: "Never reached"' for s in result.steps)   # stops at a failure
    assert result.success and result.steps[-1].action.raw == 'click: "after"'


def test_bad_options_are_an_error_check_not_a_crash(monkeypatch, runner):
    _patch_run_step(monkeypatch)
    with _Skill(ActionType.TEST_WIDGETS, lambda sc: [info("max", str(sc.count("max", 5)))]):
        (marker,) = _flow(runner, '# T\n\n## S\n- test_widgets: "max=lots" | "timeout=-1"\n').steps
    checks = {c.name: c for c in marker.checks}
    assert checks["max"].detail == "5"
    assert checks["options valid"].outcome == "failed" and checks["options valid"].count == 2
    assert not marker.success


def test_a_probe_drops_the_oracles_dialog_check_but_keeps_the_rest(monkeypatch, runner):
    _patch_run_step(monkeypatch)
    monkeypatch.setattr(oracle, "observe_after", lambda page, rec, since, ignore: ({}, [
        Check(oracle.DIALOG_CHECK, False, "warn", "modal dialog open: Edit"),
        Check("no console errors", False, "warn", "boom")]))

    def opens(sc: SkillContext):
        sc.run(ActionType.CLICK, "Edit", kind="probe")
        sc.run(ActionType.CLICK, "Other")
        return []

    with _Skill(ActionType.TEST_WIDGETS, opens):
        _, probe, action = _flow(runner, '# T\n\n## S\n- test_widgets\n').steps
    assert [c.name for c in probe.checks] == ["no console errors"]
    assert [c.name for c in action.checks] == [oracle.DIALOG_CHECK, "no console errors"]


def test_budgets_live_in_the_call_not_in_shared_state(monkeypatch, runner):
    """A skill's limit bounds what it starts, never the next flow line — even
    when a nested skill crashes."""
    _patch_run_step(monkeypatch)

    def crash(sc: SkillContext):
        raise RuntimeError("nested boom")

    def limited(sc: SkillContext):
        sc.run(ActionType.CLICK, "one", kind="probe")
        sc.run_skill(ActionType.TEST_WIDGETS)                    # crashes inside
        refused = sc.run(ActionType.CLICK, "two", kind="probe")  # over this skill's max_actions=1
        return [info("two", refused.message)]

    def free(sc: SkillContext):
        return [info("pressed", str(sum(sc.run(ActionType.CLICK, n, kind="probe").success for n in "abc")))]

    with _Skill(ActionType.TEST_WIDGETS, crash), _Skill(ActionType.TEST_PAGE, limited), _Skill(ActionType.TEST_TABLE, free):
        result = _flow(runner, '# T\n\n## A\n- test_page: "max_actions=1"\n\n## B\n- test_table\n')
    first = next(s for s in result.steps if s.action.type == ActionType.TEST_PAGE)
    second = next(s for s in result.steps if s.action.type == ActionType.TEST_TABLE)
    assert {c.name: c.detail for c in first.checks}["two"].startswith("not run — action limit")
    assert {c.name: c.detail for c in second.checks}["pressed"] == "3"    # nothing left over from A


def test_a_skill_run_twice_keeps_each_steps_own_screenshots(monkeypatch, runner):
    """Screenshots are numbered per run: the second test_responsive never
    overwrites the first one's files, so each step shows what it saw."""
    from pathlib import Path
    _patch_run_step(monkeypatch)

    def shoots(sc: SkillContext):
        sc.screenshot("390x664")
        return []

    with _Skill(ActionType.TEST_RESPONSIVE, shoots):
        result = _flow(runner, '# T\n\n## A\n- test_responsive\n\n## B\n- test_responsive\n')
    first, second = (s.evidence.screenshots["390x664"] for s in result.steps)
    assert first != second and Path(first).exists() and Path(second).exists()
    assert "test_responsive__390x664" in Path(first).name
