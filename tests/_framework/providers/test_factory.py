"""Tests for the LLM provider factory and ConfigError."""

from __future__ import annotations

import pytest


def test_config_error_is_exception():
    from app.layers.providers import ConfigError
    assert issubclass(ConfigError, Exception)


def test_llm_provider_is_abstract():
    from app.layers.providers.base import LLMProvider
    with pytest.raises(TypeError):
        LLMProvider()  # type: ignore[abstract]


from unittest.mock import patch


def _stub_settings(provider="", key="", model=""):
    """Return a fresh settings-like object; patch app.layers.providers.settings."""
    from types import SimpleNamespace
    return SimpleNamespace(ai_provider=provider, llm_key=key, llm_model=model)


def test_factory_returns_none_when_all_unset():
    from app.layers.providers import get_provider
    with patch("app.layers.providers.settings", _stub_settings()):
        assert get_provider() is None


def test_factory_raises_on_missing_key():
    from app.layers.providers import ConfigError, get_provider
    with patch(
        "app.layers.providers.settings",
        _stub_settings(provider="openai", model="gpt-4o-mini"),
    ):
        with pytest.raises(ConfigError, match="LLM_KEY"):
            get_provider()


def test_factory_raises_on_missing_model():
    from app.layers.providers import ConfigError, get_provider
    with patch(
        "app.layers.providers.settings",
        _stub_settings(provider="openai", key="k"),
    ):
        with pytest.raises(ConfigError, match="LLM_MODEL"):
            get_provider()


@pytest.mark.parametrize("provider", ["", "   ", None])
def test_factory_disables_l3_when_provider_is_blank_even_with_key_and_model(provider):
    """AI_PROVIDER is the switch: a leftover key/model must not block startup."""
    from app.layers.providers import get_provider
    with patch(
        "app.layers.providers.settings",
        _stub_settings(provider=provider, key="k", model="m"),
    ):
        assert get_provider() is None


def test_factory_names_every_missing_var_once_provider_is_set():
    from app.layers.providers import ConfigError, get_provider
    with (
        patch("app.layers.providers.settings", _stub_settings(provider="openai")),
        pytest.raises(
            ConfigError, match=r"AI_PROVIDER is configured but missing: LLM_KEY, LLM_MODEL$"
        ),
    ):
        get_provider()


def test_factory_treats_whitespace_key_and_model_as_missing():
    from app.layers.providers import ConfigError, get_provider
    with (
        patch(
            "app.layers.providers.settings",
            _stub_settings(provider="openai", key="  ", model="\t"),
        ),
        pytest.raises(ConfigError, match="missing: LLM_KEY, LLM_MODEL"),
    ):
        get_provider()


def test_factory_raises_on_invalid_provider_name():
    from app.layers.providers import ConfigError, get_provider
    with patch(
        "app.layers.providers.settings",
        _stub_settings(provider="cohere", key="k", model="m"),
    ):
        with pytest.raises(ConfigError, match="Invalid AI_PROVIDER"):
            get_provider()


def test_factory_returns_openai_provider():
    from app.layers.providers import get_provider
    from app.layers.providers.openai_provider import OpenAIProvider
    with patch("app.layers.providers.settings",
               _stub_settings(provider="openai", key="k", model="gpt-4o-mini")), \
         patch("app.layers.providers.openai_provider.OpenAI"):
        p = get_provider()
    assert isinstance(p, OpenAIProvider)


def test_factory_returns_gemini_provider():
    from app.layers.providers import get_provider
    from app.layers.providers.gemini_provider import GeminiProvider
    with patch("app.layers.providers.settings",
               _stub_settings(provider="gemini", key="k", model="gemini-1.5-flash")), \
         patch("app.layers.providers.gemini_provider.genai.configure"):
        p = get_provider()
    assert isinstance(p, GeminiProvider)


def test_factory_returns_claude_provider():
    from app.layers.providers import get_provider
    from app.layers.providers.anthropic_provider import ClaudeProvider
    with patch(
        "app.layers.providers.settings",
        _stub_settings(provider="anthropic", key="k", model="claude-haiku-4-5-20251001"),
    ), patch("app.layers.providers.anthropic_provider.Anthropic"):
        p = get_provider()
    assert isinstance(p, ClaudeProvider)
