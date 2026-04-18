"""Unit tests for OpenAIProvider."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def _mock_response(text: str):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))]
    )


def test_complete_maps_system_and_user_to_messages():
    from app.layers.providers.openai_provider import OpenAIProvider

    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _mock_response("hi")

    with patch(
        "app.layers.providers.openai_provider.OpenAI",
        return_value=fake_client,
    ):
        provider = OpenAIProvider(api_key="k", model="gpt-4o-mini")
        out = provider.complete("SYS", "USR", temperature=0.0, max_tokens=123)

    assert out == "hi"
    fake_client.chat.completions.create.assert_called_once_with(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "SYS"},
            {"role": "user", "content": "USR"},
        ],
        temperature=0.0,
        max_tokens=123,
    )


def test_complete_returns_empty_string_when_content_is_none():
    from app.layers.providers.openai_provider import OpenAIProvider

    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _mock_response(None)

    with patch(
        "app.layers.providers.openai_provider.OpenAI",
        return_value=fake_client,
    ):
        provider = OpenAIProvider(api_key="k", model="gpt-4o-mini")
        assert provider.complete("s", "u") == ""
