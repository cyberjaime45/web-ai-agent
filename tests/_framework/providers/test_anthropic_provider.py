"""Unit tests for ClaudeProvider."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def _mock_response(text: str, stop_reason: str = "end_turn"):
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=[SimpleNamespace(type="thinking", thinking=""),
                 SimpleNamespace(type="text", text=text)],
    )


def _provider(fake_client):
    from app.layers.providers.anthropic_provider import ClaudeProvider

    with patch(
        "app.layers.providers.anthropic_provider.Anthropic",
        return_value=fake_client,
    ):
        return ClaudeProvider(api_key="k", model="claude-haiku-4-5-20251001")


def test_complete_uses_system_param_and_user_message():
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _mock_response("hi")

    out = _provider(fake_client).complete("SYS", "USR", temperature=0.2, max_tokens=321)

    assert out == "hi"
    # temperature is not sent (current models 400 on it); max_tokens gets a floor
    fake_client.messages.create.assert_called_once_with(
        model="claude-haiku-4-5-20251001",
        system="SYS",
        messages=[{"role": "user", "content": "USR"}],
        max_tokens=4096,
    )


def test_complete_keeps_larger_max_tokens():
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _mock_response("hi")

    _provider(fake_client).complete("s", "u", max_tokens=8000)

    assert fake_client.messages.create.call_args.kwargs["max_tokens"] == 8000


def test_complete_skips_thinking_blocks():
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _mock_response('{"ok": true}')

    assert _provider(fake_client).complete("s", "u") == '{"ok": true}'


def test_complete_returns_empty_string_on_refusal():
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _mock_response("partial", stop_reason="refusal")

    assert _provider(fake_client).complete("s", "u") == ""


def test_complete_returns_empty_string_when_no_content():
    fake_client = MagicMock()
    fake_client.messages.create.return_value = SimpleNamespace(stop_reason="end_turn", content=[])

    assert _provider(fake_client).complete("s", "u") == ""
