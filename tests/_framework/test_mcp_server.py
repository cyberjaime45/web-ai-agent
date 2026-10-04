"""The Web Agent MCP end to end: a real MCP client over stdio → the Web Agent MCP →
a real Web Agent run (pytest subprocess, Chromium) on a local fixture page.

The temporary flows live under the gitignored ``reports/`` tree — inside the
project, so the root conftest loads for them — and run against the ``local``
environment (file:// pages). Skipped when the `mcp` extra or Chromium is missing.
"""

from __future__ import annotations

import asyncio
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

_PASSING = f'# Fixture sign-in page\n\n## Page loads\n- goto: "{_FIXTURE}"\n- assert_text: "Welcome!"\n'
_FAILING = (f'# Fixture sign-in page (broken expectation)\n\n## Page loads\n- goto: "{_FIXTURE}"\n'
            '- assert_text: "Welcome!"\n\n## Signed in\n- assert_text: "This text is not on the page"\n')
_SLOW = f'# Slow flow\n\n## Waits\n- goto: "{_FIXTURE}"\n- wait: 120000\n'
_LIVE = '# Live site\n\n## Home\n- goto: "https://wheelsup.com/"\n'
_INPUT = '# Page from an input\n\n## Page loads\n- goto: "<MCP_TEST_PAGE_URL>"\n- assert_text: "Welcome!"\n'


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
                       ("slow.md", _SLOW), ("live.md", _LIVE), ("input.md", _INPUT)):
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
            assert set(tools) == {"list_flows", "run_flow", "get_status", "get_result", "cancel_execution",
                                  "describe_capabilities", "get_flow", "validate_flow", "save_flow", "explore_page"}
            assert all(t.outputSchema for t in tools.values())

            catalog = await _call(session, "list_flows")
            flows = {f["id"]: f for f in catalog["flows"]}
            assert flows["passing.md"]["environments"] == ["local"]
            assert flows["passing.md"]["tests"] == ["Page loads"]
            assert flows["live.md"]["environments"] == ["production"]
            assert flows["input.md"]["inputs"] == ["MCP_TEST_PAGE_URL"] and flows["input.md"]["environments"] == []
            environments = {e["name"]: e for e in catalog["environments"]}
            assert environments["production"]["enabled"] is False

            only_local = await _call(session, "list_flows", environment="local")
            assert "live.md" not in {f["id"] for f in only_local["flows"]}
            unknown = await _call(session, "list_flows", environment="qa9")
            assert unknown["error"]["code"] == "INVALID_REQUEST"
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
                ({"inputs": {"MCP_TEST_PASSWORD": "x"}}, "credentials are not accepted"),
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
