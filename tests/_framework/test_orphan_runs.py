"""A run outlives a Web Agent MCP server that is killed (it is a process group of its own): the next server to
start stops it and closes its record. Who is alive is told by file locks, never by a process number: a process
that only has a run's number is not touched, nor is the run of a server still working on the same folder."""

from __future__ import annotations

import asyncio
import fcntl
import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from mcp_server.executions import SERVERS, ExecutionManager, lock_free
from mcp_server.models import ExecutionState
from tests._framework.test_mcp_adapter import _config

READY = "print('ready', flush=True)\n"
SLEEPER = READY + "import time\ntime.sleep(120)\n"
# a run that, interrupted, writes what it finished before it goes: what an interrupted pytest does with its report
POLITE = ("import signal, sys, time, pathlib\n"
          "def leave(*_):\n    pathlib.Path(sys.argv[1]).write_text('written')\n    sys.exit(0)\n"
          "signal.signal(signal.SIGINT, leave)\n" + READY + "time.sleep(120)\n")
STUBBORN = "import signal, time\nsignal.signal(signal.SIGINT, signal.SIG_IGN)\n" + READY + "time.sleep(120)\n"
# a run whose own process goes at once when interrupted and leaves a child that does not: a browser left behind
LEAVES_A_CHILD = ("import os, signal, subprocess, sys, time\n"
                  "child = subprocess.Popen([sys.executable, '-c', 'import signal, time\\n"
                  "signal.signal(signal.SIGINT, signal.SIG_IGN)\\nprint(\"up\", flush=True)\\ntime.sleep(120)'],"
                  " stdout=subprocess.PIPE)\n"
                  "child.stdout.readline()\nprint(child.pid, flush=True)\n" + READY + "time.sleep(120)\n")
HOLDS = "import fcntl, sys, time\nheld = open(sys.argv[1], 'ab')\nfcntl.flock(held, fcntl.LOCK_EX)\n" + READY + \
        "time.sleep(120)\n"
DEAD = "0" * 16
started: list[subprocess.Popen] = []


@pytest.fixture(autouse=True)
def nothing_left_running():
    yield
    for process in started:
        if process.poll() is None:
            process.kill()
        process.wait()
    started.clear()


def _ready(process: subprocess.Popen, lines: int = 1) -> list[str]:
    """What the process said once it was set up: a test never guesses with a sleep."""
    return [process.stdout.readline().strip() for _ in range(lines)]


def _run(folder: Path, script: str, *arguments: str, lines: int = 1) -> tuple[subprocess.Popen, list[str]]:
    """A run as the server starts one — a process group of its own, holding its folder's run.lock — whose
    server is gone: nobody waits for it."""
    folder.mkdir(parents=True, exist_ok=True)
    with open(folder / "run.lock", "ab") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        process = subprocess.Popen([sys.executable, "-c", script, *arguments], start_new_session=True, text=True,
                                   stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                   pass_fds=(held.fileno(),))
    started.append(process)
    return process, _ready(process, lines)


def _record(root: Path, execution_id: str, **fields) -> Path:
    folder = root / "executions" / execution_id
    folder.mkdir(parents=True, exist_ok=True)
    record = {"execution_id": execution_id, "flow_id": "app/login.md", "flow_path": "flows/app/login.md",
              "environment": "staging", "hosts": [], "profile": None, "label": "x", "metadata": {},
              "directory": str(folder), "state": "RUNNING", "started_at": time.time(),
              "server": DEAD, "host": socket.gethostname(), **fields}
    (folder / "execution.json").write_text(json.dumps(record))
    servers = root / "executions" / SERVERS
    servers.mkdir(parents=True, exist_ok=True)
    (servers / f"{DEAD}.lock").touch()              # a server that was killed: its lock file is there, held by nobody
    return folder / "execution.json"


def _gone(process: subprocess.Popen, within: float = 10.0) -> bool:
    try:
        process.wait(timeout=within)
    except subprocess.TimeoutExpired:
        return False
    return True


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _recover(root: Path) -> tuple[ExecutionManager, list[str]]:
    manager = ExecutionManager(_config(root))
    return manager, asyncio.run(manager.recover())


