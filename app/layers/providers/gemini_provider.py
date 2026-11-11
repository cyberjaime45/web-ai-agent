"""Google Gemini SDK adapter for LLMProvider (the ``google-genai`` SDK;
``google-generativeai`` is deprecated)."""

from __future__ import annotations

from google import genai
from google.genai import types

from app.layers.providers.base import LLMProvider

# The SDK sets no request timeout and no retries by default: one stuck call
# would hold a flow step indefinitely. 60 s covers a ≤ 500-token completion;
# 3 attempts mirror the OpenAI SDK's default of 2 retries (429 / 5xx).
TIMEOUT_MS = 60_000
ATTEMPTS = 3


class GeminiProvider(LLMProvider):
    def __init__(self, api_key: str, model: str) -> None:
        self._model = model
        # One client per provider (the factory builds one per session); the
        # system prompt travels with each request, so nothing is cached per prompt.
        # vertexai=False: otherwise the SDK reads GOOGLE_GENAI_USE_VERTEXAI /
        # GOOGLE_GENAI_USE_ENTERPRISE from the environment and may switch to
        # Vertex AI — configuration comes from settings only.
        self._client = genai.Client(
            api_key=api_key,
            vertexai=False,
            http_options=types.HttpOptions(
                timeout=TIMEOUT_MS,
                retry_options=types.HttpRetryOptions(attempts=ATTEMPTS),
            ),
        )

    def complete(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.0,
        max_tokens: int = 500,
    ) -> str:
        resp = self._client.models.generate_content(
            model=self._model,
            contents=user,
            config=types.GenerateContentConfig(
                system_instruction=system,
                temperature=temperature,
                max_output_tokens=max_tokens,
            ),
        )
        return resp.text or ""
