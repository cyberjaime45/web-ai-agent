"""
Actions — data types for flow steps and execution results.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ActionType(str, Enum):
    # ── Navigation ────────────────────────────────────────────────
    GOTO                  = "goto"
    RELOAD                = "reload"
    BACK                  = "back"
    WAIT_LOAD             = "wait_load"
    SWITCH_TAB            = "switch_tab"
    SCROLL                = "scroll"

    # ── Click ────────────────────────────────────────────────────
    CLICK                 = "click"
    CLICK_LINK_TEXT       = "click_link_text"
    CLICK_ID              = "click_id"
    CLICK_BUTTON          = "click_button"
    DOUBLE_CLICK          = "double_click"
    RIGHT_CLICK           = "right_click"
    HOVER                 = "hover"

    # ── Input ────────────────────────────────────────────────────
    FILL                  = "fill"
    TYPE                  = "type"
    CLEAR                 = "clear"
    FOCUS                 = "focus"
    SELECT                = "select"
    CHECK                 = "check"
    UNCHECK               = "uncheck"

    # ── Advanced ─────────────────────────────────────────────────
    DRAG_TO               = "drag_to"
    UPLOAD                = "upload"

    # ── Table / Data ─────────────────────────────────────────────
    READ_ROW              = "read_row"
    TABLE_CLICK           = "table_click"
    FIND_ROW              = "find_row"
    COUNT_ELEMENTS        = "count_elements"
    GET_ATTRIBUTE         = "get_attribute"

    # ── Assertions ───────────────────────────────────────────────
    ASSERT_TEXT           = "assert_text"
    ASSERT_NOT_TEXT       = "assert_not_text"
    ASSERT_VISIBLE        = "assert_visible"
    ASSERT_HIDDEN         = "assert_hidden"
    ASSERT_URL            = "assert_url"
    ASSERT_ENABLED        = "assert_enabled"
    ASSERT_DISABLED       = "assert_disabled"
    ASSERT_CHECKED        = "assert_checked"

    # ── Waits ────────────────────────────────────────────────────
    WAIT                  = "wait"
    WAIT_FOR_LOAD         = "wait_for_load"
    WAIT_FOR_ELEMENT      = "wait_for_element"
    WAIT_FOR_TEXT         = "wait_for_text"
    WAIT_FOR_URL          = "wait_for_url"

    # ── AI-native ────────────────────────────────────────────────
    AI_CLICK              = "ai_click"
    AI_EXTRACT            = "ai_extract"
    AI_ASSERT             = "ai_assert"
    AI_SUMMARIZE          = "ai_summarize"

    # ── Utilities ────────────────────────────────────────────────
    SCREENSHOT            = "screenshot"
    PRESS                 = "press"


# Keyword aliases accepted in .md files (old → new canonical)
ACTION_ALIASES: dict[str, ActionType] = {
    # ── Old canonical names (backward compat) ────────────────────
    "open":                    ActionType.GOTO,
    "click_link":              ActionType.CLICK_LINK_TEXT,
    "press_key":               ActionType.PRESS,
    "scroll_to":               ActionType.SCROLL,
    "assert_element_visible":  ActionType.ASSERT_VISIBLE,
    "assert_element_hidden":   ActionType.ASSERT_HIDDEN,
    "assert_button_enabled":   ActionType.ASSERT_ENABLED,
    "assert_button_disabled":  ActionType.ASSERT_DISABLED,
    "assert_title":            ActionType.ASSERT_TEXT,
    "assert_link":             ActionType.ASSERT_VISIBLE,
    "wait_load":               ActionType.WAIT_LOAD,

    # ── Convenience aliases ──────────────────────────────────────
    "go_to":           ActionType.GOTO,
    "navigate":        ActionType.GOTO,
    "enter":           ActionType.FILL,
    "verify_text":     ActionType.ASSERT_TEXT,
    "check_text":      ActionType.ASSERT_TEXT,
    "assert":          ActionType.ASSERT_TEXT,
    "verify_url":      ActionType.ASSERT_URL,
    "assert_visible":  ActionType.ASSERT_VISIBLE,
    "assert_hidden":   ActionType.ASSERT_HIDDEN,
    "dblclick":        ActionType.DOUBLE_CLICK,
    "key":             ActionType.PRESS,
    "keypress":        ActionType.PRESS,
}

# Old enum values that map to new ones — used by the parser to resolve
# keywords written as old enum .value strings (e.g. "wait_for_load")
_OLD_VALUE_MAP: dict[str, ActionType] = {
    "wait_for_load":  ActionType.WAIT_FOR_LOAD,
}


# Argument count spec: (min_args, max_args)
ACTION_ARG_SPEC: dict[ActionType, tuple[int, int]] = {
    ActionType.GOTO:            (1, 1),
    ActionType.RELOAD:          (0, 0),
    ActionType.BACK:            (0, 0),
    ActionType.WAIT_LOAD:       (0, 1),
    ActionType.SWITCH_TAB:      (1, 1),
    ActionType.SCROLL:          (0, 1),

    ActionType.CLICK:           (1, 1),
    ActionType.CLICK_LINK_TEXT: (1, 1),
    ActionType.CLICK_ID:        (1, 1),
    ActionType.CLICK_BUTTON:    (1, 1),
    ActionType.DOUBLE_CLICK:    (1, 1),
    ActionType.RIGHT_CLICK:     (1, 1),
    ActionType.HOVER:           (1, 1),

    ActionType.FILL:            (1, 2),
    ActionType.TYPE:            (1, 2),
    ActionType.CLEAR:           (1, 1),
    ActionType.FOCUS:           (1, 1),
    ActionType.SELECT:          (1, 2),
    ActionType.CHECK:           (1, 1),
    ActionType.UNCHECK:         (1, 1),

    ActionType.DRAG_TO:         (2, 2),
    ActionType.UPLOAD:          (2, 2),

    ActionType.READ_ROW:        (1, 1),
    ActionType.TABLE_CLICK:     (1, 2),
    ActionType.FIND_ROW:        (1, 1),
    ActionType.COUNT_ELEMENTS:  (1, 1),
    ActionType.GET_ATTRIBUTE:   (2, 2),

    ActionType.ASSERT_TEXT:     (1, 1),
    ActionType.ASSERT_NOT_TEXT: (1, 1),
    ActionType.ASSERT_VISIBLE:  (1, 1),
    ActionType.ASSERT_HIDDEN:   (1, 1),
    ActionType.ASSERT_URL:      (1, 1),
    ActionType.ASSERT_ENABLED:  (1, 1),
    ActionType.ASSERT_DISABLED: (1, 1),
    ActionType.ASSERT_CHECKED:  (1, 1),

    ActionType.WAIT:            (0, 1),
    ActionType.WAIT_FOR_LOAD:   (0, 0),
    ActionType.WAIT_FOR_ELEMENT:(1, 1),
    ActionType.WAIT_FOR_TEXT:   (1, 1),
    ActionType.WAIT_FOR_URL:    (1, 1),

    ActionType.AI_CLICK:        (1, 1),
    ActionType.AI_EXTRACT:      (1, 1),
    ActionType.AI_ASSERT:       (1, 1),
    ActionType.AI_SUMMARIZE:    (0, 0),

    ActionType.SCREENSHOT:      (0, 1),
    ActionType.PRESS:           (1, 1),
}

# Actions that bypass L1/L2 and go directly to L3 (AI)
AI_ONLY_ACTIONS: frozenset[ActionType] = frozenset({
    ActionType.AI_CLICK,
    ActionType.AI_EXTRACT,
    ActionType.AI_ASSERT,
    ActionType.AI_SUMMARIZE,
})

# Old aliases that imply a negated assertion (backward compat)
_NEGATED_ALIASES: frozenset[str] = frozenset({
    "assert_button_disabled",
    "assert_element_hidden",
})


@dataclass
class FlowAction:
    type:     ActionType
    args:     list[str]
    raw:      str = ""   # original step text, for error messages
    step_num: int = 0
    negated:  bool = False


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
