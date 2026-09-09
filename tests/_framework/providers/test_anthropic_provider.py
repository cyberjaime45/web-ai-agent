"""Unit tests for ClaudeProvider."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def _mock_response(text: str):
    return SimpleNamespace(content=[SimpleNamespace(text=text)])


def test_complete_uses_system_param_and_user_message():
    from app.layers.providers.anthropic_provider import ClaudeProvider

    fake_client = MagicMock()
    fake_client.messages.create.return_value = _mock_response("hi")

    with patch(
        "app.layers.providers.anthropic_provider.Anthropic",
        return_value=fake_client,
    ):
        provider = ClaudeProvider(api_key="k", model="claude-haiku-4-5-20251001")
        out = provider.complete("SYS", "USR", temperature=0.2, max_tokens=321)

    assert out == "hi"
    fake_client.messages.create.assert_called_once_with(
        model="claude-haiku-4-5-20251001",
        system="SYS",
        messages=[{"role": "user", "content": "USR"}],
        temperature=0.2,
        max_tokens=321,
    )


def test_complete_returns_empty_string_when_no_content():
    from app.layers.providers.anthropic_provider import ClaudeProvider

    fake_client = MagicMock()
    fake_client.messages.create.return_value = SimpleNamespace(content=[])

    with patch(
        "app.layers.providers.anthropic_provider.Anthropic",
        return_value=fake_client,
    ):
        provider = ClaudeProvider(api_key="k", model="claude-haiku-4-5-20251001")
        assert provider.complete("s", "u") == ""
