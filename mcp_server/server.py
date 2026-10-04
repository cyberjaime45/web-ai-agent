"""The Web Agent MCP: five tools over the existing Web Agent runtime.

    list_flows        what can be run, and against which environments
    run_flow          start one flow against one environment → execution id
    get_status        where an execution is
    get_result        what it found: totals, failures with evidence, report files
    cancel_execution  stop it

The tools validate and delegate — the catalog reads flows with the Web
Agent's parser, the execution manager runs them with the Web Agent's pytest
entry point, results come from the Web Agent's report. There is no shell,
no file access and no code execution behind any of them.
"""

from __future__ import annotations

import datetime
import logging
import re
import sys
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from mcp.server.fastmcp import FastMCP

from app.browser.profiles import (
    BUILTIN as PROFILES,  # also loads .env, as every entry point does
)
from app.flow.placeholders import is_sensitive
from mcp_server import results
from mcp_server.catalog import Catalog, load_environments
from mcp_server.config import AdapterConfig, ConfigError, load_config
from mcp_server.executions import Execution, ExecutionManager
from mcp_server.models import (
    ErrorCode,
    ErrorInfo,
    ExecutionResult,
    ExecutionState,
    ExecutionStatus,
    FlowCatalog,
    Progress,
)

logger = logging.getLogger("web_agent.mcp")

_INSTRUCTIONS = (
    "The Web Agent MCP: the interface to the Web Agent, which runs Markdown test flows in a real browser. Call list_flows to see the flows "
    "and the environments each may run against, run_flow to start one, get_status until the status "
    "is COMPLETED, FAILED, CANCELLED or TIMED_OUT, then get_result. A COMPLETED execution may still "
    "contain failed tests: read the result. FAILED means the Web Agent itself could not run the flow."
)
_MAX_METADATA = 20
_MAX_INPUTS = 20
_INPUT_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


def _error(code: ErrorCode, message: str, **details) -> ErrorInfo:
    return ErrorInfo(code=code, message=message, details=details)


def _iso(ts: float | None) -> str | None:
    if ts is None:
        return None
    return datetime.datetime.fromtimestamp(ts).astimezone().isoformat(timespec="seconds")


def _metadata(raw: dict[str, str] | None) -> dict[str, str]:
    """Free-form labels from the caller, kept small and as text."""
    return {str(k)[:64]: str(v)[:256] for k, v in list((raw or {}).items())[:_MAX_METADATA]}


def _status(execution: Execution) -> ExecutionStatus:
    progress = None
    if (data := results.read_json(execution.progress_file)) and data.get("total"):
        progress = Progress(completed=int(data.get("completed") or 0), total=int(data["total"]),
                            current=data.get("current"))
    end = execution.finished_at or time.time()
    return ExecutionStatus(
        execution_id=execution.execution_id, status=execution.state, flow=execution.flow_id,
        environment=execution.environment, created_at=_iso(execution.created_at),
        started_at=_iso(execution.started_at), finished_at=_iso(execution.finished_at),
        elapsed_seconds=round(end - execution.started_at, 1) if execution.started_at else None,
        progress=progress, error=execution.error_info(),
    )


def _bad_inputs(inputs: dict[str, str] | None) -> str | None:
    """Why *inputs* cannot be accepted, or None. Secrets never arrive this way:
    they stay in the Web Agent's own configuration."""
    if not inputs:
        return None
    if len(inputs) > _MAX_INPUTS:
        return f"at most {_MAX_INPUTS} inputs"
    for name, value in inputs.items():
        if not _INPUT_NAME_RE.match(name):
            return f"input {name!r}: a name is upper-case letters, digits and underscores"
        if is_sensitive(name):
            return f"input {name!r}: credentials are not accepted as inputs; set them in the Web Agent's .env"
        if not isinstance(value, str) or not value.strip() or len(value) > 2000:
            return f"input {name!r}: the value must be a non-empty string"
    return None