def test_a_run_whose_server_was_killed_is_stopped_and_closed_at_the_next_start(tmp_path: Path):
    folder = tmp_path / "executions" / "web-000000000001"
    run, _ = _run(folder, POLITE, str(tmp_path / "report.txt"))
    saved = _record(tmp_path, folder.name, pid=run.pid)
    manager, closed = _recover(tmp_path)
    assert closed == [folder.name]
    assert _gone(run) and (tmp_path / "report.txt").read_text() == "written"     # interrupted, not just killed
    kept = json.loads(saved.read_text())
    assert kept["state"] == "FAILED" and kept["finished_at"] and "has been stopped" in kept["error"]["message"]
    assert asyncio.run(manager.recover()) == []                                  # closed on disk: found once
    assert manager.get(folder.name).state is ExecutionState.FAILED


def test_a_run_that_ignores_the_interrupt_is_killed(tmp_path: Path):
    folder = tmp_path / "executions" / "web-000000000002"
    stubborn, _ = _run(folder, STUBBORN)
    saved = _record(tmp_path, folder.name, pid=stubborn.pid)
    _recover(tmp_path)
    assert _gone(stubborn) and stubborn.returncode == -signal.SIGKILL
    assert "has been stopped" in json.loads(saved.read_text())["error"]["message"]


def test_what_the_run_started_goes_with_it_though_its_own_process_left_first(tmp_path: Path):
    """The browser a run started is in its process group: it is not left behind with what it was handed."""
    folder = tmp_path / "executions" / "web-000000000003"
    run, (child, _) = _run(folder, LEAVES_A_CHILD, lines=2)
    _record(tmp_path, folder.name, pid=run.pid)
    _recover(tmp_path)
    assert _gone(run)
    deadline = time.monotonic() + 5
    while _alive(int(child)) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not _alive(int(child))


def test_a_process_that_only_has_the_runs_number_is_never_touched(tmp_path: Path):
    """The run ended with its server (nobody holds its lock) and its number went to something else: the record
    is closed, and nothing is signalled. Likewise a record from before runs held a lock."""
    stranger = subprocess.Popen([sys.executable, "-c", SLEEPER], start_new_session=True, stdout=subprocess.PIPE,
                                text=True)
    started.append(stranger)
    _ready(stranger)
    (tmp_path / "executions" / "web-000000000004").mkdir(parents=True)
    (tmp_path / "executions" / "web-000000000004" / "run.lock").touch()         # its run is gone: free
    records = [_record(tmp_path, "web-000000000004", pid=stranger.pid),
               _record(tmp_path, "web-000000000005", pid=stranger.pid, server=None, host=None)]   # an older record
    _, closed = _recover(tmp_path)
    assert sorted(closed) == ["web-000000000004", "web-000000000005"] and stranger.poll() is None
    for record in records:
        kept = json.loads(record.read_text())
        assert kept["state"] == "FAILED" and kept["error"]["message"].endswith("has stopped.")


@pytest.mark.parametrize("pid", [0, 1, -5, None, "12", True, 2 ** 40, os.getpid(), os.getppid()])
def test_a_record_cannot_point_the_server_at_a_process_that_is_no_run(tmp_path: Path, monkeypatch, pid):
    """A record is a file: one naming the system's first process, this server, or no number at all stops nothing."""
    signalled: list[tuple] = []
    monkeypatch.setattr(os, "killpg", lambda *call: signalled.append(call))
    folder = tmp_path / "executions" / "web-000000000006"
    _run(folder, SLEEPER)                                                       # its lock is held, all the same
    _record(tmp_path, folder.name, pid=pid)
    _recover(tmp_path)
    assert signalled == []


def test_the_run_of_a_server_still_working_beside_this_one_is_its_own(tmp_path: Path):
    """Two servers on one folder (a terminal JANUS beside the service): neither closes the other's runs."""
    servers = tmp_path / "executions" / SERVERS
    servers.mkdir(parents=True)
    other = subprocess.Popen([sys.executable, "-c", HOLDS, str(servers / ("a" * 16 + ".lock"))],
                             stdout=subprocess.PIPE, text=True)
    started.append(other)
    _ready(other)
    folder = tmp_path / "executions" / "web-000000000007"
    run, _ = _run(folder, SLEEPER)
    saved = _record(tmp_path, folder.name, pid=run.pid, server="a" * 16)
    manager, closed = _recover(tmp_path)
    assert closed == [] and run.poll() is None and json.loads(saved.read_text())["state"] == "RUNNING"
    assert manager.get(folder.name).state is ExecutionState.RUNNING              # read as it stands
    other.kill()
    other.wait()                                                                 # that server is killed …
    assert asyncio.run(manager.recover()) == [folder.name] and _gone(run)        # … and its run is an orphan


