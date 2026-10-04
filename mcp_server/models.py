"""The MCP contract — what each tool returns.

Every response carries ``error``: ``null`` when the call did what was asked,
otherwise a code and a message. A flow whose tests failed is *not* an error —
it is a COMPLETED execution whose result lists the failures. MCP protocol
errors are left for transport problems only.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class ExecutionState(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"      # the Web Agent ran the flow; tests may have passed or failed
    FAILED = "FAILED"            # the Web Agent could not run it (crash, bad setup, no report)
    CANCELLED = "CANCELLED"
    TIMED_OUT = "TIMED_OUT"


TERMINAL_STATES = frozenset({
    ExecutionState.COMPLETED, ExecutionState.FAILED,
    ExecutionState.CANCELLED, ExecutionState.TIMED_OUT,
})


class ErrorCode(StrEnum):
    INVALID_REQUEST = "INVALID_REQUEST"
    ENVIRONMENT_NOT_ALLOWED = "ENVIRONMENT_NOT_ALLOWED"
    EXECUTION_NOT_FOUND = "EXECUTION_NOT_FOUND"
    EXECUTION_START_FAILED = "EXECUTION_START_FAILED"
    EXECUTION_TIMEOUT = "EXECUTION_TIMEOUT"
    RESULT_NOT_AVAILABLE = "RESULT_NOT_AVAILABLE"
    WEB_AGENT_ERROR = "WEB_AGENT_ERROR"


class ErrorInfo(BaseModel):
    code: ErrorCode
    message: str
    details: dict[str, Any] = Field(default_factory=dict)   # for debugging: exit code, log path, log tail


# ── list_flows ───────────────────────────────────────────────────────────────

class EnvironmentInfo(BaseModel):
    name: str
    description: str = ""
    hosts: list[str] = Field(default_factory=list)
    production: bool = False
    enabled: bool = True          # false: known, but this server will not run against it


class FlowInfo(BaseModel):
    id: str                       # what run_flow takes: the path under the flows folder
    title: str
    tests: list[str] = Field(default_factory=list)       # one test case per ## section
    markers: list[str] = Field(default_factory=list)
    expected: list[str] = Field(default_factory=list)    # the flow's "## Expected Outcome" lines
    hosts: list[str] = Field(default_factory=list)       # every site the flow opens
    environments: list[str] = Field(default_factory=list)  # environments it may run against
    inputs: list[str] = Field(default_factory=list)      # <PLACEHOLDER> names its sites come from (run_flow inputs)
    profiles: list[str] = Field(default_factory=list)    # the flow's own device profiles, if it names any
    steps: int = 0


class FlowDocument(BaseModel):
    """A flow's content and what the catalog knows about it (get_flow)."""
    info: FlowInfo | None = None
    content: str = ""
    path: str = ""
    error: ErrorInfo | None = None


class LintFinding(BaseModel):
    line: int
    rule: str
    message: str
    blocking: bool = False      # a flow with a blocking finding is not saved


class ValidationResult(BaseModel):
    """validate_flow / save_flow: parse and lint outcome, plus the flow as it
    would be listed. ``saved`` is the id when save_flow wrote it."""
    valid: bool = False
    findings: list[LintFinding] = Field(default_factory=list)
    info: FlowInfo | None = None
    saved: str | None = None
    path: str | None = None
    error: ErrorInfo | None = None


class ActionSpec(BaseModel):
    keyword: str
    group: str = ""
    min_args: int = 0
    max_args: int = 0
    description: str = ""


class SkillSpec(BaseModel):
    keyword: str
    description: str = ""
    options: dict[str, str] = Field(default_factory=dict)    # option → meaning (with its default)


class Capabilities(BaseModel):
    """describe_capabilities: what flows may contain, from the Web Agent's own
    registries and documentation — never a copy kept elsewhere."""
    web_agent_version: str = ""
    contract: str = "execution/1"
    actions: list[ActionSpec] = Field(default_factory=list)
    skills: list[SkillSpec] = Field(default_factory=list)
    flow_format: dict[str, Any] = Field(default_factory=dict)
    configured_placeholders: list[str] = Field(default_factory=list)   # <NAME>s the environment can fill (names only)
    tools: list[str] = Field(default_factory=list)
    error: ErrorInfo | None = None


