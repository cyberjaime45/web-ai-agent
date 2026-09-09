"""LLM provider abstraction for Layer 3 (AIResolver)."""

from __future__ import annotations

from app.config.settings import settings
from app.layers.providers.base import LLMProvider


class ConfigError(Exception):
    """Raised when AI provider configuration is invalid or incomplete."""


_VALID_PROVIDERS = ("openai", "gemini", "anthropic")


def get_provider() -> LLMProvider | None:
    """Return the configured LLMProvider, or None if L3 is disabled.

    AI_PROVIDER is the switch: unset, empty, or whitespace-only disables L3
    regardless of LLM_KEY / LLM_MODEL. Once a provider is named, both
    LLM_KEY and LLM_MODEL must be non-blank, and the name must be a known
    provider — anything else raises ConfigError naming the problem.
    """
    provider = (settings.ai_provider or "").strip().lower()
    key      = (settings.llm_key or "").strip()
    model    = (settings.llm_model or "").strip()

    if not provider:
        return None

    missing = [name for name, value in (("LLM_KEY", key), ("LLM_MODEL", model)) if not value]
    if missing:
        raise ConfigError(
            "Incomplete LLM configuration — AI_PROVIDER is configured but missing: "
            + ", ".join(missing)
        )

    if provider not in _VALID_PROVIDERS:
        raise ConfigError(
            f"Invalid AI_PROVIDER: {settings.ai_provider!r}. "
            f"Must be one of: {', '.join(_VALID_PROVIDERS)}"
        )

    if provider == "openai":
        from app.layers.providers.openai_provider import OpenAIProvider
        return OpenAIProvider(api_key=key, model=model)
    if provider == "gemini":
        from app.layers.providers.gemini_provider import GeminiProvider
        return GeminiProvider(api_key=key, model=model)
    # provider == "anthropic"
    from app.layers.providers.anthropic_provider import ClaudeProvider
    return ClaudeProvider(api_key=key, model=model)


__all__ = ["LLMProvider", "ConfigError", "get_provider"]
