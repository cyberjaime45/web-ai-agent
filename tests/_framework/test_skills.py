"""Skill runtime: option parsing, marker + child steps, engine dispatch, oracle wiring."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.execution import oracle
from app.execution.engine import FlowRunner
from app.flow.parser import parse_flow_markdown
from app.schemas.actions import SKILL_ACTIONS, ActionType, Check, FlowAction, StepResult
from app.skills import SKILLS, parse_skill_args, run_skill
from app.skills.base import SkillContext, skill


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
    monkeypatch.setattr(oracle, "run_checks",
                        lambda page, rec, since, ignore: [Check("page rendered", False, "error", "blank")])
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
