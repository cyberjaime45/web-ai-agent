"""L1 blocker recovery: an interaction that failed at L1 is retried once after
a banner or modal was dismissed; assertions never are."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import app.layers.deterministic as det
from app.layers.deterministic import DeterministicRunner
from app.schemas.actions import ActionType, FlowAction, StepResult


@pytest.fixture
def runner(tmp_path, monkeypatch):
    monkeypatch.setattr(det, "settings", SimpleNamespace(dismiss_blockers=False))   # not the .env
    r = DeterministicRunner(page=object(), artifacts_dir=tmp_path)
    r.l1_calls = 0
    r.dismissed = []
    monkeypatch.setattr(r, "_layer2", lambda action, original_error: "L2")
    return r


def _l1(runner, monkeypatch, outcomes):
    """L1 raises or passes per call, in order."""
    def layer1(action):
        runner.l1_calls += 1
        if outcomes[runner.l1_calls - 1] == "raise":
            raise TimeoutError("element intercepts pointer events")
        return StepResult(action=action, success=True, message="ok")
    monkeypatch.setattr(runner, "_layer1", layer1)


def _dismiss(runner, monkeypatch, what):
    def dismiss(page):
        runner.dismissed.append(what)
        return what
    monkeypatch.setattr(det, "dismiss_blockers", dismiss)


def test_click_is_retried_after_a_blocker_is_dismissed(runner, monkeypatch):
    _l1(runner, monkeypatch, ["raise", "pass"])
    _dismiss(runner, monkeypatch, 'button:has-text("Accept") in [class*="cookie" i]')
    result = runner.execute(FlowAction(type=ActionType.CLICK, args=["Save"]))
    assert result.success and runner.l1_calls == 2
    check = result.checks[0]
    assert check.name == "dismissed blocker" and check.severity == "info" and "cookie" in check.detail


def test_nothing_dismissed_goes_straight_to_l2(runner, monkeypatch):
    _l1(runner, monkeypatch, ["raise"])
    _dismiss(runner, monkeypatch, None)
    assert runner.execute(FlowAction(type=ActionType.FILL, args=["Name", "x"])) == "L2"
    assert runner.l1_calls == 1


def test_retry_that_still_fails_falls_through_to_l2(runner, monkeypatch):
    _l1(runner, monkeypatch, ["raise", "raise"])
    _dismiss(runner, monkeypatch, "Escape on .modal.show")
    assert runner.execute(FlowAction(type=ActionType.CLICK, args=["Save"])) == "L2"
    assert runner.l1_calls == 2


@pytest.mark.parametrize("kind", [ActionType.ASSERT_HIDDEN, ActionType.ASSERT_TEXT, ActionType.WAIT_FOR_TEXT])
def test_assertions_never_dismiss_anything(runner, monkeypatch, kind):
    _l1(runner, monkeypatch, ["raise"])
    _dismiss(runner, monkeypatch, "Escape on .modal.show")
    assert runner.execute(FlowAction(type=kind, args=["Welcome"])) == "L2"
    assert runner.dismissed == []
