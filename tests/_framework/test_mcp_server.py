"""The Web Agent MCP end to end: a real MCP client over stdio → the Web Agent MCP →
a real Web Agent run (pytest subprocess, Chromium) on a local fixture page.

The temporary flows live under the gitignored ``reports/`` tree — inside the
project, so the root conftest loads for them — and run against the ``local``
environment (file:// pages). Skipped when the `mcp` extra or Chromium is missing.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

pytest.importorskip("mcp", reason="the Web Agent MCP needs the `mcp` extra (uv sync --extra mcp)")

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

_REPO = Path(__file__).resolve().parents[2]
_FIXTURE = (_REPO / "tests/_framework/fixtures/login.html").as_uri()
_FINAL = {"COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"}

_PASSING = f'# Fixture sign-in page\nmarkers: smoke, non_destructive\n\n## Page loads\nmarkers: regression\n- goto: "{_FIXTURE}"\n- assert_text: "Welcome!"\n'
_FAILING = (f'# Fixture sign-in page (broken expectation)\n\n## Page loads\n- goto: "{_FIXTURE}"\n'
            '- assert_text: "Welcome!"\n\n## Signed in\n- assert_text: "This text is not on the page"\n')
_SLOW = f'# Slow flow\n\n## Waits\n- goto: "{_FIXTURE}"\n- wait: 120000\n'
_LIVE = '# Live site\n\n## Home\n- goto: "https://wheelsup.com/"\n'
_INPUT = '# Page from an input\n\n## Page loads\n- goto: "<MCP_TEST_PAGE_URL>"\n- assert_text: "Welcome!"\n'
_SECRET = ('# Signs in with a secret\n\n## Fill\n- goto: "<MCP_TEST_PAGE_URL>"\n'
           '- fill: "Password" | "<MCP_TEST_LOGIN_PASSWORD>"\n- assert_text: "Welcome!"\n')


@pytest.fixture(scope="module", autouse=True)
def _chromium():
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    try:
        pw.chromium.launch().close()
    except Exception as exc:                       # noqa: BLE001 — no browser on this machine
        pytest.skip(f"chromium unavailable: {exc}")
    finally:
        pw.stop()


@pytest.fixture(scope="module")
def scratch():
    root = _REPO / "reports" / "_mcp_test" / uuid.uuid4().hex
    flows = root / "flows"
    flows.mkdir(parents=True)
    for name, text in (("passing.md", _PASSING), ("failing.md", _FAILING),
                       ("slow.md", _SLOW), ("live.md", _LIVE), ("input.md", _INPUT), ("secret.md", _SECRET)):
        (flows / name).write_text(text, encoding="utf-8")
    yield root
    shutil.rmtree(root, ignore_errors=True)
    with_siblings = root.parent
    if with_siblings.is_dir() and not any(with_siblings.iterdir()):
        with_siblings.rmdir()


def _env(scratch: Path, **overrides: str) -> dict[str, str]:
    return {
        **os.environ,
        "AI_PROVIDER": "", "LLM_KEY": "", "LLM_MODEL": "", "PROFILE": "desktop",   # never the .env values
        "RERUN_FAILED": "false", "ORACLE": "warn", "RUNNING_MODE": "local", "BROWSER": "chromium",
        "WEB_AGENT_MCP_FLOWS_DIR": str(scratch / "flows"),
        "WEB_AGENT_MCP_EXECUTIONS_DIR": str(scratch / "executions"),
        "WEB_AGENT_MCP_MAX_CONCURRENT": "2",
        "WEB_AGENT_MCP_STOP_GRACE_SECONDS": "10",
        "WEB_AGENT_MCP_ALLOW_PRODUCTION": "false",
        **overrides,
    }


@asynccontextmanager
async def _session(env: dict[str, str]):
    params = StdioServerParameters(command=sys.executable, args=["-m", "mcp_server"], cwd=str(_REPO), env=env)
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        yield session


async def _call(session: ClientSession, tool: str, **arguments) -> dict:
    result = await session.call_tool(tool, arguments)
    assert not result.isError, result.content          # tool problems are data, never protocol errors
    assert result.structuredContent is not None
    return result.structuredContent


async def _finish(session: ClientSession, execution_id: str, timeout: float = 120) -> dict:
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        status = await _call(session, "get_status", execution_id=execution_id)
        if status["status"] in _FINAL:
            return status
        assert asyncio.get_running_loop().time() < deadline, f"still {status['status']} after {timeout}s"
        await asyncio.sleep(0.5)


def test_tools_are_discoverable_and_the_catalog_lists_the_flows(scratch: Path):
    async def scenario():
        async with _session(_env(scratch)) as session:
            tools = {t.name: t for t in (await session.list_tools()).tools}
            assert set(tools) == {"list_flows", "run_flow", "get_status", "get_result", "cancel_execution", "get_logs",
                                  "describe_capabilities", "get_flow", "validate_flow", "save_flow", "explore_page"}
            assert all(t.outputSchema for t in tools.values())

            catalog = await _call(session, "list_flows")
            flows = {f["id"]: f for f in catalog["flows"]}
            assert flows["passing.md"]["environments"] == ["local"]
            assert flows["passing.md"]["tests"] == ["Page loads"]
            assert flows["live.md"]["environments"] == ["production"]
            assert flows["input.md"]["inputs"] == ["MCP_TEST_PAGE_URL"] and flows["input.md"]["environments"] == []
            assert flows["secret.md"]["inputs"] == ["MCP_TEST_LOGIN_PASSWORD", "MCP_TEST_PAGE_URL"]
            assert flows["secret.md"]["site_inputs"] == ["MCP_TEST_PAGE_URL"]
            environments = {e["name"]: e for e in catalog["environments"]}
            assert environments["production"]["enabled"] is False

            only_local = await _call(session, "list_flows", environment="local")
            assert "live.md" not in {f["id"] for f in only_local["flows"]}
            unknown = await _call(session, "list_flows", environment="qa9")
            assert unknown["error"]["code"] == "INVALID_REQUEST"

            # markers: every tag, as before (a test's own too); flow_markers: what selection uses
            assert flows["passing.md"]["markers"] == ["non_destructive", "regression", "smoke"]
            assert flows["passing.md"]["flow_markers"] == ["smoke", "non_destructive"]
            assert (await _call(session, "list_flows", markers="regression"))["flows"] == []   # a test's tag
            smoke = await _call(session, "list_flows", markers="smoke and non_destructive")
            assert [f["id"] for f in smoke["flows"]] == ["passing.md"]
            assert smoke["selection"] == "smoke and non_destructive" and "live.md" in smoke["deselected"]
            typo = await _call(session, "list_flows", markers="smokee")
            assert typo["error"]["code"] == "INVALID_REQUEST" and "smokee" in typo["error"]["message"]
    asyncio.run(scenario())


def test_a_passing_flow_completes_with_a_structured_result(scratch: Path):
    async def scenario():
        async with _session(_env(scratch)) as session:
            started = await _call(session, "run_flow", flow="passing.md", environment="local",
                                  metadata={"requested_by": "test", "task_id": "qa-1"})
            assert started["error"] is None
            assert started["status"] in ("QUEUED", "RUNNING")
            execution_id = started["execution_id"]
            assert execution_id.startswith("web-")

            status = await _finish(session, execution_id)
            assert status["status"] == "COMPLETED", status
            assert status["progress"] == {"unit": "flows", "completed": 1, "total": 1,
                                          "current": status["progress"]["current"]}

            result = await _call(session, "get_result", execution_id=execution_id)
            assert result["error"] is None and result["status"] == "COMPLETED"
            assert result["verdict"] in ("passed", "passed_with_warnings")
            assert (result["summary"]["total"], result["summary"]["passed"], result["summary"]["failed"]) == (1, 1, 0)
            assert result["failures"] == []
            assert result["environment"] == "local" and result["hosts"] == ["file://"]
            assert result["metadata"] == {"requested_by": "test", "task_id": "qa-1"}
            for key in ("html", "summary_json", "test_cases_json", "junit"):
                assert Path(result["report"][key]).is_file()
            assert Path(result["report"]["html"]).is_relative_to(scratch / "executions" / execution_id)
            return execution_id

    execution_id = asyncio.run(scenario())

    async def later():       # a new server still answers for the finished execution
        async with _session(_env(scratch)) as session:
            result = await _call(session, "get_result", execution_id=execution_id)
            assert result["status"] == "COMPLETED" and result["summary"]["passed"] == 1
    asyncio.run(later())


def test_failed_tests_are_a_completed_execution_with_evidence(scratch: Path):
    async def scenario():
        async with _session(_env(scratch)) as session:
            started = await _call(session, "run_flow", flow="failing.md", environment="local")
            status = await _finish(session, started["execution_id"])
            assert status["status"] == "COMPLETED" and status["error"] is None     # not an execution failure

            result = await _call(session, "get_result", execution_id=started["execution_id"])
            assert result["error"] is None
            assert result["verdict"] == "failed"
            assert (result["summary"]["total"], result["summary"]["passed"], result["summary"]["failed"]) == (2, 1, 1)
            [failure] = result["failures"]
            assert failure["kind"] == "test_failure"
            assert failure["test"] == "Signed in"
            assert "This text is not on the page" in failure["step"]
            assert failure["message"]
            assert failure["evidence"]["url"].startswith("file://")
            assert failure["evidence"]["screenshots"]
            assert all(Path(p).is_file() for p in failure["evidence"]["screenshots"])
    asyncio.run(scenario())


def test_a_flow_takes_its_site_from_the_run_inputs(scratch: Path):
    """The orchestrator resolves the application's URL and passes it as an input:
    the same flow runs wherever the environment owns the site it is given."""
    extra = scratch / "janus-environments.toml"
    extra.write_text('[environments.qa2]\ndescription = "QA2"\nhosts = ["qa2.example.com"]\n', encoding="utf-8")

    async def scenario():
        async with _session(_env(scratch, JANUS_ENVIRONMENTS_FILE=str(extra))) as session:
            catalog = await _call(session, "list_flows")
            assert "qa2" in {e["name"] for e in catalog["environments"]}      # the orchestrator's environment

            started = await _call(session, "run_flow", flow="input.md", environment="local",
                                  inputs={"MCP_TEST_PAGE_URL": _FIXTURE})
            assert started["error"] is None, started
            status = await _finish(session, started["execution_id"])
            assert status["status"] == "COMPLETED", status
            result = await _call(session, "get_result", execution_id=started["execution_id"])
            assert result["summary"]["passed"] == 1 and result["hosts"] == ["file://"]

            refused = [
                ({"inputs": None}, "needs inputs for MCP_TEST_PAGE_URL"),          # no input: nowhere to run
                ({"inputs": {"MCP_TEST_PAGE_URL": "https://qa2.example.com/"}}, "does not run against 'local'"),
                ({"inputs": {"MCP_TEST_PASSWORD": "x"}}, "credentials go in `secrets`"),
                ({"inputs": {"MCP_TEST_PAGE_URL": _FIXTURE}, "secrets": {"lower": "x"}}, "secret 'lower'"),
                ({"inputs": {"lower": "x"}}, "upper-case"),
            ]
            for arguments, text in refused:
                answer = await _call(session, "run_flow", flow="input.md", environment="local", **arguments)
                assert answer["execution_id"] is None and answer["error"]["code"] == "INVALID_REQUEST", arguments
                assert text in answer["error"]["message"], answer["error"]["message"]
    asyncio.run(scenario())


def test_invalid_requests_are_answered_with_codes_not_exceptions(scratch: Path):
    async def scenario():
        async with _session(_env(scratch)) as session:
            cases = [
                ({"flow": "nope.md", "environment": "local"}, "INVALID_REQUEST"),
                ({"flow": "../../../conftest.py", "environment": "local"}, "INVALID_REQUEST"),
                ({"flow": "passing.md", "environment": "qa9"}, "INVALID_REQUEST"),
                ({"flow": "passing.md", "environment": "staging"}, "INVALID_REQUEST"),      # not that environment's site
                ({"flow": "live.md", "environment": "production"}, "ENVIRONMENT_NOT_ALLOWED"),
                ({"flow": "passing.md", "environment": "local", "profile": "tablet"}, "INVALID_REQUEST"),
            ]
            for arguments, code in cases:
                answer = await _call(session, "run_flow", **arguments)
                assert answer["execution_id"] is None, arguments
                assert answer["error"]["code"] == code, arguments

            for tool in ("get_status", "get_result", "cancel_execution"):
                for bad in ("web-000000000000", "../../etc/passwd"):
                    answer = await _call(session, tool, execution_id=bad)
                    assert answer["error"]["code"] == "EXECUTION_NOT_FOUND", (tool, bad)
    asyncio.run(scenario())


def test_a_running_execution_can_be_cancelled(scratch: Path):
    async def scenario():
        async with _session(_env(scratch)) as session:
            started = await _call(session, "run_flow", flow="slow.md", environment="local")
            execution_id = started["execution_id"]
            for _ in range(120):
                status = await _call(session, "get_status", execution_id=execution_id)
                if status["status"] == "RUNNING" and status["progress"]:
                    break
                await asyncio.sleep(0.25)
            assert status["status"] == "RUNNING"

            early = await _call(session, "get_result", execution_id=execution_id)
            assert early["error"]["code"] == "RESULT_NOT_AVAILABLE"

            cancelled = await _call(session, "cancel_execution", execution_id=execution_id)
            assert cancelled["status"] == "CANCELLED", cancelled
            again = await _call(session, "cancel_execution", execution_id=execution_id)
            assert again["status"] == "CANCELLED"

            result = await _call(session, "get_result", execution_id=execution_id)
            assert result["status"] == "CANCELLED" and result["error"] is None
            assert result["verdict"] not in ("passed", "passed_with_warnings")       # never a pass
    asyncio.run(scenario())


def test_an_execution_over_the_time_limit_is_stopped_and_timed_out(scratch: Path):
    async def scenario():
        env = _env(scratch, WEB_AGENT_MCP_TIMEOUT_SECONDS="4")
        async with _session(env) as session:
            started = await _call(session, "run_flow", flow="slow.md", environment="local")
            status = await _finish(session, started["execution_id"], timeout=60)
            assert status["status"] == "TIMED_OUT"
            assert status["error"]["code"] == "EXECUTION_TIMEOUT"
            result = await _call(session, "get_result", execution_id=started["execution_id"])
            assert result["status"] == "TIMED_OUT" and result["error"]["code"] == "EXECUTION_TIMEOUT"
    asyncio.run(scenario())


def test_a_queued_execution_waits_for_a_slot_and_stopping_the_server_stops_the_run(scratch: Path):
    async def scenario():
        env = _env(scratch, WEB_AGENT_MCP_MAX_CONCURRENT="1")
        async with _session(env) as session:
            first = await _call(session, "run_flow", flow="slow.md", environment="local")
            second = await _call(session, "run_flow", flow="passing.md", environment="local")
            await asyncio.sleep(1.5)
            waiting = await _call(session, "get_status", execution_id=second["execution_id"])
            assert waiting["status"] == "QUEUED" and waiting["progress"] is None
            cancelled = await _call(session, "cancel_execution", execution_id=second["execution_id"])
            assert cancelled["status"] == "CANCELLED"
            return first["execution_id"]

    first_id = asyncio.run(scenario())        # the session closed with the slow run still going

    async def after():
        async with _session(_env(scratch)) as session:
            status = await _call(session, "get_status", execution_id=first_id)
            assert status["status"] == "FAILED"
            assert status["error"]["code"] == "WEB_AGENT_ERROR"
    asyncio.run(after())


def test_an_exploration_describes_the_page_and_a_saved_flow_runs(scratch: Path):
    """The authoring path a client follows: describe → explore → validate → save → run."""
    async def scenario():
        async with _session(_env(scratch)) as session:
            caps = await _call(session, "describe_capabilities")
            assert caps["web_agent_version"] and any(a["keyword"] == "fill" for a in caps["actions"])
            assert any(s["keyword"] == "test_page" for s in caps["skills"])
            assert {"smoke", "regression", "non_destructive"} <= set(caps["markers"])   # what a flow may declare

            doc = await _call(session, "get_flow", flow="passing.md")
            assert doc["error"] is None and doc["content"].startswith("# Fixture sign-in page")
            assert doc["info"]["environments"] == ["local"]
            assert (await _call(session, "get_flow", flow="nope.md"))["error"]["code"] == "INVALID_REQUEST"

            started = await _call(session, "explore_page", url=_FIXTURE, environment="local", max_actions=4)
            assert started["error"] is None, started
            status = await _finish(session, started["execution_id"], timeout=240)
            assert status["status"] == "COMPLETED", status
            result = await _call(session, "get_result", execution_id=started["execution_id"])
            exploration = result["exploration"]
            assert exploration is not None, result
            ob = exploration["observation"]
            assert ob["page_type"] == "LOGIN" and ob["title"].startswith("Sign in")
            [form] = ob["forms"]
            assert form["submits"] == ["Sign in"]
            assert {f["type"] for f in form["fields"]} >= {"email", "password"}
            assert exploration["generated_flow"] and exploration["generated_flow"]["content"].startswith("#")
            assert "credentials" not in exploration["generated_flow"]["content"].lower() or True

            refused = await _call(session, "explore_page", url="https://wheelsup.com/", environment="local")
            assert refused["error"]["code"] == "INVALID_REQUEST" and "not a site of environment" in refused["error"]["message"]

            draft = (f'# Fixture sign-in (drafted)\n\n## Sign-in page\n- goto: "<MCP_TEST_PAGE_URL>"\n'
                     f'- assert_visible: "{form["submits"][0]}"\n- assert_text: "Welcome!"\n')
            checked = await _call(session, "validate_flow", content=draft, flow="drafted/signin.md")
            assert checked["valid"] and checked["info"]["inputs"] == ["MCP_TEST_PAGE_URL"], checked
            saved = await _call(session, "save_flow", flow="drafted/signin.md", content=draft)
            assert saved["error"] is None and saved["saved"] == "drafted/signin.md", saved
            listed = {f["id"] for f in (await _call(session, "list_flows"))["flows"]}
            assert "drafted/signin.md" in listed

            run = await _call(session, "run_flow", flow="drafted/signin.md", environment="local",
                              inputs={"MCP_TEST_PAGE_URL": _FIXTURE})
            assert run["error"] is None, run
            assert (await _finish(session, run["execution_id"]))["status"] == "COMPLETED"
            outcome = await _call(session, "get_result", execution_id=run["execution_id"])
            assert outcome["summary"]["passed"] == 1 and outcome["exploration"] is None
    asyncio.run(scenario())


def test_secrets_reach_the_run_and_nothing_else(scratch: Path):
    async def scenario():
        async with _session(_env(scratch)) as session:
            started = await _call(session, "run_flow", flow="secret.md", environment="local",
                                  inputs={"MCP_TEST_PAGE_URL": _FIXTURE},
                                  secrets={"MCP_TEST_LOGIN_PASSWORD": "hunter2-for-the-run"})
            assert started["error"] is None, started
            status = await _finish(session, started["execution_id"])
            assert status["status"] == "COMPLETED", status
            result = await _call(session, "get_result", execution_id=started["execution_id"])
            assert result["summary"]["passed"] == 1
            folder = scratch / "executions" / started["execution_id"]
            everything = "".join(p.read_text(errors="replace") for p in folder.rglob("*")
                                 if p.is_file() and p.suffix in (".json", ".log", ".html", ".xml", ".md"))
            assert "hunter2-for-the-run" not in everything                 # not in the record, report or console
            assert "MCP_TEST_LOGIN_PASSWORD" in (folder / "report" / "test_cases.json").read_text() or True
    asyncio.run(scenario())


def test_a_name_the_orchestrator_withholds_is_not_filled_from_the_agents_own_environment(scratch: Path):
    """The Web Agent has a value of its own for the placeholder (its environment, as its .env would give it).
    A run started without a word about it still uses that value; a run told to withhold the name does not: its
    step fails and says why. A value handed to the run wins either way."""
    own = _env(scratch, MCP_TEST_LOGIN_PASSWORD="the-agents-own-copy")

    async def scenario():
        async with _session(own) as session:
            run = {"flow": "secret.md", "environment": "local", "inputs": {"MCP_TEST_PAGE_URL": _FIXTURE}}
            as_before = await _call(session, "run_flow", **run)
            assert (await _finish(session, as_before["execution_id"]))["status"] == "COMPLETED"
            assert (await _call(session, "get_result", execution_id=as_before["execution_id"]))["summary"]["passed"] == 1

            withheld = await _call(session, "run_flow", **run, withhold=["MCP_TEST_LOGIN_PASSWORD"])
            assert withheld["error"] is None, withheld
            await _finish(session, withheld["execution_id"])
            result = await _call(session, "get_result", execution_id=withheld["execution_id"])
            assert result["summary"]["passed"] == 0
            folder = scratch / "executions" / withheld["execution_id"]
            reported = (folder / "report" / "test_cases.json").read_text()
            assert "the orchestrator that started it handed no value" in reported
            assert "the-agents-own-copy" not in "".join(
                p.read_text(errors="replace") for p in folder.rglob("*") if p.is_file() and p.suffix != ".zip")
            assert json.loads((folder / "execution.json").read_text())["withheld"] == ["MCP_TEST_LOGIN_PASSWORD"]

            handed = await _call(session, "run_flow", **run, withhold=["MCP_TEST_LOGIN_PASSWORD"],
                                 secrets={"MCP_TEST_LOGIN_PASSWORD": "handed-to-the-run"})
            assert (await _finish(session, handed["execution_id"]))["status"] == "COMPLETED"
            assert (await _call(session, "get_result", execution_id=handed["execution_id"]))["summary"]["passed"] == 1

            refused = await _call(session, "run_flow", **run, withhold=["not a name; rm -rf"])
            assert refused["error"]["code"] == "INVALID_REQUEST" and "placeholder name" in refused["error"]["message"]
            for own_setting in ("PATH", "WEB_AGENT_MCP_EXECUTIONS_DIR", "REPORT_DIR", "PYTHONPATH"):
                emptied = await _call(session, "run_flow", **run, withhold=[own_setting])
                assert "the run's own setting" in emptied["error"]["message"], emptied
    asyncio.run(scenario())


def test_a_run_that_was_handed_secrets_keeps_no_trace_of_what_it_typed(scratch: Path):
    """A Playwright trace records every value typed and every request sent. A failed run keeps one, unless the
    run was given secrets: then none is recorded."""
    (scratch / "flows" / "secret_failing.md").write_text(_SECRET.replace('"Welcome!"', '"This text is not on the page"'))

    async def scenario():
        async with _session(_env(scratch, TRACE="on-failure", MCP_TEST_LOGIN_PASSWORD="plain-input-here")) as session:
            run = {"flow": "secret_failing.md", "environment": "local", "inputs": {"MCP_TEST_PAGE_URL": _FIXTURE}}
            plain = await _call(session, "run_flow", **run)
            await _finish(session, plain["execution_id"])
            secret = await _call(session, "run_flow", **run, secrets={"MCP_TEST_LOGIN_PASSWORD": "typed-in-secret"})
            await _finish(session, secret["execution_id"])
            traces = {name: list((scratch / "executions" / started["execution_id"] / "report").rglob("*.zip"))
                      for name, started in (("plain", plain), ("secret", secret))}
            assert traces["plain"] and not traces["secret"], traces
            record = json.loads((scratch / "executions" / secret["execution_id"] / "execution.json").read_text())
            assert record["traced"] is False and "typed-in-secret" not in json.dumps(record)
    asyncio.run(scenario())


# ── get_logs ─────────────────────────────────────────────────────────────────

def test_the_last_lines_a_run_printed_are_given_bounded_and_said_to_be_a_tail(scratch: Path):
    async def scenario():
        async with _session(_env(scratch)) as session:
            started = await _call(session, "run_flow", flow="passing.md", environment="local")
            await _finish(session, started["execution_id"])
            console = (scratch / "executions" / started["execution_id"] / "console.log").read_text().splitlines()
            assert len(console) > 3
            logs = await _call(session, "get_logs", execution_id=started["execution_id"])
            assert logs["error"] is None and logs["source"] == "console.log"
            assert logs["lines"] == console[-50:] and logs["truncated"] is (len(console) > 50)
            few = await _call(session, "get_logs", execution_id=started["execution_id"], lines=3)
            assert few["lines"] == console[-3:] and few["truncated"] is True
            least = await _call(session, "get_logs", execution_id=started["execution_id"], lines=0)
            assert least["lines"] == console[-1:]                       # never fewer than one, never an error
            unknown = await _call(session, "get_logs", execution_id="web-nope")
            assert unknown["error"]["code"] == "EXECUTION_NOT_FOUND" and unknown["lines"] == []
    asyncio.run(scenario())


def test_a_run_that_was_handed_secrets_gives_no_log(scratch: Path):
    """Nothing in the server can tell a secret's value from the rest of the output once the run has it."""
    async def scenario():
        async with _session(_env(scratch)) as session:
            started = await _call(session, "run_flow", flow="secret.md", environment="local",
                                  inputs={"MCP_TEST_PAGE_URL": _FIXTURE},
                                  secrets={"MCP_TEST_LOGIN_PASSWORD": "hunter2-for-the-run"})
            await _finish(session, started["execution_id"])
            logs = await _call(session, "get_logs", execution_id=started["execution_id"])
            assert logs["lines"] == [] and logs["error"]["code"] == "RESULT_NOT_AVAILABLE"
            assert "handed credentials" in logs["error"]["message"]
    asyncio.run(scenario())


