"""Unit tests for GeminiProvider (google-genai SDK)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def _provider(fake_client):
    from app.layers.providers import gemini_provider
    with patch.object(gemini_provider.genai, "Client", return_value=fake_client) as mock_client:
        provider = gemini_provider.GeminiProvider(api_key="k", model="gemini-2.5-flash")
    return provider, mock_client


def test_complete_sends_the_key_model_system_instruction_and_limits():
    fake_client = MagicMock()
    fake_client.models.generate_content.return_value = SimpleNamespace(text="hello")
    provider, mock_client = _provider(fake_client)

    out = provider.complete("SYS", "USR", temperature=0.1, max_tokens=222)

    assert out == "hello"
    mock_client.assert_called_once()
    assert mock_client.call_args.kwargs["api_key"] == "k"
    fake_client.models.generate_content.assert_called_once()
    kwargs = fake_client.models.generate_content.call_args.kwargs
    assert kwargs["model"] == "gemini-2.5-flash" and kwargs["contents"] == "USR"
    config = kwargs["config"]
    assert config.system_instruction == "SYS"
    assert config.temperature == 0.1 and config.max_output_tokens == 222


def test_each_call_carries_its_own_system_prompt():
    fake_client = MagicMock()
    fake_client.models.generate_content.return_value = SimpleNamespace(text="ok")
    provider, _ = _provider(fake_client)

    provider.complete("first", "u")
    provider.complete("second", "u")

    systems = [c.kwargs["config"].system_instruction for c in fake_client.models.generate_content.call_args_list]
    assert systems == ["first", "second"]


def test_complete_returns_empty_string_when_text_missing():
    fake_client = MagicMock()
    fake_client.models.generate_content.return_value = SimpleNamespace(text=None)
    provider, _ = _provider(fake_client)
    assert provider.complete("s", "u") == ""


def test_the_client_is_bounded_and_ignores_vertex_env_vars(monkeypatch):
    """A stuck call must not hold a flow step forever, and a stray
    GOOGLE_GENAI_USE_VERTEXAI in the shell must not reroute the key to Vertex AI."""
    from app.layers.providers import gemini_provider
    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "true")
    monkeypatch.setenv("GOOGLE_GENAI_USE_ENTERPRISE", "true")

    provider = gemini_provider.GeminiProvider(api_key="k", model="gemini-2.5-flash")   # the real Client

    client = provider._client._api_client
    assert client.vertexai is False and client.api_key == "k"
    assert client._http_options.timeout == gemini_provider.TIMEOUT_MS
    assert client._http_options.retry_options.attempts == gemini_provider.ATTEMPTS


def test_a_blocked_or_empty_answer_is_an_empty_string():
    """The SDK's own ``.text`` on a response with no candidates (a blocked prompt)."""
    from google.genai import types
    fake_client = MagicMock()
    fake_client.models.generate_content.return_value = types.GenerateContentResponse(candidates=[])
    provider, _ = _provider(fake_client)
    assert provider.complete("s", "u") == ""


def test_api_errors_reach_the_caller():
    """L3, the planner and the explainer catch provider errors themselves; the adapter must not hide them."""
    import pytest
    from google.genai import errors
    fake_client = MagicMock()
    fake_client.models.generate_content.side_effect = errors.ClientError(
        400, {"error": {"code": 400, "message": "API key not valid", "status": "INVALID_ARGUMENT"}})
    provider, _ = _provider(fake_client)
    with pytest.raises(errors.APIError):
        provider.complete("s", "u")
