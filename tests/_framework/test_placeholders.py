"""{NAME} placeholder resolution: the one substitution every step argument,
the site domain and the MCP catalog share. No browser."""

from __future__ import annotations

import pytest

from app.flow.parser import parse_flow_markdown
from app.flow.placeholders import (
    PlaceholderError,
    flow_site_domain,
    placeholder_names,
    resolve_env_placeholders,
    substitute,
)


def _step(line: str, section: str = "Schedule Page"):
    flow = parse_flow_markdown(f"# T\n\n## {section}\n{line}\n")
    return flow.actions[0]


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("WA_TEST_URL", "https://one.example.com")
    monkeypatch.setenv("WA_TEST_SLASH_URL", "https://one.example.com/")
    monkeypatch.setenv("WA_TEST_PASSWORD", "hunter2")
    monkeypatch.setenv("WA_TEST_EMPTY", "  ")
    monkeypatch.delenv("WA_TEST_UNSET", raising=False)


@pytest.mark.parametrize("arg, expected", [
    ("{WA_TEST_URL}", "https://one.example.com"),
    ("{WA_TEST_URL}/calendar/scheduleboard/", "https://one.example.com/calendar/scheduleboard/"),
    ("{WA_TEST_URL}/operations?tab=dashboard&x=1#top", "https://one.example.com/operations?tab=dashboard&x=1#top"),
    ("{WA_TEST_SLASH_URL}/leads", "https://one.example.com/leads"),        # no double slash
    ("{WA_TEST_SLASH_URL}", "https://one.example.com/"),
    ("<WA_TEST_URL>/calendar", "https://one.example.com/calendar"),       # legacy spelling
])
def test_goto_keeps_the_rest_of_the_url(arg, expected):
    resolved = resolve_env_placeholders(_step(f'- goto: "{arg}"'))
    assert resolved.args == [expected]


def test_every_argument_is_resolved_and_secrets_are_masked_in_the_step_text():
    resolved = resolve_env_placeholders(_step('- fill: "{WA_TEST_URL} login" | "pw-{WA_TEST_PASSWORD}"'))
    assert resolved.args == ["https://one.example.com login", "pw-hunter2"]
    assert "hunter2" not in resolved.raw and "pw-******" in resolved.raw
    assert "https://one.example.com login" in resolved.raw


@pytest.mark.parametrize("var, state", [("WA_TEST_UNSET", "not set"), ("WA_TEST_EMPTY", "empty")])
def test_an_unset_or_empty_variable_fails_naming_it_and_where(var, state):
    action = _step(f'- goto: "{{{var}}}/calendar"')
    with pytest.raises(PlaceholderError) as exc:
        resolve_env_placeholders(action)
    message = str(exc.value)
    assert f"Variable '{var}' is {state}" in message
    assert "step 1 in section 'Schedule Page'" in message and f"{{{var}}}/calendar" in message


def test_steps_without_placeholders_are_returned_as_they_are():
    action = _step('- assert_text: "Price {per seat} <b>"')       # lower-case braces are text
    assert resolve_env_placeholders(action) is action


def test_names_and_substitution_helpers():
    assert placeholder_names("{A_URL}/x/{B}/<A_URL>") == ["A_URL", "B"]
    assert substitute("{A}/{B}", {"A": "1"}.get) == ("1/{B}", ["B"])


def test_site_domain_comes_from_a_placeholder_with_a_path():
    flow = parse_flow_markdown('# T\n\n## S\n- goto: "{WA_TEST_URL}/calendar/scheduleboard/"\n')
    assert flow_site_domain(flow) == "example.com"
    unset = parse_flow_markdown('# T\n\n## S\n- goto: "{WA_TEST_UNSET}/x"\n')
    assert flow_site_domain(unset) == ""


def test_a_name_the_orchestrator_withheld_fails_as_any_unset_one_and_says_whose_it_was(monkeypatch):
    """Worded as an unset variable, so that it is diagnosed as the flow's setup and never run again for it; the
    advice to set it in .env would be wrong, and is not given."""
    from app.observability import diagnosis
    from app.schemas.actions import Evidence, StepResult
    monkeypatch.setenv("WEB_AGENT_WITHHELD", "WA_KEPT_BACK,WA_OTHER")
    monkeypatch.setenv("WA_KEPT_BACK", "")
    action = _step('- fill: "Password" | "{WA_KEPT_BACK}"')
    with pytest.raises(PlaceholderError) as exc:
        resolve_env_placeholders(action)
    message = str(exc.value)
    assert "Variable 'WA_KEPT_BACK' is not set for this run" in message and ".env are not used for it" in message
    assert "set it in .env" not in message
    failed = StepResult(action=action, success=False, message=message, error=message, evidence=Evidence())
    told = diagnosis.diagnose(failed, page=None)
    assert told["verdict"] == "framework" and "handed no value by the orchestrator" in told["summary"]


def test_what_a_run_was_handed_as_a_secret_is_masked_whatever_it_is_called(monkeypatch):
    """A seed, a pin or a user name an orchestrator brokers has no "password" in its name: the run is told the
    names it was handed, and the report masks them in the step's text and in what a failed step was expected to do."""
    from app.flow.placeholders import is_sensitive, mask_sensitive_values
    from app.observability.diagnosis import expected_of
    monkeypatch.setenv("WA_OTP_SEED", "JBSWY3DPEHPK3PXP")
    assert not is_sensitive("WA_OTP_SEED")
    plain = resolve_env_placeholders(_step('- fill: "Code" | "{WA_OTP_SEED}"'))
    assert "JBSWY3DPEHPK3PXP" in plain.raw                              # an ordinary input: shown as it is
    monkeypatch.setenv("WEB_AGENT_SECRET_NAMES", "WA_OTP_SEED,WA_TEST_USER")
    assert is_sensitive("WA_OTP_SEED") and not is_sensitive("WA_OTP")
    handed = resolve_env_placeholders(_step('- fill: "Code" | "{WA_OTP_SEED}"'))
    assert handed.args == ["Code", "JBSWY3DPEHPK3PXP"] and "JBSWY3DPEHPK3PXP" not in handed.raw
    assert expected_of(handed) == '"Code" accepts the value "******"'
    password = resolve_env_placeholders(_step('- fill: "Password" | "{WA_TEST_PASSWORD}"'))
    assert "hunter2" not in expected_of(password)                       # a password, as before in the step's text
    assert mask_sensitive_values("nothing of the kind") == "nothing of the kind"
