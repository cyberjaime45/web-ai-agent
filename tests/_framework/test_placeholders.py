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
