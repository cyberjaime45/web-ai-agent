"""Google Gemini SDK adapter for LLMProvider."""

from __future__ import annotations

import google.generativeai as genai

from app.layers.providers.base import LLMProvider


class GeminiProvider(LLMProvider):
    def __init__(self, api_key: str, model: str) -> None:
        genai.configure(api_key=api_key)
        self._model_name = model
        # One GenerativeModel per system prompt (there are a handful) instead
        # of a new one per completion — L3 can call twice per failed step.
        self._models: dict[str, genai.GenerativeModel] = {}

    def complete(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.0,
        max_tokens: int = 500,
    ) -> str:
        model = self._models.get(system)
        if model is None:
            model = self._models[system] = genai.GenerativeModel(
                model_name=self._model_name,
                system_instruction=system,
            )
        resp = model.generate_content(
            user,
            generation_config={
                "temperature": temperature,
                "max_output_tokens": max_tokens,
            },
        )
        return resp.text or ""
