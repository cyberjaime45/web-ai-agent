"""LLM provider abstraction for Layer 3 (AIResolver)."""

from __future__ import annotations

from app.layers.providers.base import LLMProvider


class ConfigError(Exception):
    """Raised when AI provider configuration is invalid or incomplete."""


__all__ = ["LLMProvider", "ConfigError"]