def build_server(config: AdapterConfig) -> FastMCP:
    load_environments(config.environments_file, config.extra_environments_file)   # fail at start if unreadable
    catalog = Catalog(config)
    manager = ExecutionManager(config)

    @asynccontextmanager
    async def lifespan(_: FastMCP) -> AsyncIterator[None]:
        try:
            yield
        finally:
            await manager.shutdown()

    server = FastMCP("web-agent-mcp", instructions=_INSTRUCTIONS, lifespan=lifespan)

    @server.tool()
    async def list_flows(environment: str | None = None) -> FlowCatalog:
        """List the test flows this Web Agent can run and the environments it knows.

        Each flow names the sites it opens and the environments it may run
        against. Pass `environment` to list only the flows runnable there.
        """
        entries, unavailable = catalog.list()
        flows = [e.info for e in entries]
        if environment is not None:
            env = catalog.environment(environment)
            if env is None:
                return FlowCatalog(environments=catalog.environment_infos(), error=_error(
                    ErrorCode.INVALID_REQUEST, f"Unknown environment {environment!r}.",
                    known=[e.name for e in catalog.environment_infos()]))
            flows = [f for f in flows if env.name in f.environments]
        return FlowCatalog(flows=flows, environments=catalog.environment_infos(), unavailable=unavailable)

    @server.tool()
    async def run_flow(flow: str, environment: str, profile: str | None = None,
                       metadata: dict[str, str] | None = None,
                       inputs: dict[str, str] | None = None) -> ExecutionStatus:
        """Start one flow against one environment. Returns at once with an execution id.

        `flow` is a flow id from list_flows; `environment` must be one the flow
        may run against. `profile` is `desktop` or `mobile` (default: the flow's
        own setting). `metadata` is free-form labels kept with the execution,
        for example `requested_by` and `task_id`. `inputs` are values for the
        flow's `<NAME>` placeholders for this run — its `inputs` from list_flows,
        typically the URL of the application in that environment; the
        environment must own the sites they point at. Credentials are never
        accepted as inputs.
        """
        if problem := _bad_inputs(inputs):
            return ExecutionStatus(error=_error(ErrorCode.INVALID_REQUEST, f"Invalid inputs: {problem}."))
        entry = catalog.get(flow, inputs)
        if entry is None:
            return ExecutionStatus(error=_error(
                ErrorCode.INVALID_REQUEST, f"Unknown flow {flow!r}. Use a flow id from list_flows."))
        env = catalog.environment(environment)
        if env is None:
            return ExecutionStatus(flow=entry.info.id, error=_error(
                ErrorCode.INVALID_REQUEST, f"Unknown environment {environment!r}.",
                known=[e.name for e in catalog.environment_infos()]))
        if not catalog.enabled(env):
            return ExecutionStatus(flow=entry.info.id, environment=env.name, error=_error(
                ErrorCode.ENVIRONMENT_NOT_ALLOWED,
                f"Environment {env.name!r} is a production environment and is not enabled on this server."))
        if env.name not in entry.info.environments:
            unset = [n for n in entry.info.inputs if n not in (inputs or {})]
            return ExecutionStatus(flow=entry.info.id, environment=env.name, error=_error(
                ErrorCode.INVALID_REQUEST,
                f"Flow {entry.info.id!r} does not run against {env.name!r}: it opens "
                f"{', '.join(entry.info.hosts) or 'no known site'}"
                + (f" and needs inputs for {', '.join(unset)}" if unset else "") + ".",
                flow_hosts=entry.info.hosts, flow_environments=entry.info.environments,
                flow_inputs=entry.info.inputs))
        if profile is not None and profile not in PROFILES:
            return ExecutionStatus(flow=entry.info.id, environment=env.name, error=_error(
                ErrorCode.INVALID_REQUEST, f"Unknown profile {profile!r}.", known=list(PROFILES)))

        labels = _metadata(metadata)
        try:
            execution = manager.start(
                flow_id=entry.info.id, flow_path=entry.path, environment=env.name,
                hosts=entry.info.hosts, profile=profile,
                label=labels.get("build_name") or f"{entry.info.title} · {env.name}",
                metadata=labels, inputs=inputs)
        except OSError as exc:
            return ExecutionStatus(flow=entry.info.id, environment=env.name, error=_error(
                ErrorCode.EXECUTION_START_FAILED, f"The execution could not be created: {exc}"))
        return _status(execution)

    @server.tool()
    async def get_status(execution_id: str) -> ExecutionStatus:
        """Where an execution is: QUEUED, RUNNING, COMPLETED, FAILED, CANCELLED or TIMED_OUT.

        `progress` counts flows finished out of flows collected, as the test
        runner reports them; it is absent until the run has reported one.
        """
        execution = manager.get(execution_id)
        if execution is None:
            return ExecutionStatus(execution_id=execution_id, error=_error(
                ErrorCode.EXECUTION_NOT_FOUND, f"No execution {execution_id!r}."))
        return _status(execution)

    @server.tool()
    async def get_result(execution_id: str) -> ExecutionResult:
        """The result of a finished execution: test totals, each failure with its
        step, message, likely cause and evidence files, warnings, and the report paths.

        Failed tests are part of a normal result (status COMPLETED). `error` is
        set when the execution itself did not work, or is not finished yet.
        """
        execution = manager.get(execution_id)
        if execution is None:
            return ExecutionResult(execution_id=execution_id, error=_error(
                ErrorCode.EXECUTION_NOT_FOUND, f"No execution {execution_id!r}."))
        base = ExecutionResult(
            execution_id=execution.execution_id, status=execution.state, flow=execution.flow_id,
            environment=execution.environment, hosts=execution.hosts, metadata=execution.metadata)
        if not execution.terminal:
            return base.model_copy(update={"error": _error(
                ErrorCode.RESULT_NOT_AVAILABLE,
                f"Execution {execution.execution_id} is {execution.state.value}; the result is "
                "available once it has finished.")})
        # A stopped or broken run may still have reported what finished before it stopped.
        report = results.build_result(execution.report_dir) or {}
        return base.model_copy(update={**report, "error": execution.error_info()})

    @server.tool()
    async def cancel_execution(execution_id: str) -> ExecutionStatus:
        """Stop a queued or running execution. The browser is closed with it.

        Returns the execution's status: CANCELLED once stopped. Cancelling a
        finished execution changes nothing and returns its final status.
        """
        execution = await manager.cancel(execution_id)
        if execution is None:
            return ExecutionStatus(execution_id=execution_id, error=_error(
                ErrorCode.EXECUTION_NOT_FOUND, f"No execution {execution_id!r}."))
        return _status(execution)

    return server


def main() -> None:
    # stdout is the MCP channel: every log line goes to stderr.
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, force=True,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        server = build_server(load_config())
    except ConfigError as exc:
        print(f"Web Agent MCP cannot start: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    server.run()        # stdio


__all__ = ["ExecutionState", "build_server", "main"]
