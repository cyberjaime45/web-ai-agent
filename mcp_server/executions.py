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

A run is a process group of its own, so that what it starts stops with it (the
browser goes when the driver the run started for it does); for the same reason
it outlives a server that is killed rather than stopped. The
next server to start stops such runs (``ExecutionManager.recover``). Who is
still alive is told by file locks, which the operating system drops when a
process ends, however it ends — never by a process number, which is used
again, or by a clock:

    <executions_dir>/.servers/<id>.lock   held by a server for as long as it runs; its runs' records name it
    <executions_dir>/<id>/run.lock        held by the run's own process (handed to it when it is started)

A run is stopped only while its lock is held (its process is then the very
one the record names) and its server's is seen free; the runs of a server
still working on the same folder, of a server that could hold no lock, and
records written on another machine are never touched. Where that cannot be
told, a record is only ever read as lost, and only once its run is long past
the time any run is allowed.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import signal
import socket
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

try:                                    # advisory file locks: POSIX (the platforms the Web Agent MCP runs on)
    import fcntl
except ImportError:                     # pragma: no cover — elsewhere nothing is recovered, as before
    fcntl = None                        # type: ignore[assignment]

from mcp_server import results
from mcp_server.config import AdapterConfig, llm_off
from mcp_server.models import TERMINAL_STATES, ErrorCode, ErrorInfo, ExecutionState

logger = logging.getLogger("web_agent.mcp")

_ID_RE = re.compile(r"^web-[0-9a-f]{12}$")
_SERVER_RE = re.compile(r"^[0-9a-f]{16}$")
SERVERS = ".servers"            # under the executions folder: one lock file per running server
_REAP_GRACE = 10.0              # seconds an orphaned run gets to write its report before it is killed
LOST = "The execution was lost: the Web Agent MCP process that started it has stopped."