def test_a_record_from_another_machine_is_never_judged_here_only_read_as_lost_once_long_overdue(tmp_path: Path):
    """A folder shared between machines (or a machine that changed its name): their locks and process numbers
    mean nothing on this one. Nothing is signalled or written; a run far past the time any run is allowed is
    read as lost, so that nobody waits on it for good."""
    folder = tmp_path / "executions" / "web-000000000008"
    run, _ = _run(folder, SLEEPER)
    saved = _record(tmp_path, folder.name, pid=run.pid, host="another-machine")
    manager, closed = _recover(tmp_path)
    assert closed == [] and run.poll() is None and json.loads(saved.read_text())["state"] == "RUNNING"
    assert manager.get(folder.name).state is ExecutionState.RUNNING
    old = _record(tmp_path, "web-000000000018", pid=run.pid, host="another-machine", started_at=time.time() - 3600)
    before = old.read_text()
    assert manager.get("web-000000000018").state is ExecutionState.FAILED        # the limit here is 60 s
    assert asyncio.run(manager.recover()) == [] and old.read_text() == before and run.poll() is None


def test_a_server_whose_lock_file_was_tidied_away_keeps_its_runs(tmp_path: Path):
    """A living server holds its lock on a file somebody removed with the folder: a missing file says nothing."""
    folder = tmp_path / "executions" / "web-000000000050"
    run, _ = _run(folder, SLEEPER)
    saved = _record(tmp_path, folder.name, pid=run.pid, server="b" * 16)         # no such lock file
    _, closed = _recover(tmp_path)
    assert closed == [] and run.poll() is None and json.loads(saved.read_text())["state"] == "RUNNING"


def test_the_run_of_a_server_that_could_hold_no_lock_is_never_a_strangers_to_stop(tmp_path: Path):
    """Such a record names no server, as one from before records did: while its run holds a lock it is alive,
    and its server may be too."""
    folder = tmp_path / "executions" / "web-000000000051"
    run, _ = _run(folder, SLEEPER)
    saved = _record(tmp_path, folder.name, pid=run.pid, server=None)
    _, closed = _recover(tmp_path)
    assert closed == [] and run.poll() is None and json.loads(saved.read_text())["state"] == "RUNNING"


def test_a_run_that_could_not_be_stopped_is_left_to_be_tried_again(tmp_path: Path, monkeypatch):
    folder = tmp_path / "executions" / "web-000000000052"
    run, _ = _run(folder, SLEEPER)
    saved = _record(tmp_path, folder.name, pid=run.pid)
    monkeypatch.setattr(os, "killpg", lambda *call: None)                        # as when it is not ours to signal
    manager = ExecutionManager(_config(tmp_path, stop_grace_seconds=0.3))
    monkeypatch.setattr("mcp_server.executions._REAP_GRACE", 0.3)
    assert asyncio.run(manager.recover()) == [] and json.loads(saved.read_text())["state"] == "RUNNING"
    monkeypatch.undo()
    assert asyncio.run(manager.recover()) == [folder.name] and _gone(run)        # the next start does


def test_an_orphan_another_server_closed_meanwhile_is_not_closed_again(tmp_path: Path, monkeypatch):
    """Two servers start together and both find it: the second reads it again once it is its turn."""
    saved = _record(tmp_path, "web-000000000053")
    manager = ExecutionManager(_config(tmp_path))
    found = manager._orphans

    def found_then_closed_by_another():
        orphans = found()
        record = json.loads(saved.read_text())
        saved.write_text(json.dumps({**record, "state": "FAILED", "error": {"code": "WEB_AGENT_ERROR",
                                                                            "message": "closed by the other"}}))
        return orphans
    monkeypatch.setattr(manager, "_orphans", found_then_closed_by_another)
    assert asyncio.run(manager.recover()) == []
    assert json.loads(saved.read_text())["error"]["message"] == "closed by the other"