class UnavailableFlow(BaseModel):
    id: str
    reason: str


class FlowCatalog(BaseModel):
    flows: list[FlowInfo] = Field(default_factory=list)
    environments: list[EnvironmentInfo] = Field(default_factory=list)
    unavailable: list[UnavailableFlow] = Field(default_factory=list)
    error: ErrorInfo | None = None


# ── run_flow / get_status / cancel_execution ─────────────────────────────────

class Progress(BaseModel):
    """Counted by pytest itself: flows finished out of flows collected."""
    unit: Literal["flows"] = "flows"
    completed: int
    total: int
    current: str | None = None


class ExecutionStatus(BaseModel):
    execution_id: str | None = None
    status: ExecutionState | None = None
    flow: str | None = None
    environment: str | None = None
    created_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    elapsed_seconds: float | None = None
    progress: Progress | None = None     # absent until the Web Agent has reported one
    error: ErrorInfo | None = None


# ── get_result ───────────────────────────────────────────────────────────────

class Totals(BaseModel):
    """Test cases, as the Web Agent's summary.json counts them."""
    total: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    errors: int = 0
    warnings: int = 0
    unverified: int = 0
    pass_rate: float = 0.0
    duration_ms: float = 0.0


class CaseOutcome(BaseModel):
    name: str
    file: str = ""
    status: str
    profile: str = ""
    duration_ms: float = 0.0
    retried: bool = False


class FailureEvidence(BaseModel):
    url: str = ""
    title: str = ""
    screenshots: list[str] = Field(default_factory=list)   # absolute paths
    trace: str | None = None
    layers: dict[str, str] = Field(default_factory=dict)   # what L1 / L2 / L3 each did


class Failure(BaseModel):
    test: str
    file: str = ""
    # test_failure: a step ran and failed. execution_error: the test broke
    # without a failed step (crash, setup or teardown error).
    kind: Literal["test_failure", "execution_error"]
    step: str | None = None
    message: str = ""
    likely_cause: dict[str, Any] | None = None    # the Web Agent's diagnosis: verdict, summary
    evidence: FailureEvidence | None = None


class Finding(BaseModel):
    test: str
    check: str
    detail: str = ""
    severity: str = ""


class ReportFiles(BaseModel):
    html: str | None = None
    summary_json: str | None = None
    test_cases_json: str | None = None
    junit: str | None = None


class GeneratedFlow(BaseModel):
    path: str
    content: str = ""


class Exploration(BaseModel):
    """What an explore_page execution learned: the page as inspect_page saw it,
    the assertions test_page suggests, and the draft flow it generated."""
    url: str = ""
    title: str = ""
    page_type: str = ""
    observation: dict[str, Any] = Field(default_factory=dict)
    components: list[str] = Field(default_factory=list)
    assertions: list[str] = Field(default_factory=list)       # step lines test_page would assert
    actions: list[str] = Field(default_factory=list)          # leaf steps the agent ran
    generated_flow: GeneratedFlow | None = None


class ExecutionResult(BaseModel):
    execution_id: str | None = None
    status: ExecutionState | None = None
    flow: str | None = None
    environment: str | None = None
    hosts: list[str] = Field(default_factory=list)
    verdict: str | None = None          # the Web Agent's own run status (passed, failed, …)
    exploration: Exploration | None = None   # present for explore_page executions
    summary: Totals | None = None
    tests: list[CaseOutcome] = Field(default_factory=list)
    failures: list[Failure] = Field(default_factory=list)
    warnings: list[Finding] = Field(default_factory=list)
    healed_steps: int = 0               # steps the exact locator missed and a fallback resolved
    report: ReportFiles | None = None
    run: dict[str, Any] = Field(default_factory=dict)       # run id, browser, versions, timings
    metadata: dict[str, str] = Field(default_factory=dict)
    error: ErrorInfo | None = None