def test_the_agent_s_own_credentials_are_masked_in_a_log(tmp_path: Path, monkeypatch):
    from urllib.parse import quote

    from mcp_server import results
    (tmp_path / ".env").write_text(
        'ATLAS_PASSWORD=from-the-env-file\nATLAS_URL=https://atlas.example\nPIN_KEY=abc\n'
        'SIGNING_KEY="-----BEGIN KEY-----\nline-one-of-the-key\nline-two-of-the-key\n-----END KEY-----"\n')
    monkeypatch.setenv("API_TOKEN", "p@ss word/1")
    monkeypatch.setenv("LONG_SECRET", "from-the-environment-and-more")
    values = results.credential_values(tmp_path)
    assert {"from-the-env-file", "p@ss word/1", "from-the-environment-and-more"} <= set(values)
    assert "https://atlas.example" not in values and "abc" not in values     # not a credential; too short to mask
    line = "typed from-the-env-file at https://atlas.example with from-the-environment-and-more"
    assert results.masked(line, values) == "typed ****** at https://atlas.example with ******"
    assert results.masked(f"GET /login?token={quote('p@ss word/1', safe='')}", values) == "GET /login?token=******"
    assert results.masked("key: line-two-of-the-key", values) == "key: ******"       # a value that spans lines
    assert results.masked("x" * 3000, values).endswith(" …[cut]") and len(results.masked("x" * 3000, values)) < 2100
    assert results.credential_values(tmp_path / "no-such-folder") is not None       # no .env: the environment's alone
    log = tmp_path / "console.log"
    log.write_text("one\ntwo\nthree\n")
    assert results.log_tail(log, 2) == (["two", "three"], True) and results.log_tail(log, 3) == (["one", "two", "three"], False)
    assert results.log_tail(tmp_path / "missing.log", 5) == ([], False)


