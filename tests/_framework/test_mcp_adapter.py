"""The Web Agent MCP's own logic — catalog, environment allow-list, outcome and
result mapping — without a server, a subprocess or a browser."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("mcp", reason="the Web Agent MCP needs the `mcp` extra (uv sync --extra mcp)")

from mcp_server import results
from mcp_server.catalog import (
    FILE_TARGET,
    Catalog,
    Environment,
    load_environments,
)
from mcp_server.config import AdapterConfig, ConfigError, load_config
from mcp_server.models import ErrorCode, ExecutionState

_ENVIRONMENTS = {
    "staging": Environment("staging", hosts=("staging.example.com",)),
    "production": Environment("production", hosts=("example.com", "*.example.org"), production=True),
    "local": Environment("local", hosts=("localhost",), allow_file_urls=True),
}


def _config(root: Path, **overrides) -> AdapterConfig:
    values = {
        "project_root": root, "flows_dir": root / "flows", "executions_dir": root / "executions",
        "environments_file": root / "environments.toml", "extra_environments_file": None,
        "timeout_seconds": 60, "stop_grace_seconds": 1,
        "max_concurrent": 1, "headless": True, "allow_production": False, "python": "python"}
    return AdapterConfig(**{**values, **overrides})


def _flow(root: Path, name: str, text: str) -> None:
    path = root / "flows" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def catalog(tmp_path: Path) -> Catalog:
    _flow(tmp_path, "app/login.md", '# Login\n\n## Sign in\n- goto: "https://staging.example.com/login"\n'
                                    '- assert_text: "Welcome"\n\n## Expected Outcome\n- The user is signed in\n')
    _flow(tmp_path, "app/live.md", '# Live\n\n## Home\n- goto: "https://example.com/"\n')
    _flow(tmp_path, "app/mixed.md", '# Mixed\n\n## Both\n- goto: "https://staging.example.com/"\n'
                                    '- goto: "https://example.com/"\n')
    _flow(tmp_path, "app/with_component.md", '# Uses a component\n\n## Steps\n- run_flow: "components/open"\n'
                                             '- assert_text: "Hi"\n')
    _flow(tmp_path, "app/components/open.md", '# Open\n\n## Steps\n- goto: "https://sub.example.org/"\n')
    _flow(tmp_path, "app/fixture.md", '# Fixture\n\n## Page\n- goto: "file:///tmp/page.html"\n')
    _flow(tmp_path, "app/no_site.md", '# No site\n\n## Steps\n- assert_text: "x"\n')
    _flow(tmp_path, "app/placeholder.md", '# Placeholder\n\n## Steps\n- goto: "<MCP_TEST_UNSET_URL>"\n')
    _flow(tmp_path, "app/broken.md", '# Broken\n\n## Steps\n- fill\n')
    _flow(tmp_path, "_framework/internal.md", '# Internal\n\n## Steps\n- goto: "https://example.com/"\n')
    return Catalog(_config(tmp_path), _ENVIRONMENTS)


# ── Catalog ─────────────────────────────────────────────────────────────────

def test_catalog_lists_flows_with_their_sites_and_environments(catalog: Catalog):
    entries, unavailable = catalog.list()
    flows = {e.info.id: e.info for e in entries}

    assert flows["app/login.md"].title == "Login"
    assert flows["app/login.md"].tests == ["Sign in"]
    assert flows["app/login.md"].expected == ["The user is signed in"]
    assert flows["app/login.md"].hosts == ["staging.example.com"]
    assert flows["app/login.md"].environments == ["staging"]
    assert flows["app/live.md"].environments == ["production"]
    assert flows["app/fixture.md"].hosts == [FILE_TARGET]
    assert flows["app/fixture.md"].environments == ["local"]
    assert [u.id for u in unavailable] == ["app/broken.md"]


def test_a_flow_spanning_two_environments_runs_against_neither(catalog: Catalog):
    assert catalog.get("app/mixed.md").info.environments == []


def test_component_sites_count_and_components_are_not_runnable_flows(catalog: Catalog):
    info = catalog.get("app/with_component.md").info
    assert info.hosts == ["sub.example.org"]          # from the component, wildcard host
    assert info.environments == ["production"]
    assert info.tests == ["Uses a component"]          # the generic "Steps" heading names nothing
    assert catalog.get("app/components/open.md") is None
    assert "app/components/open.md" not in {e.info.id for e in catalog.list()[0]}


def test_a_flow_whose_site_is_unknown_runs_nowhere(catalog: Catalog):
    assert catalog.get("app/no_site.md").info.environments == []
    assert catalog.get("app/placeholder.md").info.environments == []


def test_a_placeholder_site_is_filled_from_the_run_inputs(catalog: Catalog):
    listed = catalog.get("app/placeholder.md").info
    assert listed.inputs == ["MCP_TEST_UNSET_URL"] and listed.hosts == [] and listed.environments == []
    filled = catalog.get("app/placeholder.md", {"MCP_TEST_UNSET_URL": "https://staging.example.com/app/"}).info
    assert filled.hosts == ["staging.example.com"] and filled.environments == ["staging"]
    assert filled.inputs == ["MCP_TEST_UNSET_URL"]
    elsewhere = catalog.get("app/placeholder.md", {"MCP_TEST_UNSET_URL": "https://example.com/"}).info
    assert elsewhere.environments == ["production"]
    assert catalog.get("app/login.md").info.inputs == []            # a literal URL declares no input


def test_the_environment_files_are_read_on_every_call_and_merged(tmp_path: Path):
    own = tmp_path / "environments.toml"
    own.write_text('[environments.staging]\nhosts = ["staging.example.com"]\n'
                   '[environments.production]\nproduction = true\nhosts = ["example.com"]\n')
    extra = tmp_path / "janus.toml"
    extra.write_text('[environments.staging]\nhosts = ["one-staging.example.com"]\n'
                     '[environments.qa2]\ndescription = "QA2"\nhosts = ["qa2.example.com"]\n')
    _flow(tmp_path, "app/qa.md", '# QA\n\n## Steps\n- goto: "<APP_URL>"\n')
    catalog = Catalog(_config(tmp_path, extra_environments_file=extra))
    assert set(catalog.environments) == {"staging", "production", "qa2"}
    assert catalog.environments["staging"].hosts == ("staging.example.com", "one-staging.example.com")
    assert catalog.environments["production"].production
    assert catalog.get("app/qa.md", {"APP_URL": "https://qa2.example.com/"}).info.environments == ["qa2"]

    extra.write_text(extra.read_text() + '[environments.qa5]\nhosts = ["qa5.example.com"]\n')
    assert "qa5" in catalog.environments                             # no restart needed
    extra.write_text("not toml [")
    assert "qa5" in catalog.environments                             # a broken file keeps the last good list
    assert load_environments(own)["staging"].hosts == ("staging.example.com",)


@pytest.mark.parametrize("flow_id", ["../environments.toml", "/etc/passwd", "app/login", "", "app/missing.md",
                                     "_framework/internal.md", "app/../../flows/app/login.txt"])
def test_only_catalog_flows_resolve(catalog: Catalog, flow_id: str):
    assert catalog.get(flow_id) is None


def test_production_is_disabled_unless_allowed(tmp_path: Path):
    blocked = Catalog(_config(tmp_path), _ENVIRONMENTS)
    allowed = Catalog(_config(tmp_path, allow_production=True), _ENVIRONMENTS)
    assert {e.name: e.enabled for e in blocked.environment_infos()} == {
        "staging": True, "production": False, "local": True}
    assert all(e.enabled for e in allowed.environment_infos())
    assert blocked.environment(" Staging ").name == "staging"
    assert blocked.environment("qa9") is None


def test_environment_host_matching_is_exact_unless_a_wildcard_is_written():
    prod = _ENVIRONMENTS["production"]
    assert prod.owns("example.com") and prod.owns("a.example.org")
    assert not prod.owns("staging.example.com")        # a subdomain is another site
    assert not prod.owns(FILE_TARGET)


def test_environments_file_is_validated(tmp_path: Path):
    good = tmp_path / "good.toml"
    good.write_text('[environments.QA2]\ndescription = "QA2"\nhosts = ["QA2.example.com"]\n')
    assert load_environments(good)["qa2"].hosts == ("qa2.example.com",)

    for text in ("", "not toml [", '[environments.x]\nhosts = "one"\n'):
        bad = tmp_path / "bad.toml"
        bad.write_text(text)
        with pytest.raises(ConfigError):
            load_environments(bad)
    with pytest.raises(ConfigError):
        load_environments(tmp_path / "missing.toml")


def test_the_shipped_environments_file_loads_and_blocks_production():
    config = load_config()
    environments = load_environments(config.environments_file)
    assert environments["production"].production
    assert not environments["staging"].production


def test_flows_folder_must_be_inside_the_project(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEB_AGENT_MCP_FLOWS_DIR", str(tmp_path))
    with pytest.raises(ConfigError, match="must be inside"):
        load_config()
    monkeypatch.setenv("WEB_AGENT_MCP_FLOWS_DIR", "tests")
    monkeypatch.setenv("WEB_AGENT_MCP_TIMEOUT_SECONDS", "soon")
    with pytest.raises(ConfigError, match="must be a number"):
        load_config()


# ── Outcome: test failure vs execution failure ──────────────────────────────

def _report(root: Path, status: str, tests: list[dict], **totals) -> Path:
    report = root / "report"
    (report / "images").mkdir(parents=True, exist_ok=True)
    counted = {"total": len(tests), "passed": 0, "failed": 0, "skipped": 0, "errors": 0,
               "warnings": 0, "unverified": 0, "pass_rate": 0.0, "duration_ms": 1200.0, **totals}
    (report / "summary.json").write_text(json.dumps({
        "run_id": "20260101_000000", "created_at": "2026-01-01T00:00:00+00:00", "status": status,
        "environment": {"browser": "chromium", "headless": True, "framework": "1.2.0", "playwright": "1.63.0"},
        "totals": counted}))
    (report / "test_cases.json").write_text(json.dumps({"run_id": "20260101_000000", "tests": tests}))
    (report / "report.html").write_text("<html></html>")
    return report


def _judge(report: Path, exit_code: int | None, **flags) -> tuple:
    options = {"timed_out": False, "cancelled": False, "timeout_seconds": 60, **flags}
    return results.judge(report, report.parent / "console.log", exit_code, **options)


_PASSED = {"name": "Sign in", "file": "app/login.md", "status": "passed",
           "steps": [{"id": "1", "parent": None, "name": "goto", "status": "passed"}]}
_FAILED = {
    "name": "Sign in", "file": "app/login.md", "status": "failed",
    "profile": {"name": "desktop"}, "duration_ms": 900.0,
    "error": {"message": "Section failed"},
    "steps": [
        {"id": "1", "parent": None, "name": "test_form", "status": "failed"},
        {"id": "1.1", "parent": "1", "name": 'assert_text: "Welcome"', "status": "failed",
         "error": 'Text "Welcome" not found',
         "evidence": {"url": "https://staging.example.com/login", "title": "Sign in",
                      "layers": {"L1 exact": "failed", "L2 fuzzy": "failed"},
                      "screenshots": {"viewport": "images/shot.png"}, "trace": "traces/t.zip",
                      "diagnosis": {"verdict": "application", "summary": "Likely application defect",
                                    "signals": ["x"]}}},
        {"id": "2", "parent": None, "name": "click", "status": "skipped"},
    ],
    "warnings": [{"check": "page has one h1", "detail": "2 found", "severity": "warn"}],
    "healings": [{"description": "click"}],
}
_CRASHED = {"name": "Sign in", "file": "app/login.md", "status": "failed", "steps": [],
            "error": {"message": "BrowserType.launch: Executable doesn't exist"}}


def test_failed_tests_are_a_completed_execution(tmp_path: Path):
    report = _report(tmp_path, "failed", [_PASSED, _FAILED], passed=1, failed=1)
    assert _judge(report, 1) == (ExecutionState.COMPLETED, None)
    assert _judge(_report(tmp_path, "passed_with_warnings", [_PASSED], passed=1), 0)[0] is ExecutionState.COMPLETED


def test_no_report_is_a_failed_execution_with_debugging_details(tmp_path: Path):
    (tmp_path / "console.log").write_text("line 1\nERROR: usage error\n")
    state, error = _judge(tmp_path / "report", 4)
    assert state is ExecutionState.FAILED
    assert error.code is ErrorCode.WEB_AGENT_ERROR
    assert error.details["exit_code"] == 4
    assert error.details["console_tail"][-1] == "ERROR: usage error"


def test_a_flow_that_never_ran_a_step_is_a_failed_execution(tmp_path: Path):
    state, error = _judge(_report(tmp_path, "failed", [_CRASHED], failed=1), 1)
    assert state is ExecutionState.FAILED
    assert "Executable doesn't exist" in error.message


def test_a_run_the_web_agent_calls_broken_is_a_failed_execution(tmp_path: Path):
    for status in ("error", "interrupted"):
        state, error = _judge(_report(tmp_path, status, [_PASSED], passed=1), 2)
        assert state is ExecutionState.FAILED and error.code is ErrorCode.WEB_AGENT_ERROR


def test_timeout_and_cancel_win_over_whatever_was_reported(tmp_path: Path):
    report = _report(tmp_path, "interrupted", [_PASSED], passed=1)
    state, error = _judge(report, 2, timed_out=True)
    assert state is ExecutionState.TIMED_OUT and error.code is ErrorCode.EXECUTION_TIMEOUT
    assert _judge(report, 2, cancelled=True) == (ExecutionState.CANCELLED, None)


# ── Result mapping ──────────────────────────────────────────────────────────

def test_result_carries_totals_failures_evidence_and_report_paths(tmp_path: Path):
    report = _report(tmp_path, "failed", [_PASSED, _FAILED], passed=1, failed=1, pass_rate=50.0)
    result = results.build_result(report)

    assert result["verdict"] == "failed"
    assert (result["summary"].total, result["summary"].passed, result["summary"].failed) == (2, 1, 1)
    assert [t.status for t in result["tests"]] == ["passed", "failed"]

    failure = result["failures"][0]
    assert failure.kind == "test_failure"
    assert failure.step == 'assert_text: "Welcome"'          # the leaf, not the group that holds it
    assert failure.message == 'Text "Welcome" not found'
    assert failure.likely_cause == {"verdict": "application", "summary": "Likely application defect"}
    assert failure.evidence.url == "https://staging.example.com/login"
    assert failure.evidence.screenshots == [str((report / "images/shot.png").resolve())]
    assert failure.evidence.trace == str((report / "traces/t.zip").resolve())
    assert failure.evidence.layers["L1 exact"] == "failed"

    assert result["warnings"][0].check == "page has one h1"
    assert result["healed_steps"] == 1
    assert result["report"].html == str(report / "report.html")
    assert result["report"].junit is None                     # not written: not claimed
    assert result["run"]["web_agent_version"] == "1.2.0"


def test_a_crashed_test_is_reported_as_an_execution_error(tmp_path: Path):
    result = results.build_result(_report(tmp_path, "failed", [_PASSED, _CRASHED], passed=1, failed=1))
    failure = result["failures"][0]
    assert failure.kind == "execution_error" and failure.step is None
    assert "Executable doesn't exist" in failure.message


def test_no_report_means_no_result(tmp_path: Path):
    assert results.build_result(tmp_path / "report") is None
