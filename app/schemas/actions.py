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
    WAIT_FOR_ELEMENT      = "wait_for_element"
    WAIT_FOR_TEXT         = "wait_for_text"
    WAIT_FOR_URL          = "wait_for_url"

    # ── AI-native ────────────────────────────────────────────────
    AI_CLICK              = "ai_click"
    AI_EXTRACT            = "ai_extract"
    AI_ASSERT             = "ai_assert"
    AI_SUMMARIZE          = "ai_summarize"

    # ── Flow Composition ────────────────────────────────────────
    RUN_FLOW              = "run_flow"

    # ── Utilities ────────────────────────────────────────────────
    SCREENSHOT            = "screenshot"
    PRESS                 = "press"

    # ── QA skills (orchestrate actions; see app/skills/) ─────────
    INSPECT_PAGE          = "inspect_page"
    CHECK_CONSOLE_NETWORK = "check_console_network"
    TEST_RESPONSIVE       = "test_responsive"
    TEST_FORM             = "test_form"
    EXPLORE_PAGE          = "explore_page"
    TEST_PAGE             = "test_page"

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
    ActionType.WAIT_FOR_ELEMENT:(1, 1),
    ActionType.WAIT_FOR_TEXT:   (1, 1),
    ActionType.WAIT_FOR_URL:    (1, 1),

    ActionType.AI_CLICK:        (1, 1),
    ActionType.AI_EXTRACT:      (1, 1),
    ActionType.AI_ASSERT:       (1, 1),
    ActionType.AI_SUMMARIZE:    (0, 0),

    ActionType.RUN_FLOW:        (1, 1),

    ActionType.SCREENSHOT:      (0, 1),
    ActionType.PRESS:           (1, 1),

    # Skills take `key=value` options; see app/skills/__init__.py
    ActionType.INSPECT_PAGE:          (0, 4),
    ActionType.CHECK_CONSOLE_NETWORK: (0, 4),
    ActionType.TEST_RESPONSIVE:       (0, 4),
    ActionType.TEST_FORM:             (0, 4),
    ActionType.EXPLORE_PAGE:          (0, 6),
    ActionType.TEST_PAGE:             (0, 8),
}

# Actions that bypass L1/L2 and go directly to L3 (AI)
AI_ONLY_ACTIONS: frozenset[ActionType] = frozenset({
    ActionType.AI_CLICK,
    ActionType.AI_EXTRACT,
    ActionType.AI_ASSERT,
    ActionType.AI_SUMMARIZE,
})

# Skills: handled by the engine like run_flow — a marker step followed by
# the child actions they execute through FlowRunner.execute. Never L1/L2/L3.
SKILL_ACTIONS: frozenset[ActionType] = frozenset({
    ActionType.INSPECT_PAGE,
    ActionType.CHECK_CONSOLE_NETWORK,
    ActionType.TEST_RESPONSIVE,
    ActionType.TEST_FORM,
    ActionType.EXPLORE_PAGE,
    ActionType.TEST_PAGE,
})

@dataclass
class FlowAction:
    type:     ActionType
    args:     list[str]
    raw:      str = ""   # original step text, for error messages
    step_num: int = 0
    section:  str = ""   # ## heading this action belongs to (empty for legacy "Steps")


@dataclass
class RunContext:
    """Per-run short-term memory — tracks execution state across steps.

    Scoped to a single FlowRunner.run() call. Reset between executions.
    No cross-test leakage: each run creates a fresh instance.
    """
    history: list[dict[str, str]] = field(default_factory=list)
    data:    dict[str, str] = field(default_factory=dict)

    def record(
        self,
        action: "FlowAction",
        result: "StepResult",
        url: str,
    ) -> None:
        """Append a step to history."""
        self.history.append({
            "action": action.type.value,
            "target": action.args[0] if action.args else "",
            "result": "pass" if result.success else "fail",
            "layer":  str(result.layer_used),
            "url":    url,
        })

    def store(self, key: str, value: str) -> None:
        """Store extracted data for use by subsequent steps."""
        self.data[key] = value

    def recent_history(self, n: int = 5) -> list[dict[str, str]]:
        """Return the last *n* steps for context summaries."""
        return self.history[-n:]


@dataclass
class Evidence:
    """Debugging bundle attached to a failed step (see observability/evidence.py).

    ``layers`` records what each resolution layer did, in order — e.g.
    ``{"L1 exact": "failed", "L2 fuzzy": "failed", "L3 AI": "skipped: provider
    not configured"}``. ``screenshots`` maps a kind (``viewport``, ``full_page``,
    ``element``) to an absolute path; the reporter makes them report-relative.
    """
    url:         str = ""
    title:       str = ""
    profile:     str = ""                                       # "mobile · iPhone 13 · chromium · 390x664"
    layers:      dict[str, str] = field(default_factory=dict)
    screenshots: dict[str, str] = field(default_factory=dict)
    trace:       Optional[str] = None                           # Playwright trace zip, set at flow end
    console:     list[dict] = field(default_factory=list)       # error/warning entries since the step started
    network:     list[dict] = field(default_factory=list)       # failed requests since the step started
    files:       dict[str, str] = field(default_factory=dict)   # label → other artifact (generated flow…)


@dataclass
class Check:
    """One automatic QA check — from the oracle after a step, or a skill's finding.

    ``severity`` says what a failed check means: ``error`` (a defect —
    fails the step in strict mode, always fails an explicit skill step),
    ``warn`` (worth a look, never fails), ``info`` (an observation;
    ``passed`` is always True).
    """
    name:     str
    passed:   bool = True
    severity: str = "error"
    detail:   str = ""


@dataclass
class StepResult:
    action:          FlowAction
    success:         bool
    message:         str
    layer_used:      int = 1          # 1=deterministic, 2=fallback, 3=AI
    sub_flow:        str = ""         # non-empty when step belongs to a nested flow
    screenshot_path: Optional[str] = None   # viewport shot at the failure site (also evidence.screenshots["viewport"])
    error:           Optional[str] = None
    duration:        float = 0.0      # seconds
    skipped:         bool = False     # True when step was skipped due to a prior section failure
    started_at:      float = 0.0      # epoch seconds; 0.0 = never executed
    ended_at:        float = 0.0      # epoch seconds; 0.0 = never executed
    evidence:        Optional[Evidence] = None   # only on failed (non-skipped) steps
    checks:          list[Check] = field(default_factory=list)   # oracle / skill checks
    group:           bool = False     # marker step whose children follow (run_flow, skills)
    url:             str = ""         # page URL after the step (for generated flows)
    agent:           Optional[dict] = None   # autonomous-run facts: page type, plan, skipped, ai_calls…


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
        return sum(1 for s in self.steps if not s.success and not s.skipped)

    @property
    def skipped(self) -> int:
        return sum(1 for s in self.steps if s.skipped)
