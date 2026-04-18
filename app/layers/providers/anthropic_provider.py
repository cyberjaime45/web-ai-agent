"""Anthropic Claude SDK adapter for LLMProvider."""

from __future__ import annotations

from anthropic import Anthropic

from app.layers.providers.base import LLMProvider


class ClaudeProvider(LLMProvider):
    def __init__(self, api_key: str, model: str) -> None:
        self._model = model
        self._client = Anthropic(api_key=api_key)

    def complete(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.0,
        max_tokens: int = 500,
    ) -> str:
        resp = self._client.messages.create(
            model=self._model,
            system=system,
            messages=[{"role": "user", "content": user}],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if not resp.content:
            return ""
        return resp.content[0].text or ""
