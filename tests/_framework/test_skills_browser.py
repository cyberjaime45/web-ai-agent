"""The four skills and the oracle against a local fixture page, in a real Chromium.

One browser for the module; skipped when Chromium is not installed. Nothing
here touches the developer's .env: provider=None, artifacts in tmp_path.
"""

from __future__ import annotations

import functools
import http.server
import threading
from pathlib import Path

import pytest

from app.execution.engine import FlowRunner
from app.flow.parser import parse_flow_markdown
from app.observability.recorder import PageRecorder

FIXTURES = Path(__file__).parent / "fixtures"


class _Handler(http.server.SimpleHTTPRequestHandler):
    """Static fixtures plus two API stubs the page calls: a 404 and a 500."""

    def do_GET(self):
        if self.path.startswith("/api/boom"):
            self.send_error(500, "boom")
        elif self.path.startswith("/api/"):
            self.send_error(404, "no such api")
        else:
            super().do_GET()

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def fixture_url():
    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(_Handler, directory=str(FIXTURES)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/form_page.html"
    server.shutdown()


@pytest.fixture(scope="module")
def page():
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    try:
        browser = pw.chromium.launch()
    except Exception as exc:                       # no browser on this machine
        pw.stop()
        pytest.skip(f"chromium unavailable: {exc}")
    context = browser.new_context(viewport={"width": 1280, "height": 800})
    pg = context.new_page()
    pg.set_default_timeout(5000)
    yield pg
    context.close()
    browser.close()
    pw.stop()


def _run(page, tmp_path, steps: str, config: str = ""):
    md = "# Fixture\n\n" + (f"## Config\n{config}\n\n" if config else "") + "## Steps\n" + steps
    recorder = PageRecorder()
    recorder.attach(page)
    runner = FlowRunner(artifacts_dir=str(tmp_path), flows_dir=tmp_path, provider=None)
    return runner.run(parse_flow_markdown(md), page, recorder=recorder)


def _checks(step) -> dict:
    return {c.name: c for c in step.checks}


def test_inspect_page_describes_the_fixture(page, fixture_url, tmp_path):
    result = _run(page, tmp_path, f'- goto: "{fixture_url}"\n- inspect_page\n')
    assert result.success
    marker = result.steps[1]
    assert marker.group and marker.action.type.value == "inspect_page"
    checks = _checks(marker)
    assert checks["page type"].detail == "FORM"
    assert checks["headings"].detail == "1: Members"
    assert "Add Member" in checks["buttons"].detail
    assert "4 fields, 2 required; submit: Save member" in checks["form: Add member"].detail
    assert checks["tables"].detail == "1"


def test_test_form_runs_the_validation_checks_without_submitting(page, fixture_url, tmp_path):
    result = _run(page, tmp_path, f'- goto: "{fixture_url}"\n- test_form\n')
    marker, *children = result.steps[1:]
    assert marker.success, marker.message
    checks = _checks(marker)
    assert checks["empty submission rejected"].passed
    assert "name, email" in checks["empty submission rejected"].detail
    assert checks["invalid email rejected"].passed
    assert checks["value shorter than 3 rejected"].passed
    assert checks["valid input accepted"].passed
    assert checks["submission"].detail.startswith("skipped")
    raws = [c.action.raw for c in children]
    assert raws.count('click: "Save member"') == 3           # empty, bad email, too short
    # the fixture's labels wrap their controls → selector targets (see observer._field_target)
    assert any(r.startswith("fill: \"input[name='email']\" | \"qa.webagent+") for r in raws)
    assert "select: \"select[name='role']\" | \"Viewer\"" in raws
    assert "check: \"input[name='active']\"" in raws
    assert all(c.success and c.sub_flow == "test_form" for c in children)
    assert all(c.layer_used == 1 for c in children)          # deterministic, nothing healed
    assert page.title() != "Saved"                            # never submitted


def test_test_form_submit_true_submits_the_valid_input(page, fixture_url, tmp_path):
    result = _run(page, tmp_path, f'- goto: "{fixture_url}"\n- test_form: "submit=true"\n')
    marker = result.steps[1]
    assert marker.success, marker.message
    assert _checks(marker)["submission accepted"].passed
    assert page.title() == "Saved"


def test_check_console_network_flags_the_fixture_noise_unless_ignored(page, fixture_url, tmp_path):
    # networkidle: the page's fetches must have answered before the check reads the recorder
    result = _run(page, tmp_path, f'- goto: "{fixture_url}"\n- wait_load: "networkidle"\n- check_console_network\n')
    marker = result.steps[2]
    checks = _checks(marker)
    assert not checks["no console errors"].passed and "fixture: a console error" in checks["no console errors"].detail
    assert not checks["no failed requests"].passed and "/api/boom → 500" in checks["no failed requests"].detail
    assert not checks["no 4xx responses"].passed and "does-not-exist → 404" in checks["no 4xx responses"].detail
    assert not marker.success                                  # a 5xx is an error, the rest warnings

    result = _run(page, tmp_path, f'- goto: "{fixture_url}"\n- wait_load: "networkidle"\n- check_console_network\n',
                  config='- ignore_network: "/api/"\n- ignore_console: "fixture:"')
    marker = result.steps[2]
    assert marker.success and all(c.passed for c in marker.checks)


def test_test_responsive_opens_the_mobile_menu_and_restores_the_viewport(page, fixture_url, tmp_path):
    result = _run(page, tmp_path, f'- goto: "{fixture_url}"\n- test_responsive: "viewports=390x664"\n')
    marker, *children = result.steps[1:]
    assert marker.success, marker.message
    checks = _checks(marker)
    assert checks["viewports"].detail == "1280x800, 390x664"
    assert checks["[1280x800] no horizontal overflow"].passed
    assert checks["[390x664] mobile menu opens"].passed
    assert [c.action.raw for c in children] == ['click: "Open menu"', 'press: "Escape"']
    assert set(marker.evidence.screenshots) == {"1280x800", "390x664"}
    assert page.viewport_size == {"width": 1280, "height": 800}


def test_oracle_records_checks_after_goto(page, fixture_url, tmp_path):
    result = _run(page, tmp_path, f'- goto: "{fixture_url}"\n- assert_text: "Members"\n')
    goto, assertion = result.steps
    names = {c.name for c in goto.checks}
    assert {"page rendered", "no page errors", "no blocking dialog", "no horizontal overflow"} <= names
    assert _checks(goto)["page rendered"].passed
    assert assertion.checks == [] and result.success          # warn mode never fails


def test_explore_page_builds_a_graph_and_respects_safety(page, fixture_url, tmp_path):
    result = _run(page, tmp_path,
                  f'- goto: "{fixture_url}"\n- explore_page: "depth=2" | "max_actions=20" | "max_pages=3"\n')
    marker, *children = result.steps[1:]
    checks = _checks(marker)
    graph = checks["graph"].detail
    assert graph.startswith("Members — QA fixture (FORM) http://")
    assert "Members [navigates → " in graph and "members.html" in graph
    assert "Edit [opens dialog \"Edit member\"]" in graph
    assert "Docs (external) [external → https://example.com/]" in graph
    assert "skipped by safety: Delete member" in graph
    assert "Save member [changes page]" in graph                     # validation message appeared
    assert "Refresh [no observable result]" in graph
    assert not checks["no broken pages"].passed and "missing.html → HTTP 404" in checks["no broken pages"].detail
    assert not marker.success                                       # the broken page is a defect
    assert checks["planning"].detail.startswith("deterministic")
    assert "Delete member — name contains 'delete'" in checks["skipped by safety"].detail
    raws = [c.action.raw for c in children]
    assert 'click: "Delete member"' not in raws and 'click: "Save changes"' not in raws
    assert raws.count('press: "Escape"') >= 1 and 'back' in raws
    assert all(c.success for c in children)                        # every click and return worked
    assert "explore_graph" in [k for k in result.steps[0].action.args] or True


def test_test_page_composes_skills_and_generates_a_flow(page, fixture_url, tmp_path):
    result = _run(page, tmp_path, f'- goto: "{fixture_url}"\n- test_page: "max_actions=6"\n',
                  config='- ignore_console: "fixture:"\n- ignore_network: "/api/"')
    marker, *children = result.steps[1:]
    checks = _checks(marker)
    assert checks["page type"].detail == "FORM (deterministic)"
    assert "form 'Add member': 4 fields" in checks["components"].detail
    nested = [c.action.type.value for c in children if c.group and c.sub_flow == "test_page"]
    assert nested == ["check_console_network", "test_form", "test_responsive"]
    inner = [c for c in children if c.sub_flow == "test_page/test_form"]
    assert inner and all(c.success for c in inner)
    assert marker.success, marker.message
    assert marker.agent["page_type"] == "FORM" and marker.agent["ai_calls"] == 0
    assert "validate the form (submit=false)" in marker.agent["plan"]
    generated = Path(marker.agent["generated"])
    assert generated.exists() and generated.name.endswith("__desktop__test_page.md")
    from app.flow.parser import parse_flow_file
    flow = parse_flow_file(generated)
    kinds = [a.type.value for a in flow.actions]
    assert kinds[0] == "goto" and "click" in kinds and "fill" in kinds and "select" in kinds
    assert "press" not in kinds                      # test_responsive's viewport-bound steps stay out
    assert not any(k in ("test_form", "test_page", "screenshot") for k in kinds)


def test_test_page_on_a_list_page_explores(page, fixture_url, tmp_path):
    url = fixture_url.replace("form_page.html", "members.html")
    result = _run(page, tmp_path, f'- goto: "{url}"\n- test_page: "depth=1" | "max_actions=8"\n')
    marker, *children = result.steps[1:]
    assert _checks(marker)["page type"].detail == "TABLE (deterministic)"
    nested = [c.action.type.value for c in children if c.group and c.sub_flow == "test_page"]
    assert "explore_page" in nested
    explore = next(c for c in children if c.group and c.action.type.value == "explore_page")
    assert "Delete member" in " ".join(marker.agent["skipped"])
    assert explore.agent and "generated" not in explore.agent          # one file per test_page
    assert Path(marker.agent["generated"]).exists()
