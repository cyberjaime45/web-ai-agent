"""Unit tests for AIResolver with a fake LLM provider."""

from __future__ import annotations

from unittest.mock import MagicMock

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
