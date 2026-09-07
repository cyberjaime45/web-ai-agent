"""Engine emits wall-clock step timestamps and skipped StepResults."""

from __future__ import annotations

import time

import pytest

from app.execution.engine import FlowRunner
from app.flow.parser import parse_flow_markdown
from app.schemas.actions import StepResult


class FakePage:
    url = "https://x.test/"

    def title(self):
        return "t"


@pytest.fixture
def runner(tmp_path):
    return FlowRunner(artifacts_dir=str(tmp_path), flows_dir=tmp_path, provider=None)


def _patch_run_step(monkeypatch, fail_raws=()):
    def fake(self, action, page, runner, ctx):
        ok = action.raw not in fail_raws
        return StepResult(action=action, success=ok,
                          message="" if ok else "boom", layer_used=1)
    monkeypatch.setattr(FlowRunner, "_run_step", fake)


MD = """# T

## One
- click: "a"
- click: "b"

## Two
- click: "c"
"""


def test_steps_get_wallclock_timestamps(monkeypatch, runner):
    _patch_run_step(monkeypatch)
    before = time.time()
    result = runner.run(parse_flow_markdown(MD), FakePage())
    after = time.time()
    assert result.success
    for s in result.steps:
        assert before <= s.started_at <= s.ended_at <= after


def test_failed_section_steps_recorded_as_skipped(monkeypatch, runner):
    _patch_run_step(monkeypatch, fail_raws=('click: "a"',))
    result = runner.run(parse_flow_markdown(MD), FakePage())
    assert not result.success
    raws = [(s.action.raw, s.success, s.skipped) for s in result.steps]
    assert raws == [
        ('click: "a"', False, False),
        ('click: "b"', False, True),   # was silently dropped before
        ('click: "c"', True, False),   # next section still runs
    ]
    skipped = result.steps[1]
    assert skipped.started_at == 0.0 and skipped.ended_at == 0.0
    assert skipped.duration == 0.0
    # pass/fail math unchanged: skipped steps are not failures
    assert result.failed == 1 and result.skipped == 1
