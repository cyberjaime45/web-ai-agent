"""
Actions — data types for flow steps and execution results.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ActionType(str, Enum):
    OPEN             = "open"
    CLICK            = "click"
    CLICK_LINK       = "click_link"
    CLICK_BUTTON     = "click_button"
    FILL             = "fill"
    SELECT           = "select"
    CHECK            = "check"
    UNCHECK          = "uncheck"
    ASSERT_TEXT      = "assert_text"
    ASSERT_TITLE     = "assert_title"
    ASSERT_URL       = "assert_url"
    WAIT             = "wait"
    WAIT_FOR_LOAD    = "wait_for_load"
    WAIT_FOR_ELEMENT = "wait_for_element"
    SCREENSHOT       = "screenshot"
    SCROLL           = "scroll"
    HOVER            = "hover"


# Keyword aliases accepted in .md files
ACTION_ALIASES: dict[str, ActionType] = {
    "go_to":       ActionType.OPEN,
    "navigate":    ActionType.OPEN,
    "goto":        ActionType.OPEN,
    "type":        ActionType.FILL,
    "enter":       ActionType.FILL,
    "verify_text": ActionType.ASSERT_TEXT,
    "check_text":  ActionType.ASSERT_TEXT,
    "verify_url":  ActionType.ASSERT_URL,
    "assert":      ActionType.ASSERT_TEXT,
}


@dataclass
class FlowAction:
    type:     ActionType
    args:     list[str]
    raw:      str = ""   # original step text, for error messages
    step_num: int = 0


@dataclass
class StepResult:
    action:          FlowAction
    success:         bool
    message:         str
    layer_used:      int = 1          # 1=deterministic, 2=fallback, 3=AI
    screenshot_path: Optional[str] = None
    error:           Optional[str] = None


@dataclass
class FlowResult:
    flow_name: str
    success:   bool = False
    steps:     list[StepResult] = field(default_factory=list)
    error:     str = ""
    last_screenshot: Optional[str] = None

    @property
    def passed(self) -> int:
        return sum(1 for s in self.steps if s.success)

    @property
    def failed(self) -> int:
        return sum(1 for s in self.steps if not s.success)
