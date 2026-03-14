"""
Schemas — Pydantic models for structured page state and agent actions.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class ActionType(str, Enum):
    CLICK = "click"
    FILL = "fill"
    NAVIGATE = "navigate"
    WAIT = "wait"
    ASSERT_TEXT = "assert_text"
    ASSERT_URL = "assert_url"
    SCREENSHOT = "screenshot"
    DONE = "done"
    FAIL = "fail"


class PageState(BaseModel):
    """Structured snapshot of the current page state sent to the AI planner."""

    url: str = ""
    title: str = ""
    labels: list[str] = Field(default_factory=list)
    buttons: list[str] = Field(default_factory=list)
    links: list[str] = Field(default_factory=list)
    inputs: list[InputField] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    visible_text_snippet: str = ""


class InputField(BaseModel):
    """Represents a form input on the page."""

    label: str = ""
    input_type: str = "text"
    name: str = ""
    placeholder: str = ""
    value: str = ""
    is_enabled: bool = True


# Rebuild PageState now that InputField is defined
PageState.model_rebuild()


class AgentAction(BaseModel):
    """An action proposed by the AI planner."""

    action: ActionType
    target: Optional[str] = None
    value: Optional[str] = None
    reason: str = ""


class AgentResponse(BaseModel):
    """Full response from the AI planner for a single step."""

    actions: list[AgentAction] = Field(default_factory=list)
    is_complete: bool = False
    summary: str = ""


class ActionResult(BaseModel):
    """Result of executing a single action."""

    action: AgentAction
    success: bool = True
    message: str = ""
    screenshot_path: Optional[str] = None