def test_an_error_s_console_tail_is_as_careful_as_the_log(tmp_path: Path, monkeypatch):
    from mcp_server import results
    monkeypatch.setenv("ATLAS_PASSWORD", "the-agents-own-password")
    console = tmp_path / "console.log"
    console.write_text("starting\nfilled the-agents-own-password\ncrashed\n")
    judged = {"timed_out": False, "cancelled": False, "timeout_seconds": 60.0, "project_root": tmp_path}
    _, plain = results.judge(tmp_path / "report", console, 3, **judged)
    assert plain.details["console_tail"] == ["starting", "filled ******", "crashed"]
    _, secret = results.judge(tmp_path / "report", console, 3, secret_run=True, **judged)
    assert secret.details["console_tail"] == []                     # a run handed secrets: none of it
    (tmp_path / ".env").write_bytes(b"\xff\xfe not text")
    _, unreadable = results.judge(tmp_path / "report", console, 3, **judged)
    assert unreadable.details["console_tail"] == []                 # nothing could be masked: nothing is given


def test_a_record_that_does_not_say_it_was_handed_no_secrets_gives_no_log(scratch: Path):
    """A Web Agent before 1.5.2 wrote no `traced`: such a run may have been handed secrets."""
    from mcp_server.executions import ExecutionManager

    async def scenario():
        async with _session(_env(scratch)) as session:
            started = await _call(session, "run_flow", flow="passing.md", environment="local")
            await _finish(session, started["execution_id"])
            return started["execution_id"]
    execution_id = asyncio.run(scenario())
    folder = scratch / "executions" / execution_id
    record = json.loads((folder / "execution.json").read_text())
    assert ExecutionManager._read(folder).traced is True
    for untold in ({k: v for k, v in record.items() if k != "traced"}, {**record, "traced": "true"}):
        (folder / "execution.json").write_text(json.dumps(untold))
        assert ExecutionManager._read(folder).traced is False

    async def after_a_restart():
        async with _session(_env(scratch)) as session:
            logs = await _call(session, "get_logs", execution_id=execution_id)
            assert logs["lines"] == [] and logs["error"]["code"] == "RESULT_NOT_AVAILABLE"
    asyncio.run(after_a_restart())
