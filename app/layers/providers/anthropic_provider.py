"""Anthropic Claude SDK adapter for LLMProvider."""

from __future__ import annotations

from anthropic import Anthropic

from app.layers.providers.base import LLMProvider

# Thinking counts toward max_tokens on current Claude models; callers size
# max_tokens for the answer alone, so give the request headroom.
_MIN_MAX_TOKENS = 4096


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
        # temperature is accepted for interface parity but not sent: current
        # Claude models reject sampling parameters (400).
        resp = self._client.messages.create(
            model=self._model,
            system=system,
            messages=[{"role": "user", "content": user}],
            max_tokens=max(max_tokens, _MIN_MAX_TOKENS),
        )
        if resp.stop_reason == "refusal":
            return ""
        return "".join(b.text for b in resp.content if b.type == "text")
