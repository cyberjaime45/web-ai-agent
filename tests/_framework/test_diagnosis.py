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
    assert verdict == "timing" and "still loading" in summary


@pytest.mark.parametrize("error, verdict, expected", [
    ("page.goto: net::ERR_NAME_NOT_RESOLVED at https://x.test", "environment", "ERR_NAME_NOT_RESOLVED"),
    ("Environment variable 'FMS_PASSWORD' is not set (referenced in step 3)", "framework", "<FMS_PASSWORD>"),
    ("Failed to load sub-flow 'components/login': Flow file not found", "framework", "sub-flow"),
    ("Target page, context or browser has been closed", "environment", "closed"),
])
def test_environment_and_framework_problems(error, verdict, expected):
    got, summary, _ = _verdict(_failed(ActionType.GOTO, "https://x.test", error=error))
    assert got == verdict and expected in summary


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


def test_a_javascript_error_earlier_in_the_section_is_a_signal_not_a_verdict(page_state):
    section = ([{"level": "pageerror", "text": "ReferenceError: gtag is not defined"}], [])
    d = diagnosis.diagnose(_failed(ActionType.ASSERT_TEXT, "Membership that moves you"), page=None, section=section)
    assert d["verdict"] == "unclassified"
    assert "JavaScript error earlier in this section: ReferenceError: gtag is not defined" in d["signals"]


# ── triage: the cause the engine reads before recovery ──────────────────────

class _Recorder:
    def __init__(self, failures=(), errors=(), pending=()):
        self._failures, self._errors, self._pending = list(failures), list(errors), list(pending)

    def failures_since(self, seq, limit=20):
        return self._failures

    def errors_since(self, seq, limit=20):
        return self._errors

    def pending(self, types, max_age_s, ignore=()):
        return self._pending


class _Page:
    def __init__(self, url="https://x.test/members", **probe):
        self.url = url
        self.probe = {"readyState": "complete", "textLength": 100, "spinner": 0, **probe}

    def evaluate(self, js):
        return self.probe


def _triage(error=TIMEOUT, kind=ActionType.CLICK, target="Save", page=None, recorder=None,
            prev_url="https://x.test/members"):
    return diagnosis.triage(error, FlowAction(type=kind, args=[target]), page or _Page(), recorder,
                            prev_url=prev_url)


def test_triage_reads_the_error_text_first():
    assert _triage("page.goto: net::ERR_CONNECTION_REFUSED") == "network"
    assert _triage("Target page, context or browser has been closed") == "closed"


def test_triage_reads_the_recorder_before_the_page():
    broken = {"method": "GET", "url": "https://x.test/api", "status": 500, "failure": None, "resource_type": "xhr"}
    assert _triage(recorder=_Recorder(failures=[broken])) == "server"
    image = {**broken, "resource_type": "image", "status": 404}
    assert _triage(recorder=_Recorder(failures=[image])) == "not_found"          # a broken image is not the page
    assert _triage(recorder=_Recorder(errors=[{"level": "pageerror", "text": "boom"}])) == "script"
    assert _triage(recorder=_Recorder(errors=[{"level": "error", "text": "boom"}])) == "not_found"


def test_triage_reads_one_probe_for_blank_and_loading_pages():
    assert _triage(page=_Page(textLength=0)) == "blank"
    assert _triage(page=_Page(spinner=2)) == "loading"
    assert _triage(page=_Page(readyState="loading")) == "loading"
    assert _triage(recorder=_Recorder(pending=["https://x.test/api/list"])) == "loading"


def test_triage_tells_session_covered_ambiguous_and_disabled_apart():
    login = _Page(url="https://x.test/login?next=/members")
    assert _triage(page=login) == "session"                                    # sent there from /members
    assert _triage(page=login, prev_url="https://x.test/login") == "not_found"  # working on the sign-in page
    assert _triage(page=login, prev_url="") == "not_found"                      # first step of the flow
    assert _triage(page=_Page(url="https://x.test/login"), target="Sign in") == "not_found"
    assert _triage(kind=ActionType.GOTO, page=_Page(url="https://x.test/login")) == "not_found"
    assert _triage("<div> intercepts pointer events") == "covered"
    assert _triage("strict mode violation: resolved to 3 elements") == "ambiguous"
    assert _triage("element is not enabled") == "disabled"


def test_triage_never_raises():
    class Dead:
        url = "https://x.test/"

        def evaluate(self, js):
            raise RuntimeError("closed")
    assert _triage(page=Dead()) == "not_found"


def test_diagnosis_reads_the_engines_triage_and_recovery():
    sr = _failed(ActionType.ASSERT_TEXT, "Welcome", layers={
        "L1 exact": "failed", "recovery": "waited 10000 ms for the page to settle — it did not settle: 1 loading indicator(s) still visible",
        "triage": "loading"})
    verdict, summary, signals = _verdict(sr)
    assert verdict == "timing" and "did not settle" in summary
    assert signals[0].startswith("waited 10000 ms")


def test_expected_and_observed_frame_the_verdict(page_state):
    page_state["probe"] = {"no blocking dialog": "modal dialog open: Session expired"}
    sr = _failed(ActionType.CLICK, "Save", url="https://x.test/profile", title="Profile")
    d = diagnosis.diagnose(sr, page=None, notes=['the step before, click: "Edit", changed nothing visible on the page'])
    assert d["expected"] == '"Save" can be pressed and the page reacts'
    assert d["observed"].startswith("the page 'Profile' at https://x.test/profile; modal dialog open: Session expired; Locator.click")
    assert d["signals"][0].startswith("the step before")
    assert diagnosis.expected_of(FlowAction(type=ActionType.FILL, args=["Name", "Ada"])) == '"Name" accepts the value "Ada"'
    assert diagnosis.expected_of(FlowAction(type=ActionType.TEST_PAGE, args=[])) == "test page completes"
