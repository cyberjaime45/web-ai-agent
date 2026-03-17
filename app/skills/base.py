"""
Skill base class — all agent skills inherit from this.

A Skill is a named, reusable capability that composes one or more
tool calls into a meaningful operation the agent can reason about.

Example concrete skills (to be implemented under skills/web/, skills/api/ etc.):
    - LoginSkill           → open URL, fill credentials, click submit, assert URL
    - AssertFooterLinksSkill → scroll to footer, assert each link is visible
    - SearchProductSkill   → fill search input, submit, assert result count
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Skill(ABC):
    """Abstract base class for all agent skills."""

    #: Short machine-readable name used by the orchestrator to select this skill.
    name: str = ""

    #: Human-readable description used in planning prompts.
    description: str = ""

    @abstractmethod
    def execute(self, **kwargs: Any) -> Any:
        """Execute the skill. Subclasses define their own typed signature."""
        ...

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name!r})"
