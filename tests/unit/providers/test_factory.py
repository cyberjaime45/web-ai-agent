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