def lock_free(path: Path, *, missing: bool | None = True) -> bool | None:
    """Whether nobody holds the lock on *path*: True (its holder is gone), False (held: its holder is running),
    None when that cannot be told (no file locks here, the file cannot be opened). A file that is not there is
    *missing*: free for a run's lock (a run that never had one holds none), not to be told for a server's (a
    living server keeps its lock on a file somebody tidied away). Only a True is ever acted on. Asked with a
    shared lock, so that two servers asking at once do not take each other for the holder."""
    if fcntl is None:
        return None
    try:
        with open(path, "rb") as probe:
            try:
                fcntl.flock(probe, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError:
                return False
            return True                                 # released again as the file closes
    except FileNotFoundError:
        return missing
    except OSError:
        return None


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
    withheld: list[str] = field(default_factory=list)      # names this run fills from nowhere of the agent's own
    traced: bool = True                                    # False: the run was handed secrets, so no trace is kept
    state: ExecutionState = ExecutionState.QUEUED
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    exit_code: int | None = None
    pid: int | None = None
    server: str | None = None           # the Web Agent MCP process that started it (its lock: ``SERVERS``/<id>.lock)
    host: str | None = None             # the machine it runs on: locks and process numbers mean nothing elsewhere
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
    def run_lock(self) -> Path:
        return Path(self.directory) / "run.lock"

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
        self._secrets: dict[str, dict[str, str]] = {}      # per execution, in memory only: never saved or logged
        self._host = socket.gethostname()
        self._server_id = uuid.uuid4().hex[:16]
        self._presence = self._present()                   # this server's lock, held until the process ends

    def _present(self) -> Any:
        """This server's lock file, made and locked: what tells another server that this one is running. None
        when it cannot be held (no file locks, a folder that cannot be written): this server's runs then name no
        server, and one that is killed is not cleaned up after, as before there were locks."""
        if fcntl is None:
            return None
        try:
            folder = self._config.executions_dir / SERVERS
            folder.mkdir(parents=True, exist_ok=True)
            held = open(folder / f"{self._server_id}.lock", "ab")      # noqa: SIM115 — held for the process's life
            for attempt in range(20):                   # another server asking who is alive holds it for an instant
                try:
                    fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    return held
                except BlockingIOError:
                    if attempt == 19:
                        raise
                    time.sleep(0.01)
            return held
        except OSError:
            logger.warning("no server lock in %s: runs left by this server, if it is killed, are not stopped by "
                           "the next one", self._config.executions_dir)
            return None

    # ── Public API ──────────────────────────────────────────────────────────

    def start(self, *, flow_id: str, flow_path: Path | None, environment: str, hosts: list[str],
              profile: str | None, label: str, metadata: dict[str, str],
              inputs: dict[str, str] | None = None, flow_text: str | None = None,
              secrets: dict[str, str] | None = None, withheld: list[str] | None = None) -> Execution:
        """Register an execution and schedule its run. Returns at once, QUEUED.
        With *flow_text* instead of *flow_path*, the flow is written into the
        execution's folder (an exploration, which is not a catalog flow).
        *secrets* reach the run as environment variables and nothing else; a run that is handed any keeps no
        Playwright trace (a trace records what is typed and sent). *withheld* names the placeholders this run
        must not fill from the agent's own environment or ``.env``: without a value among *inputs* or
        *secrets*, a step that uses one fails and says so."""
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
            withheld=sorted(set(withheld or []) - set(inputs or {}) - set(secrets or {})), traced=not secrets,
            server=self._server_id if self._presence is not None else None, host=self._host,
        )
        self._executions[execution_id] = execution
        if secrets:
            self._secrets[execution_id] = dict(secrets)
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
        if execution_id not in self._executions:
            # another server's run, still going: its record is that server's to write, and its process that
            # server's to stop. Returned as it stands, so the caller sees it was not cancelled here
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
        if self._presence is not None:      # the file stays: a lock that is free says "gone", a missing file nothing
            with contextlib.suppress(OSError):
                self._presence.close()
            self._presence = None

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
                    timeout_seconds=self._config.timeout_seconds, secret_run=not execution.traced,
                    project_root=self._config.project_root)
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
            self._secrets.pop(execution.execution_id, None)

    async def _spawn(self, execution: Execution) -> asyncio.subprocess.Process:
        command = [self._config.python, "-m", "pytest", execution.flow_path,
                   "-p", "mcp_server.progress_plugin", "-p", "no:cacheprovider"]
        if execution.profile:
            command += ["--profile", execution.profile]
        env = {
            **os.environ,
            # a name set to nothing here is not filled from .env either (a variable that is set is never loaded
            # over), and an empty placeholder fails its step: what the orchestrator withholds stays withheld
            **dict.fromkeys(execution.withheld, ""),
            "WEB_AGENT_WITHHELD": ",".join(execution.withheld),
            **execution.inputs,                 # the run's <NAME> values win over .env
            **(secrets := self._secrets.pop(execution.execution_id, {})),   # handed over once, kept nowhere
            # their names (never a value): the report masks each as it does a password, whatever it is called
            "WEB_AGENT_SECRET_NAMES": ",".join(sorted(secrets)),
            "ENVIRONMENT": execution.environment,
            "REPORT_DIR": str(execution.report_dir),
            "BUILD_NAME": execution.label,
            "WEB_AGENT_MCP_PROGRESS_FILE": str(execution.progress_file),
            "WEB_AGENT_EXECUTION_ID": execution.execution_id,
            "PYTHONUNBUFFERED": "1",
        }
        if not execution.traced:
            env["TRACE"] = "off"                # a trace keeps every value typed and every request sent
        if self._config.headless:
            env["HEADLESS"] = "true"
        if llm_off():
            env["AI_PROVIDER"], env["LLM_KEY"] = "", ""       # the orchestrator runs without an LLM: so does the run
        # The console goes to a file: kept for debugging, never read for results.
        # stdin/stdout must not be inherited — they are the MCP channel.
        # The run's lock is taken here and handed to the run, which holds it for as long as it lives (this
        # server's own handle is closed again): while it is held, the process the record names is still that process.
        held = self._run_lock(execution)
        try:
            with execution.console_log.open("wb") as log:
                return await asyncio.create_subprocess_exec(
                    *command, cwd=self._config.project_root, env=env,
                    stdin=asyncio.subprocess.DEVNULL, stdout=log, stderr=asyncio.subprocess.STDOUT,
                    start_new_session=True,     # its own process group: the browser stops with it
                    pass_fds=(held.fileno(),) if held is not None else (),
                )
        finally:
            if held is not None:
                held.close()

    @staticmethod
    def _run_lock(execution: Execution) -> Any:
        if fcntl is None:
            return None
        try:
            held = open(execution.run_lock, "ab")       # noqa: SIM115 — closed by the caller once the run has it
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return held
        except OSError:
            return None                                 # a run nobody can later tell is alive: never stopped by a stranger

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
        tmp = execution.record_file.with_suffix(f".{os.getpid()}.tmp")     # never another server's half-written file
        tmp.write_text(json.dumps(asdict(execution), indent=2), encoding="utf-8")
        os.replace(tmp, execution.record_file)

    def _load(self, execution_id: str) -> Execution | None:
        """A record another server process wrote. One that never reached a final state is lost with its server
        (``recover`` stops what is left of it); while that server is still running beside this one, or may be
        (another machine's, or it cannot be told), the record is its own to finish and is returned as it stands."""
        if not _ID_RE.match(execution_id or ""):
            return None
        execution = self._read(self._config.executions_dir / execution_id)
        if execution is not None and not execution.terminal and (self._server_gone(execution)
                                                                 or self._overdue(execution)):
            execution.state = ExecutionState.FAILED
            execution.error = ErrorInfo(code=ErrorCode.WEB_AGENT_ERROR, message=LOST).model_dump(mode="json")
        return execution

    def _overdue(self, execution: Execution) -> bool:
        """Whether a run whose server cannot be told alive or gone (another machine's record, a machine that
        changed its name, a lock that cannot be read) is past the time any run is allowed, and some: it is then
        read as lost — never signalled, never written — so that nobody waits on it for good."""
        since = execution.started_at or execution.created_at
        allowed = self._config.timeout_seconds + self._config.stop_grace_seconds + 60
        return isinstance(since, int | float) and time.time() - since > allowed

    @staticmethod
    def _read(folder: Path) -> Execution | None:
        """The record in *folder*, or None when there is none or it is not one (a file is the folder's owner's to
        write: every field that is acted on is checked for what it must be)."""
        record = results.read_json(folder / "execution.json")
        try:
            # a record that does not say, as a plain true, that the run was handed no secrets is taken as one that
            # was (a Web Agent before 1.5.2 wrote no such field): its console output is never given out
            execution = Execution(**{**record, "state": ExecutionState(record["state"]),
                                     "traced": record.get("traced") is True})
        except (KeyError, TypeError, ValueError):
            return None
        pid, plain = execution.pid, lambda v: v is None or isinstance(v, str)       # noqa: E731
        if not isinstance(execution.directory, str) or not (pid is None or type(pid) is int) \
                or not plain(execution.server) or not plain(execution.host) \
                or not isinstance(execution.metadata, dict):
            return None
        return execution

    def _server_gone(self, execution: Execution) -> bool:
        """Whether the server that started *execution* has stopped, for certain: it ran on this machine and its
        lock is seen free. A record that names no server was written before records did, or by a server that
        could hold no lock and may well be running: it is gone only when the run holds no lock either (a run
        from before runs held one has no lock file). Anything that cannot be told counts as still running."""
        if execution.host is not None and execution.host != self._host:
            return False
        if execution.server is None:
            return lock_free(execution.run_lock) is True
        if execution.server == self._server_id or not _SERVER_RE.match(execution.server):
            return False
        return lock_free(self._config.executions_dir / SERVERS / f"{execution.server}.lock", missing=None) is True

    # ── Runs a stopped server left behind ───────────────────────────────────

    async def recover(self) -> list[str]:
        """At start: the runs an earlier server left unfinished when it was killed. A run still going (its lock
        is held) is interrupted, so that it writes the report of what it finished, then killed with everything
        in its process group; one that ended by itself is judged by the report it left. Each record is closed on
        disk, so it is not found again. Returns the ids closed; what goes wrong with one is logged and does not
        keep the others from being closed."""
        closed: list[str] = []
        for execution in await asyncio.to_thread(self._orphans):
            claim = self._claim(execution)
            if claim is None:           # another server, started beside this one, is closing it
                continue
            try:
                # read again now that it is this server's to close: another may have closed it since the scan
                execution = self._read(Path(execution.directory)) or execution
                if execution.terminal or not self._server_gone(execution):
                    continue
                if await self._reap(execution):
                    closed.append(execution.execution_id)
            except Exception:           # noqa: BLE001 — one record's trouble is its own
                logger.exception("execution_id=%s orphan not closed", execution.execution_id)
            finally:
                claim.close()
        return closed

    @staticmethod
    def _claim(execution: Execution) -> Any:
        """The right to close this orphan, held while it is done: two servers starting together must not both
        interrupt it (the second interrupt would cut off the report the first asked for)."""
        if fcntl is None:
            return None
        try:
            held = open(Path(execution.directory) / "reap.lock", "ab")     # noqa: SIM115 — closed by the caller
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return held
        except OSError:
            return None

    def _orphans(self) -> list[Execution]:
        found: list[Execution] = []
        try:
            folders = sorted(p for p in self._config.executions_dir.iterdir() if _ID_RE.match(p.name))
        except OSError:
            return found
        for folder in folders:
            if folder.name in self._executions:
                continue
            execution = self._read(folder)
            if execution is not None and not execution.terminal and execution.execution_id == folder.name \
                    and Path(execution.directory) == folder and self._server_gone(execution):
                found.append(execution)
        return found

    def _stoppable(self, execution: Execution) -> bool:
        """Whether the run's process may be signalled: its lock is held (so the process the record names is
        alive and is still that process), and the number is a process group of its own that is not this
        server's, its parent's or the system's."""
        pid = execution.pid
        if pid is None or not 1 < pid < 2 ** 31 or pid in (os.getpid(), os.getppid(), os.getpgid(0)):
            return False
        if execution.server is None or lock_free(execution.run_lock) is not False:
            return False                    # a server that held no lock may be running: its run is never a stranger's
        try:
            return os.getpgid(pid) == pid
        except (OSError, OverflowError):
            return False

    async def _reap(self, execution: Execution) -> bool:
        """Stop what is left of the run and close its record; False when it is still going and could not be
        stopped (its record is then left as it is, to be tried again at the next start)."""
        pid, stopped = execution.pid, False
        going = self._stoppable(execution)
        if going:
            for sig, wait in ((signal.SIGINT, min(self._config.stop_grace_seconds, _REAP_GRACE)), (signal.SIGKILL, 5.0)):
                with contextlib.suppress(ProcessLookupError, PermissionError):
                    os.killpg(pid, sig)
                deadline = time.monotonic() + wait
                while not stopped and time.monotonic() < deadline:
                    stopped = lock_free(execution.run_lock) is True        # only a lock seen free is a run that ended
                    if not stopped:
                        await asyncio.sleep(0.2)
                if stopped:
                    break
            if stopped:
                # what its process started in its group and left behind, having ignored the interrupt: the
                # group's number is not given to anything else while a member of it remains
                with contextlib.suppress(ProcessLookupError, PermissionError):
                    os.killpg(pid, signal.SIGKILL)
            else:
                self._log(execution, "orphan not stopped", pid=pid)
                return False
        state, error = ExecutionState.FAILED, ErrorInfo(code=ErrorCode.WEB_AGENT_ERROR, message=LOST + (
            " Its run was still going and has been stopped." if stopped else ""))
        if not going and lock_free(execution.run_lock) is True and execution.started_at is not None:
            # it ended by itself after its server was gone: what it reported stands
            judged, problem = results.judge(execution.report_dir, execution.console_log, None, timed_out=False,
                                            cancelled=False, timeout_seconds=self._config.timeout_seconds,
                                            secret_run=not execution.traced,
                                            project_root=self._config.project_root)
            if judged is ExecutionState.COMPLETED:
                state, error = judged, problem
        execution.state, execution.finished_at = state, time.time()
        execution.error = error.model_dump(mode="json") if error else None
        self._save(execution)
        self._log(execution, "orphan closed", pid=pid, stopped=stopped or None)
        return True

    def _log(self, execution: Execution, event: str, **extra: Any) -> None:
        fields = {
            "execution_id": execution.execution_id, "flow": execution.flow_id,
            "environment": execution.environment, "status": execution.state.value,
            "requested_by": execution.metadata.get("requested_by"),
            "task_id": execution.metadata.get("task_id"), **extra,
        }
        logger.info("%s %s", event, " ".join(f"{k}={v}" for k, v in fields.items() if v is not None))