def test_cancelling_another_living_servers_run_writes_nothing_and_stops_nothing(tmp_path: Path):
    servers = tmp_path / "executions" / SERVERS
    servers.mkdir(parents=True)
    other = subprocess.Popen([sys.executable, "-c", HOLDS, str(servers / ("c" * 16 + ".lock"))],
                             stdout=subprocess.PIPE, text=True)
    started.append(other)
    _ready(other)
    folder = tmp_path / "executions" / "web-000000000054"
    run, _ = _run(folder, SLEEPER)
    saved = _record(tmp_path, folder.name, pid=run.pid, server="c" * 16)
    before = saved.read_text()
    answer = asyncio.run(ExecutionManager(_config(tmp_path)).cancel(folder.name))
    assert answer.state is ExecutionState.RUNNING and saved.read_text() == before and run.poll() is None


def test_a_run_that_finished_by_itself_after_its_server_was_gone_keeps_what_it_reported(tmp_path: Path):
    folder = tmp_path / "executions" / "web-000000000009"
    (folder / "report").mkdir(parents=True)
    (folder / "run.lock").touch()
    (folder / "report" / "summary.json").write_text(json.dumps({"status": "passed"}))
    (folder / "report" / "test_cases.json").write_text(json.dumps({"tests": [{"name": "t", "steps": [{}]}]}))
    saved = _record(tmp_path, folder.name, pid=2 ** 22 + 7)
    _recover(tmp_path)
    kept = json.loads(saved.read_text())
    assert kept["state"] == "COMPLETED" and kept["error"] is None


def test_records_that_are_not_records_stop_nothing_and_do_not_keep_the_others_from_being_closed(tmp_path: Path):
    for number, fields in enumerate([{"directory": None}, {"server": 12}, {"host": ["x"]}, {"state": "NOPE"}], 20):
        _record(tmp_path, f"web-0000000000{number}", **fields)
    (tmp_path / "executions" / "web-000000000030").mkdir()                       # no record at all
    (tmp_path / "executions" / "web-000000000031").mkdir()
    (tmp_path / "executions" / "web-000000000031" / "execution.json").write_text("[1, 2]")
    (tmp_path / "executions" / "notes").mkdir()
    done = _record(tmp_path, "web-000000000032", state="COMPLETED")
    before = done.read_text()
    good = _record(tmp_path, "web-000000000033")
    manager, closed = _recover(tmp_path)
    assert closed == ["web-000000000033"] and json.loads(good.read_text())["state"] == "FAILED"
    assert done.read_text() == before and manager.get("web-000000000020") is None


def test_a_lock_that_cannot_be_read_is_never_taken_for_a_server_that_stopped(tmp_path: Path, monkeypatch):
    """Only a lock seen free says its holder is gone: when that cannot be told, the run is somebody's."""
    import mcp_server.executions as executions
    folder = tmp_path / "executions" / "web-000000000040"
    run, _ = _run(folder, SLEEPER)
    saved = _record(tmp_path, folder.name, pid=run.pid)
    monkeypatch.setattr(executions, "lock_free", lambda path, **how: None)
    _, closed = _recover(tmp_path)
    assert closed == [] and run.poll() is None and json.loads(saved.read_text())["state"] == "RUNNING"


def test_a_server_holds_its_lock_while_it_runs_and_hands_each_run_its_own(tmp_path: Path):
    lasting = tmp_path / "lasting"                  # stands in for the interpreter: a run that surely lasts
    lasting.write_text("#!/bin/sh\nexec sleep 60\n")
    lasting.chmod(0o755)

    async def scenario() -> None:
        manager = ExecutionManager(_config(tmp_path, python=str(lasting)))
        lock = tmp_path / "executions" / SERVERS / f"{manager._server_id}.lock"
        assert lock_free(lock) is False
        (tmp_path / "flows").mkdir()
        (tmp_path / "flows" / "x.md").write_text("# X\n")
        execution = manager.start(flow_id="x.md", flow_path=tmp_path / "flows" / "x.md", environment="staging",
                                  hosts=[], profile=None, label="x", metadata={})
        record = json.loads(execution.record_file.read_text())
        assert record["server"] == manager._server_id and record["host"] == socket.gethostname()
        for _ in range(250):
            if execution.pid:
                break
            await asyncio.sleep(0.02)
        assert execution.pid and execution.state is ExecutionState.RUNNING
        assert lock_free(execution.run_lock) is False           # held by the run alone: the server closed its handle
        assert json.loads(execution.record_file.read_text())["pid"] == execution.pid
        assert await manager.recover() == []                    # its own runs are never orphans
        await manager.shutdown()
        assert lock_free(execution.run_lock) is True            # the run went with its server
        assert lock_free(lock, missing=None) is True            # and the server's lock is there, free: "gone"

    asyncio.run(scenario())
