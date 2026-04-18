"""Base interface for LLM providers consumed by Layer 3 (AIResolver)."""

from __future__ import annotations

from abc import ABC, abstractmethod


class LLMProvider(ABC):
    """Minimal single-turn completion interface.

    Providers translate a (system, user) prompt pair into their vendor
    SDK's call shape and return the raw text response. They do not log,
    parse JSON, or know anything about Playwright or flow actions.
    """

    @abstractmethod
    def complete(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.0,
        max_tokens: int = 500,
    ) -> str:
        """Return the model's text response to the system+user prompt."""
        raise NotImplementedError
