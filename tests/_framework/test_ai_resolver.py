"""Unit tests for AIResolver with a fake LLM provider."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.agent.observer import Field, Form, Node, Observation
from app.layers.ai_resolver import AIResolver
from app.layers.providers.base import LLMProvider
from app.schemas.actions import ActionType, FlowAction, StepResult


class FakeProvider(LLMProvider):
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[dict] = []

    def complete(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.0,
        max_tokens: int = 500,
    ) -> str:
        self.calls.append(
            {
                "system": system,
                "user": user,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )
        return self.response


def _action(kind: ActionType = ActionType.AI_ASSERT, args=("page is loaded",)) -> FlowAction:
    return FlowAction(type=kind, args=list(args), raw="", step_num=1)


def test_available_false_when_provider_is_none():
    resolver = AIResolver(provider=None)
    assert resolver.available is False


def test_available_true_when_provider_set():
    resolver = AIResolver(provider=FakeProvider("ignored"))
    assert resolver.available is True


def test_ai_assert_parses_provider_json_response():
    provider = FakeProvider('{"result": true, "reason": "all good"}')
    resolver = AIResolver(provider=provider)

    page = MagicMock()
    page.url = "http://x"
    page.title.return_value = "t"
    page.inner_text.return_value = "some page text"

    result = resolver.resolve_ai_action(_action(), page, ctx=None)
    assert isinstance(result, StepResult)
    assert result.success is True
    assert result.layer_used == 3
    assert "all good" in result.message
    assert len(provider.calls) == 1


def test_resolve_returns_none_when_provider_unavailable():
    resolver = AIResolver(provider=None)
    assert resolver.resolve(_action(), MagicMock(), error="boom") is None


def test_resolve_ai_action_returns_none_when_provider_unavailable():
    resolver = AIResolver(provider=None)
    assert resolver.resolve_ai_action(_action(), MagicMock()) is None


# ── L3 only executes element interactions ──────────────────────────────────


def test_supports_only_locator_actions():
    assert AIResolver.supports(ActionType.CLICK)
    assert AIResolver.supports(ActionType.FILL)
    for kind in (ActionType.ASSERT_TEXT, ActionType.WAIT_FOR_TEXT, ActionType.PRESS, ActionType.GOTO):
        assert not AIResolver.supports(kind), kind


def test_execute_with_locator_rejects_unsupported_action():
    import pytest
    loc = MagicMock()
    with pytest.raises(ValueError, match="cannot execute 'assert_text'"):
        AIResolver._execute_with_locator(_action(ActionType.ASSERT_TEXT, args=("x",)), loc)
    loc.click.assert_not_called()


def test_execute_with_locator_passes_value_for_fill():
    loc = MagicMock()
    AIResolver._execute_with_locator(_action(ActionType.FILL, args=("Email", "a@b.c")), loc)
    loc.fill.assert_called_once_with("a@b.c")


# ── L3 suggestions are grounded in the observation ─────────────────────────

class _Loc:
    def __init__(self, n=1):
        self.n, self.clicked = n, 0
        self.first = self

    def count(self):
        return self.n

    def click(self):
        self.clicked += 1


class _Page:
    url = "http://x"

    def __init__(self):
        self.roles, self.labels, self.css = [], [], []

    def title(self):
        return "t"

    def get_by_role(self, role, name=None, exact=False):
        self.roles.append((role, name))
        return type("L", (), {"nth": lambda s, k: _Loc()})()

    def get_by_label(self, value, exact=False):
        self.labels.append(value)
        return _Loc()

    def locator(self, value):
        self.css.append(value)
        return _Loc()


def _ob():
    return Observation(nodes=[Node(ref="e1", role="button", name="Save"), Node(ref="e2", role="link", name="Help")],
                       forms=[Form(name="f", fields=[Field(label="Email", type="email", target="Email", placeholder="you@x")], submits=[])])


def test_build_locator_accepts_a_ref_or_an_observed_name_and_refuses_selectors():
    page = _Page()
    assert AIResolver._build_locator(page, {"ref": "e2"}, _ob()) is not None and page.roles == [("link", "Help")]
    assert AIResolver._build_locator(page, {"strategy": "role", "role": "button", "value": "save"}, _ob()) is not None
    assert AIResolver._build_locator(page, {"strategy": "label", "value": "Email"}, _ob()) is not None and page.labels == ["Email"]
    assert AIResolver._build_locator(page, {"strategy": "css", "value": "#save"}, _ob()) is None
    assert AIResolver._build_locator(page, {"strategy": "text", "value": "Delete"}, _ob()) is None   # not on the page
    assert AIResolver._build_locator(page, {"ref": "e99"}, _ob()) is None
    assert page.css == []                                                   # a selector never reached Playwright


def test_resolve_runs_the_grounded_locator_and_tells_the_model_why_l1_failed(monkeypatch):
    import app.layers.ai_resolver as mod
    monkeypatch.setattr(mod, "observe", lambda page: _ob())
    provider = FakeProvider('{"ref": "e1", "reason": "the save button"}')
    page = _Page()
    result = AIResolver(provider).resolve(_action(ActionType.CLICK, args=("Guardar",)), page, error="Timeout 5000ms", cause="not_found")
    assert result is not None and result.success and result.layer_used == 3
    assert "[ref=e1] button \"Save\"" in provider.calls[0]["user"] and "triage): not found" in provider.calls[0]["user"]
    assert 'field "Email" (email) placeholder "you@x"' in provider.calls[0]["user"]
    assert page.roles == [("button", "Save")]
