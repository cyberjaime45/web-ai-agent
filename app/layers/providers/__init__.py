"""LLM provider abstraction for Layer 3 (AIResolver)."""

from __future__ import annotations

from app.config.settings import settings
from app.layers.providers.base import LLMProvider


class ConfigError(Exception):
    """Raised when AI provider configuration is invalid or incomplete."""


_VALID_PROVIDERS = ("openai", "gemini", "anthropic")


def _missing_vars(provider: str, key: str, model: str) -> list[str]:
    missing: list[str] = []
    if not provider:
        missing.append("AI_PROVIDER")
    if not key:
        missing.append("LLM_KEY")
    if not model:
        missing.append("LLM_MODEL")
    return missing


def get_provider() -> LLMProvider | None:
    """Return the configured LLMProvider, or None if L3 is disabled.

    L3 is disabled only when all three env vars (AI_PROVIDER, LLM_KEY,
    LLM_MODEL) are unset. Any partial or invalid configuration raises
    ConfigError with a message naming the problem.
    """
    provider = (settings.ai_provider or "").strip().lower()
    key      = (settings.llm_key or "").strip()
    model    = (settings.llm_model or "").strip()

    if not provider and not key and not model:
        return None

    missing = _missing_vars(provider, key, model)
    if missing:
        raise ConfigError(
            "Incomplete LLM configuration — missing: "
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
