"""
Actions — data types for flow steps and execution results.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ActionType(str, Enum):
    # ── Navigation ────────────────────────────────────────────────
    OPEN                  = "open"
    SCROLL                = "scroll"
    SCROLL_TO             = "scroll_to"

    # ── Interaction ───────────────────────────────────────────────
    CLICK                 = "click"
    CLICK_LINK            = "click_link"
    CLICK_BUTTON          = "click_button"
    DOUBLE_CLICK          = "double_click"
    FILL                  = "fill"
    CLEAR                 = "clear"
    FOCUS                 = "focus"
    SELECT                = "select"
    CHECK                 = "check"
    UNCHECK               = "uncheck"
    HOVER                 = "hover"
    PRESS_KEY             = "press_key"

    # ── Assertions ────────────────────────────────────────────────
    ASSERT_TEXT           = "assert_text"
    ASSERT_TITLE          = "assert_title"
    ASSERT_URL            = "assert_url"
    ASSERT_LINK           = "assert_link"
    ASSERT_ELEMENT_VISIBLE = "assert_element_visible"
    ASSERT_ELEMENT_HIDDEN  = "assert_element_hidden"
    ASSERT_BUTTON_ENABLED  = "assert_button_enabled"
    ASSERT_BUTTON_DISABLED = "assert_button_disabled"

    # ── Waits ─────────────────────────────────────────────────────
    WAIT                  = "wait"
    WAIT_FOR_LOAD         = "wait_for_load"
    WAIT_FOR_ELEMENT      = "wait_for_element"
    WAIT_FOR_TEXT         = "wait_for_text"
    WAIT_FOR_URL          = "wait_for_url"

    # ── Utilities ─────────────────────────────────────────────────
    SCREENSHOT            = "screenshot"


# Keyword aliases accepted in .md files
ACTION_ALIASES: dict[str, ActionType] = {
    # Navigation
    "go_to":          ActionType.OPEN,
    "navigate":       ActionType.OPEN,
    "goto":           ActionType.OPEN,
    # Fill
    "type":           ActionType.FILL,
    "enter":          ActionType.FILL,
    # Assertions
    "verify_text":    ActionType.ASSERT_TEXT,
    "check_text":     ActionType.ASSERT_TEXT,
    "assert":         ActionType.ASSERT_TEXT,
    "verify_url":     ActionType.ASSERT_URL,
    "assert_visible": ActionType.ASSERT_ELEMENT_VISIBLE,
    "assert_hidden":  ActionType.ASSERT_ELEMENT_HIDDEN,
    # Interaction
    "dblclick":       ActionType.DOUBLE_CLICK,
    "key":            ActionType.PRESS_KEY,
    "keypress":       ActionType.PRESS_KEY,
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
