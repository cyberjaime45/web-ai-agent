"""OpenAI SDK adapter for LLMProvider."""

from __future__ import annotations

from openai import OpenAI

from app.layers.providers.base import LLMProvider


class OpenAIProvider(LLMProvider):
    def __init__(self, api_key: str, model: str) -> None:
        self._model = model
        self._client = OpenAI(api_key=api_key)

    def complete(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.0,
        max_tokens: int = 500,
    ) -> str:
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return resp.choices[0].message.content or ""
