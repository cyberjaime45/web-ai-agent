"""Execution manager — one Web Agent run per execution, tracked from start to verdict.

An execution is ``pytest <flow.md>`` in its own process: the same command a
developer or the CI pipeline runs. A process per execution is what the Web
Agent's design asks for — its settings are read once per process and its
browser calls block — and it gives each run a report folder of its own, a
hard timeout and a real cancel.

    QUEUED ─► RUNNING ─► COMPLETED   the run finished and reported (tests may have failed)
                    ├──► FAILED      the run broke: no report, crash, could not start
                    ├──► CANCELLED   cancel_execution
                    └──► TIMED_OUT   stopped after the configured timeout

State is decided from the process and the report it wrote (results.judge),
never from console text. Each execution's record is kept as
``<executions_dir>/<id>/execution.json`` so a finished execution can still be
read after the server restarts.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import signal
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from mcp_server import results
from mcp_server.config import AdapterConfig
from mcp_server.models import TERMINAL_STATES, ErrorCode, ErrorInfo, ExecutionState

logger = logging.getLogger("web_agent.mcp")

_ID_RE = re.compile(r"^web-[0-9a-f]{12}$")


@dataclass
class Execution:
    execution_id: str
    flow_id: str
    flow_path: str                  # relative to the project root: the pytest argument
    environment: str
    hosts: list[str]
    profile: str | None
    label: str                      # the run's BUILD_NAME (report title)
    metadata: dict[str, str]
    directory: str
    inputs: dict[str, str] = field(default_factory=dict)   # <NAME> values for this run (never secrets)
    state: ExecutionState = ExecutionState.QUEUED
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    exit_code: int | None = None
    pid: int | None = None
    cancel_requested: bool = False
    error: dict[str, Any] | None = None

    @property
    def report_dir(self) -> Path:
        return Path(self.directory) / "report"

    @property
    def progress_file(self) -> Path:
        return Path(self.directory) / "progress.json"

    @property
    def console_log(self) -> Path:
        return Path(self.directory) / "console.log"

    @property
    def record_file(self) -> Path:
        return Path(self.directory) / "execution.json"

    @property
    def terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    def error_info(self) -> ErrorInfo | None:
        return ErrorInfo(**self.error) if self.error else None


class ExecutionManager:
    def __init__(self, config: AdapterConfig) -> None:
        self._config = config
        self._executions: dict[str, Execution] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._slots = asyncio.Semaphore(config.max_concurrent)

    # ── Public API ──────────────────────────────────────────────────────────

    def start(self, *, flow_id: str, flow_path: Path | None, environment: str, hosts: list[str],
              profile: str | None, label: str, metadata: dict[str, str],
              inputs: dict[str, str] | None = None, flow_text: str | None = None) -> Execution:
        """Register an execution and schedule its run. Returns at once, QUEUED.
        With *flow_text* instead of *flow_path*, the flow is written into the
        execution's folder (an exploration, which is not a catalog flow)."""
        execution_id = f"web-{uuid.uuid4().hex[:12]}"
        directory = self._config.executions_dir / execution_id
        directory.mkdir(parents=True, exist_ok=False)
        if flow_path is None:
            flow_path = directory / "flow.md"
            flow_path.write_text(flow_text or "", encoding="utf-8")
        execution = Execution(
            execution_id=execution_id, flow_id=flow_id,
            flow_path=flow_path.relative_to(self._config.project_root).as_posix(),
            environment=environment, hosts=hosts, profile=profile, label=label,
            metadata=metadata, directory=str(directory), inputs=dict(inputs or {}),
        )
        self._executions[execution_id] = execution
        self._save(execution)
        self._log(execution, "queued")
        self._tasks[execution_id] = asyncio.create_task(self._run(execution), name=execution_id)
        return execution

    def get(self, execution_id: str) -> Execution | None:
        if execution_id in self._executions:
            return self._executions[execution_id]
        return self._load(execution_id)

    async def cancel(self, execution_id: str) -> Execution | None:
        """Stop a queued or running execution. Returns once it is stopped (or
        after the stop sequence has run its course); a finished one is returned as is."""
        execution = self.get(execution_id)
        if execution is None or execution.terminal:
            return execution
        execution.cancel_requested = True
        self._save(execution)
        self._log(execution, "cancel requested")
        task = self._tasks.get(execution_id)
        process = self._processes.get(execution_id)
        if process is not None:
            await self._stop(process)       # the run task sees the exit and records CANCELLED
        elif task is not None:
            task.cancel()                   # still waiting for a slot
        if task is not None:
            with contextlib.suppress(asyncio.CancelledError, asyncio.TimeoutError):
                await asyncio.wait_for(asyncio.shield(task), timeout=10)
        return execution

    async def shutdown(self) -> None:
        """Server is stopping: no run may outlive it. Killed outright — the
        client gives a closing server very little time, and nobody is left to
        read a partial report."""
        for process in list(self._processes.values()):
            if process.returncode is None:
                with contextlib.suppress(ProcessLookupError, PermissionError):
                    os.killpg(process.pid, signal.SIGKILL)
        tasks = [t for t in self._tasks.values() if not t.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    # ── The run ─────────────────────────────────────────────────────────────

    async def _run(self, execution: Execution) -> None:
        process: asyncio.subprocess.Process | None = None
        try:
            async with self._slots:
                if execution.cancel_requested:
                    self._finish(execution, ExecutionState.CANCELLED, None)
                    return
                try:
                    process = await self._spawn(execution)
                except OSError as exc:
                    self._finish(execution, ExecutionState.FAILED, ErrorInfo(
                        code=ErrorCode.EXECUTION_START_FAILED,
                        message=f"The Web Agent process could not be started: {exc}"))
                    return
                self._processes[execution.execution_id] = process
                execution.state = ExecutionState.RUNNING
                execution.started_at = time.time()
                execution.pid = process.pid
                self._save(execution)
                self._log(execution, "running")

                timed_out = False
                try:
                    await asyncio.wait_for(process.wait(), timeout=self._config.timeout_seconds)
                except TimeoutError:
                    timed_out = True
                    await self._stop(process)
                execution.exit_code = process.returncode
                state, error = results.judge(
                    execution.report_dir, execution.console_log, execution.exit_code,
                    timed_out=timed_out, cancelled=execution.cancel_requested,
                    timeout_seconds=self._config.timeout_seconds)
                self._finish(execution, state, error)
        except asyncio.CancelledError:
            if process is not None and process.returncode is None:
                await asyncio.shield(self._stop(process))
            if execution.cancel_requested:
                self._finish(execution, ExecutionState.CANCELLED, None)
            else:
                self._finish(execution, ExecutionState.FAILED, ErrorInfo(
                    code=ErrorCode.WEB_AGENT_ERROR,
                    message="The Web Agent MCP stopped while the execution was in progress."))
        except Exception as exc:        # the Web Agent MCP's own fault: report it, never hang as RUNNING
            logger.exception("execution_id=%s Web Agent MCP error", execution.execution_id)
            if process is not None and process.returncode is None:
                await self._stop(process)
            self._finish(execution, ExecutionState.FAILED, ErrorInfo(
                code=ErrorCode.WEB_AGENT_ERROR, message=f"The Web Agent MCP failed: {exc}"))
        finally:
            self._processes.pop(execution.execution_id, None)

    async def _spawn(self, execution: Execution) -> asyncio.subprocess.Process:
        command = [self._config.python, "-m", "pytest", execution.flow_path,
                   "-p", "mcp_server.progress_plugin", "-p", "no:cacheprovider"]
        if execution.profile:
            command += ["--profile", execution.profile]
        env = {
            **os.environ,
            **execution.inputs,                 # the run's <NAME> values win over .env
            "ENVIRONMENT": execution.environment,
            "REPORT_DIR": str(execution.report_dir),
            "BUILD_NAME": execution.label,
            "WEB_AGENT_MCP_PROGRESS_FILE": str(execution.progress_file),
            "WEB_AGENT_EXECUTION_ID": execution.execution_id,
            "PYTHONUNBUFFERED": "1",
        }
        if self._config.headless:
            env["HEADLESS"] = "true"
        # The console goes to a file: kept for debugging, never read for results.
        # stdin/stdout must not be inherited — they are the MCP channel.
        with execution.console_log.open("wb") as log:
            return await asyncio.create_subprocess_exec(
                *command, cwd=self._config.project_root, env=env,
                stdin=asyncio.subprocess.DEVNULL, stdout=log, stderr=asyncio.subprocess.STDOUT,
                start_new_session=True,     # its own process group: the browser stops with it
            )

    async def _stop(self, process: asyncio.subprocess.Process) -> None:
        """Interrupt first — the Web Agent then still writes the report of what
        finished — and escalate if the process does not exit."""
        grace = self._config.stop_grace_seconds
        for sig, wait in ((signal.SIGINT, grace), (signal.SIGTERM, 5.0), (signal.SIGKILL, 5.0)):
            if process.returncode is not None:
                return
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(process.pid, sig)
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(process.wait(), timeout=wait)

    # ── Bookkeeping ─────────────────────────────────────────────────────────

    def _finish(self, execution: Execution, state: ExecutionState, error: ErrorInfo | None) -> None:
        if execution.terminal:
            return
        execution.state = state
        execution.finished_at = time.time()
        execution.error = error.model_dump(mode="json") if error else None
        self._save(execution)
        self._log(execution, "finished", exit_code=execution.exit_code,
                  duration=f"{execution.finished_at - (execution.started_at or execution.created_at):.1f}s",
                  **({"error": error.code.value} if error else {}))

    def _save(self, execution: Execution) -> None:
        tmp = execution.record_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(execution), indent=2), encoding="utf-8")
        os.replace(tmp, execution.record_file)

    def _load(self, execution_id: str) -> Execution | None:
        """A record left by an earlier server process. One that never reached a
        final state lost its process with that server."""
        if not _ID_RE.match(execution_id or ""):
            return None
        record = results.read_json(self._config.executions_dir / execution_id / "execution.json")
        if record is None:
            return None
        try:
            execution = Execution(**{**record, "state": ExecutionState(record["state"])})
        except (KeyError, TypeError, ValueError):
            return None
        if not execution.terminal:
            execution.state = ExecutionState.FAILED
            execution.error = ErrorInfo(
                code=ErrorCode.WEB_AGENT_ERROR,
                message="The execution was lost: the Web Agent MCP process that started it has stopped.",
            ).model_dump(mode="json")
        return execution

    def _log(self, execution: Execution, event: str, **extra: Any) -> None:
        fields = {
            "execution_id": execution.execution_id, "flow": execution.flow_id,
            "environment": execution.environment, "status": execution.state.value,
            "requested_by": execution.metadata.get("requested_by"),
            "task_id": execution.metadata.get("task_id"), **extra,
        }
        logger.info("%s %s", event, " ".join(f"{k}={v}" for k, v in fields.items() if v is not None))
