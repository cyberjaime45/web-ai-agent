"""Failure diagnosis: verdicts from the evidence a failed step already carries."""

from __future__ import annotations

import pytest

from app.observability import diagnosis
from app.schemas.actions import ActionType, Evidence, FlowAction, StepResult

TIMEOUT = "Locator.click: Timeout 5000ms exceeded."


@pytest.fixture(autouse=True)
def page_state(monkeypatch):
    """No browser: the probe and the observed names are set per test."""
    state = {"probe": {}, "names": []}
    monkeypatch.setattr(diagnosis, "_probe", lambda page: state["probe"])
    monkeypatch.setattr(diagnosis, "_names", lambda page: state["names"])
    return state


def _failed(kind: ActionType, target: str = "Save", error: str = TIMEOUT, **evidence) -> StepResult:
    return StepResult(action=FlowAction(type=kind, args=[target]), success=False, message=error,
                      error=error, evidence=Evidence(**evidence))


def _verdict(sr: StepResult) -> tuple[str, str, list[str]]:
    d = diagnosis.diagnose(sr, page=None)
    return d["verdict"], d["summary"], d["signals"]


def test_server_error_during_the_step_is_an_application_defect():
    sr = _failed(ActionType.CLICK, network=[
        {"method": "POST", "url": "https://x.test/api/save", "status": 500, "failure": None}])
    verdict, summary, signals = _verdict(sr)
    assert verdict == "application" and "failed on the server" in summary
    assert "POST https://x.test/api/save → 500" in signals[0]


def test_aborted_requests_are_not_server_failures():
    sr = _failed(ActionType.CLICK, network=[
        {"method": "GET", "url": "https://x.test/a.js", "status": None, "failure": "net::ERR_ABORTED"}])
    assert _verdict(sr)[0] != "application"


def test_javascript_error_is_an_application_defect():
    sr = _failed(ActionType.ASSERT_TEXT, console=[{"level": "pageerror", "text": "TypeError: x is undefined"}])
    verdict, _, signals = _verdict(sr)
    assert verdict == "application" and "TypeError" in signals[0]


def test_blank_page_and_stuck_spinner(page_state):
    page_state["probe"] = {"page rendered": "no visible text on the page"}
    assert _verdict(_failed(ActionType.ASSERT_TEXT))[1] == "The page did not render."
    page_state["probe"] = {"no stuck spinner": "1 loading indicator(s) visible"}
    verdict, summary, _ = _verdict(_failed(ActionType.ASSERT_TEXT))
    assert verdict == "application" and "still loading" in summary


@pytest.mark.parametrize("error, expected", [
    ("page.goto: net::ERR_NAME_NOT_RESOLVED at https://x.test", "ERR_NAME_NOT_RESOLVED"),
    ("Environment variable 'FMS_PASSWORD' is not set (referenced in step 3)", "<FMS_PASSWORD>"),
    ("Target page, context or browser has been closed", "closed"),
])
def test_environment_problems(error, expected):
    verdict, summary, _ = _verdict(_failed(ActionType.GOTO, "https://x.test", error=error))
    assert verdict == "environment" and expected in summary


def test_landing_on_a_sign_in_page_is_a_session_problem():
    verdict, summary, signals = _verdict(_failed(ActionType.CLICK, "Members", url="https://x.test/login?next=/members"))
    assert verdict == "environment" and "session expired" in summary
    assert signals == ["the browser is on a sign-in page: https://x.test/login?next=/members"]


def test_clicking_the_sign_in_button_is_not_a_session_problem():
    assert _verdict(_failed(ActionType.CLICK, "Sign in", url="https://x.test/login"))[0] != "environment"


def test_covered_ambiguous_and_disabled_targets_are_test_issues(page_state):
    page_state["probe"] = {"no blocking dialog": "modal dialog open: Cookies"}
    verdict, summary, signals = _verdict(_failed(ActionType.CLICK, error="<div> intercepts pointer events"))
    assert verdict == "test" and "covered" in summary and "modal dialog open: Cookies" in signals
    assert "several elements" in _verdict(_failed(ActionType.CLICK, error="strict mode violation: 3 elements"))[1]
    assert "disabled" in _verdict(_failed(ActionType.CLICK, error="element is not enabled"))[1]


def test_changed_text_names_the_closest_control(page_state):
    page_state["names"] = ["Members", "Find a member", "Search members"]
    verdict, summary, signals = _verdict(_failed(ActionType.CLICK, "Search member"))
    assert verdict == "test"
    assert '"Search members" is' in summary and "similar" in signals[0]


def test_missing_text_with_nothing_similar_is_unclassified(page_state):
    page_state["names"] = ["Home", "Contact"]
    verdict, summary, signals = _verdict(_failed(ActionType.ASSERT_TEXT, "Membership that moves you",
                                                 url="https://x.test/"))
    assert verdict == "unclassified" and "nothing similar" in summary
    assert signals[-1] == "page at the failure: https://x.test/"


def test_first_cause_wins_but_every_signal_is_listed():
    sr = _failed(ActionType.CLICK, error="<div> intercepts pointer events",
                 network=[{"method": "GET", "url": "https://x.test/api", "status": 503, "failure": None}])
    verdict, _, signals = _verdict(sr)
    assert verdict == "application" and len(signals) == 2


def test_diagnose_never_raises(monkeypatch):
    monkeypatch.setattr(diagnosis, "_diagnose", lambda sr, page: 1 / 0)
    assert diagnosis.diagnose(_failed(ActionType.CLICK), page=None)["verdict"] == "unclassified"


def test_a_server_error_earlier_in_the_section_explains_missing_text(page_state):
    page_state["names"] = ["Orders"]
    section = ([], [{"method": "GET", "url": "https://x.test/api/orders", "status": 500, "failure": None}])
    d = diagnosis.diagnose(_failed(ActionType.ASSERT_TEXT, "Order history"), page=None, section=section)
    assert d["verdict"] == "application" and "earlier in this section" in d["summary"]


def test_a_loosely_similar_name_is_not_called_a_text_change(page_state):
    page_state["names"] = ["Orders"]                    # 63% similar to "Order history"
    assert _verdict(_failed(ActionType.ASSERT_TEXT, "Order history"))[0] == "unclassified"
