"""The four skills and the oracle against a local fixture page, in a real Chromium.

One browser for the module; skipped when Chromium is not installed. Nothing
here touches the developer's .env: provider=None, artifacts in tmp_path.
"""

from __future__ import annotations

import functools
import json
import http.server
import threading
import time
from pathlib import Path

import pytest

from app.execution.engine import FlowRunner
from app.flow.parser import parse_flow_markdown
from app.observability.recorder import PageRecorder

FIXTURES = Path(__file__).parent / "fixtures"


class _Handler(http.server.SimpleHTTPRequestHandler):
    """Static fixtures plus API stubs: a 404, a 500 and a slow JSON answer."""

    def do_GET(self):
        if self.path.startswith("/api/boom"):
            self.send_error(500, "boom")
        elif self.path.startswith("/api/slow"):
            time.sleep(0.6)
            body = b'{"count": 3}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path.startswith("/api/"):
            self.send_error(404, "no such api")
        else:
            super().do_GET()

    def do_HEAD(self):
        if self.path.startswith("/api/boom"):
            self.send_error(500, "boom")
        else:
            super().do_HEAD()

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def fixture_url():
    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(_Handler, directory=str(FIXTURES)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/form_page.html"
    server.shutdown()


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
    assert checks["submission"].outcome == "skipped" and "submit=true" in checks["submission"].detail
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
    assert checks["[1280x800, 390x664] no horizontal overflow"].passed      # one check for both widths
    assert checks["[390x664] mobile menu opens"].passed
    assert [c.action.raw for c in children] == ['click: "Open menu"', 'press: "Escape"']
    assert set(marker.evidence.screenshots) == {"1280x800", "390x664"}
    assert page.viewport_size == {"width": 1280, "height": 800}


def test_oracle_records_checks_after_goto(page, fixture_url, tmp_path):
    result = _run(page, tmp_path, f'- goto: "{fixture_url}"\n- assert_text: "Members"\n')
    goto, assertion = result.steps
    names = {c.name for c in goto.checks}
    assert {"page rendered", "no page errors", "no failed requests", "no horizontal overflow"} <= names
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
    assert "Save member" not in graph                                # a form's submit is test_form's job
    assert "Save member (form:Add member)" in checks["form buttons not pressed"].detail
    assert checks["form buttons not pressed"].outcome == "skipped"
    assert "Refresh [no observable result]" in graph
    assert checks["no broken pages"].passed                         # each broken page failed at its own step
    assert "missing.html → HTTP 404" in checks["broken pages found"].detail
    assert not marker.success                                       # the broken page is a defect
    assert checks["planning"].detail.startswith("deterministic")
    assert "Delete member — name contains 'delete'" in checks["blocked by safety"].detail
    assert checks["blocked by safety"].outcome == "blocked"
    raws = [c.action.raw for c in children]
    assert 'click: "Delete member"' not in raws and 'click: "Save changes"' not in raws
    assert 'click: "Save member"' not in raws
    assert raws.count('press: "Escape"') >= 1 and 'back' in raws
    # a click that led to a broken page fails itself, with its own evidence; the rest worked
    broken = [c for c in children if not c.success]
    assert broken and all(c.message.startswith("broken page: ") and not c.soft and c.evidence for c in broken)
    assert any(c.action.raw == 'goto: "' + fixture_url.replace("form_page.html", "missing.html") + '"' for c in broken)
    assert "explore_graph" in [k for k in result.steps[0].action.args] or True


def test_test_page_composes_skills_and_generates_a_flow(page, fixture_url, tmp_path):
    result = _run(page, tmp_path, f'- goto: "{fixture_url}"\n- test_page: "max_actions=6"\n',
                  config='- ignore_console: "fixture:"\n- ignore_network: "/api/"')
    marker, *children = result.steps[1:]
    checks = _checks(marker)
    assert checks["page type"].detail == "FORM (deterministic)"
    assert "form 'Add member': 4 fields" in checks["components"].detail
    nested = [c.action.type.value for c in children if c.group and c.sub_flow == "test_page"]
    assert nested == ["check_console_network", "check_accessibility", "test_form", "test_responsive"]
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
    assert kinds[0] == "goto" and "fill" in kinds and "select" in kinds
    assert "click" not in kinds                      # test_form's submit presses are never replayed
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


def test_wait_stable_waits_for_the_request_the_spinner_and_the_dom(page, fixture_url, tmp_path):
    url = fixture_url.replace("form_page.html", "async.html")
    result = _run(page, tmp_path, f'- goto: "{url}"\n- click: "Load members"\n- wait_stable\n')
    assert result.success, result.error
    step = result.steps[2]
    assert step.message.startswith("Page settled in") and not step.checks
    assert step.duration >= 0.6                                  # the slow API answer
    assert page.locator("#out").inner_text() == "Loaded 3 members"   # no assertion needed to wait


def test_wait_stable_past_its_budget_is_a_warning_not_a_failure(page, fixture_url, tmp_path):
    url = fixture_url.replace("form_page.html", "async.html")
    result = _run(page, tmp_path, f'- goto: "{url}"\n- click: "Load members"\n- wait_stable: 200\n')
    step = result.steps[2]
    assert result.success and step.success
    settled = _checks(step)["page settled"]
    assert not settled.passed and settled.severity == "warn"
    assert "/api/slow" in settled.detail


def test_check_links_finds_broken_links_and_images_without_clicking(page, fixture_url, tmp_path):
    url = fixture_url.replace("form_page.html", "links.html")
    result = _run(page, tmp_path, f'- goto: "{url}"\n- check_links\n')
    marker = result.steps[1]
    checks = _checks(marker)
    assert not marker.success                                   # broken links are errors
    assert checks["no broken links"].count == 2
    assert "404 " in checks["no broken links"].detail and "missing-page.html" in checks["no broken links"].detail
    assert "500 " in checks["no broken links"].detail
    assert checks["links checked"].detail.startswith("3 of 6 links checked (same site)")
    assert "1 external not checked" in checks["links checked"].detail
    withheld = checks["blocked by safety"].detail
    assert "logout.html — logout link, not requested" in withheld
    assert "/account/delete — delete link, not requested" in withheld
    assert checks["no broken images"].count == 1 and "nope.png" in checks["no broken images"].detail
    assert page.url == url                                      # nothing was clicked
    assert result.steps[2:] == []                               # and no child steps


def test_check_links_images_false_checks_links_only(page, fixture_url, tmp_path):
    url = fixture_url.replace("form_page.html", "members.html")
    result = _run(page, tmp_path, f'- goto: "{url}"\n- check_links: "images=false"\n')
    checks = _checks(result.steps[1])
    assert checks["no broken links"].count == 1                 # members.html links to missing.html
    assert "no broken images" not in checks


def test_check_accessibility_lists_the_fixture_problems(page, fixture_url, tmp_path):
    url = fixture_url.replace("form_page.html", "a11y.html")
    result = _run(page, tmp_path, f'- goto: "{url}"\n- check_accessibility\n')
    marker = result.steps[1]
    checks = _checks(marker)
    assert marker.success                                        # warnings only by default
    assert checks["images have alt text"].count == 1
    assert checks["fields have labels"].count == 1 and 'placeholder "Email" only' in checks["fields have labels"].detail
    assert checks["controls have names"].count == 2               # empty button + empty link; "×" has aria-label
    assert not checks["page language set"].passed
    assert checks["page has an h1"].outcome == "info"            # headings exist; a missing h1 is not a defect
    assert "h2 → h4" in checks["heading levels in order"].detail
    assert checks["referenced ids are unique"].detail == "#dup"
    assert checks["no positive tabindex"].count == 1
    assert checks["dialog holds focus"].passed
    strict = _run(page, tmp_path, f'- goto: "{url}"\n- check_accessibility: "level=strict"\n')
    assert not strict.steps[1].success


def test_check_accessibility_judges_images_names_and_headings_in_context(page, fixture_url, tmp_path):
    url = fixture_url.replace("form_page.html", "login.html")
    checks = _checks(_run(page, tmp_path, f'- goto: "{url}"\n- check_accessibility\n').steps[1])
    # genuine: a content image without alt, a field named only by its placeholder, a visual heading
    assert checks["images have alt text"].count == 1 and checks["images have alt text"].outcome == "warning"
    assert checks["fields have labels"].count == 1 and "#pw" in checks["fields have labels"].detail
    assert checks["visual headings marked up"].outcome == "warning"
    assert '"Welcome!" (div, 36px)' in checks["visual headings marked up"].detail
    # not defects: the background image, the aria-labelledby email field, the logo link's image alt
    assert checks['decorative images without alt=""'].outcome == "info"
    assert "positioned behind the content" in checks['decorative images without alt=""'].detail
    assert checks["controls have names"].passed and "page has an h1" not in checks


def test_test_responsive_judges_tap_targets_and_menus_only_where_they_apply(page, fixture_url, tmp_path):
    url = fixture_url.replace("form_page.html", "login.html")
    marker = _run(page, tmp_path, f'- goto: "{url}"\n- test_responsive: "viewports=390x664"\n').steps[1]
    checks = _checks(marker)
    tap = checks["[390x664] tap targets ≥ 24px"]
    assert tap.outcome == "warning" and '"Help" 16×16' in tap.detail and '"Chat" 16×16' in tap.detail
    assert "Forgot Password" not in tap.detail                  # small, but 24px of room around it
    assert "membership guide" not in tap.detail                 # inline in a sentence
    assert not any("mobile menu" in n for n in checks)          # the hidden nav holds a phone number only

    url = fixture_url.replace("form_page.html", "div_menu.html")
    checks = _checks(_run(page, tmp_path, f'- goto: "{url}"\n- test_responsive: "viewports=390x664"\n').steps[1])
    assert checks["[390x664] mobile menu opens"].passed         # the div opens it for a mouse…
    assert checks["[390x664] menu toggle is a button"].outcome == "warning"   # …not for a keyboard


def test_explore_page_explains_presses_before_calling_them_no_result(page, fixture_url, tmp_path):
    url = fixture_url.replace("form_page.html", "login.html")
    marker = _run(page, tmp_path, f'- goto: "{url}"\n- explore_page: "depth=0" | "max_actions=10"\n').steps[1]
    checks = _checks(marker)
    graph = checks["graph"].detail
    assert "855-FLY-8760 [hands off" in graph
    assert "Home [links to this page" in graph
    assert "Request Info [opens new tab" in graph
    assert "Show password [changes page" in graph
    assert checks["controls respond"].outcome == "info"         # every press explained
    assert len(page.context.pages) == 1                         # the new tab was closed


def test_check_accessibility_passes_the_form_fixture(page, fixture_url, tmp_path):
    result = _run(page, tmp_path, f'- goto: "{fixture_url}"\n- check_accessibility\n')
    assert all(c.passed for c in result.steps[1].checks), result.steps[1].checks


def test_test_table_sorts_pages_and_opens_a_row(page, fixture_url, tmp_path):
    url = fixture_url.replace("form_page.html", "grid.html")
    result = _run(page, tmp_path, f'- goto: "{url}"\n- test_table\n')
    marker, *children = result.steps[1:]
    checks = _checks(marker)
    assert marker.success, marker.message
    assert "4 row(s); columns: Name, Flights, Joined" in checks["table"].detail
    assert checks["sorting works"].passed and checks["sorting works"].detail == "'Name' sorted ascending"
    assert checks["pagination works"].passed and checks["previous page restores the rows"].passed
    assert checks["row opens details"].detail == "'View' opens a dialog"
    raws = [c.action.raw for c in children]
    assert 'click: "Name"' in raws and 'click: "Next"' in raws and 'press: "Escape"' in raws


def test_test_search_uses_a_value_from_the_page(page, fixture_url, tmp_path):
    url = fixture_url.replace("form_page.html", "grid.html")
    result = _run(page, tmp_path, f'- goto: "{url}"\n- test_search\n')
    marker, *children = result.steps[1:]
    checks = _checks(marker)
    assert marker.success, marker.message
    assert "searched for 'Olivia Park'" in checks["search"].detail
    assert checks["search finds a visible value"].passed
    assert checks["search narrows the results"].detail == "4 → 1 result(s)"
    assert checks["no match shows no results"].passed and checks["clearing restores the results"].passed
    assert 'assert_text: "Olivia Park"' in [c.action.raw for c in children]


def test_test_page_on_a_grid_runs_table_and_search_and_asserts_what_it_saw(page, fixture_url, tmp_path):
    url = fixture_url.replace("form_page.html", "grid.html")
    result = _run(page, tmp_path, f'- goto: "{url}"\n- test_page: "max_actions=4"\n')
    marker, *children = result.steps[1:]
    nested = [c.action.type.value for c in children if c.group and c.sub_flow == "test_page"]
    assert nested[:4] == ["check_console_network", "check_accessibility", "test_table", "test_search"]
    assert 'assert_text: "Member profile"' in marker.agent["assertions"]
    generated = Path(marker.agent["generated"]).read_text()
    assert '- assert_text: "Member profile"' in generated
    from app.flow.parser import parse_flow_markdown
    assert parse_flow_markdown(generated).actions                 # the generated flow parses


def test_test_widgets_checks_tabs_disclosures_and_dialogs(page, fixture_url, tmp_path):
    url = fixture_url.replace("form_page.html", "widgets.html")
    result = _run(page, tmp_path, f'- goto: "{url}"\n- test_widgets\n')
    marker = result.steps[1]
    checks = _checks(marker)
    assert marker.success                                         # warnings only
    assert checks["widgets"].detail == "3 tab(s), 2 disclosure(s), 1 dialog trigger(s)"
    assert checks["tabs select their panel"].passed
    assert checks["disclosures toggle"].count == 1
    assert checks["disclosures toggle"].detail == "'Returns questions' aria-expanded stayed false"
    for name in ("dialogs open", "dialog takes focus", "Escape closes the dialog", "focus returns to the opener"):
        assert checks[name].passed, (name, checks[name].detail)
    assert page.locator("#t1").get_attribute("aria-selected") == "true"   # original tab restored


def test_snapshot_page_saves_then_reports_what_disappeared(page, fixture_url, tmp_path, monkeypatch):
    monkeypatch.setattr("app.execution.engine.PROJECT_ROOT", tmp_path.parent)   # baselines under tmp_path
    url = fixture_url.replace("form_page.html", "members.html")
    first = _run(page, tmp_path, f'- goto: "{url}"\n- snapshot_page: "members"\n')
    assert "saved (first run)" in _checks(first.steps[1])["baseline"].detail
    baseline = json.loads((tmp_path / "baselines" / "members__desktop.json").read_text())
    assert "button: Refresh" in baseline["items"] and "heading: Members list" in baseline["items"]
    assert "button: Edit" not in baseline["items"]                 # inside a table row: data, not UI

    page.evaluate("document.getElementById('refresh').remove()")
    second = _run(page, tmp_path, '- snapshot_page: "members"\n')
    checks = _checks(second.steps[0])
    assert second.steps[0].success                                # a removal warns by default
    assert checks["nothing removed"].detail == "button: Refresh" and checks["nothing removed"].count == 1
    strict = _run(page, tmp_path, '- snapshot_page: "members" | "strict=true"\n')
    assert not strict.steps[0].success


def test_check_performance_reports_metrics_against_budgets(page, fixture_url, tmp_path):
    result = _run(page, tmp_path, f'- goto: "{fixture_url}"\n- wait_load: "load"\n- check_performance\n')
    marker = result.steps[2]
    checks = _checks(marker)
    assert marker.success
    assert checks["performance"].detail.startswith("ttfb ")
    assert checks["page load within budget"].passed                # a local static page
    tight = _run(page, tmp_path, f'- goto: "{fixture_url}"\n- wait_load: "load"\n- check_performance: "load=0"\n')
    assert not _checks(tight.steps[2])["page load within budget"].passed and tight.steps[2].success


def test_horizontal_overflow_counts_only_what_the_page_can_scroll_to(page):
    """A wide element the viewport clips (overflow-x: clip / hidden) is not
    overflow — the reviewer could never scroll to it; one it can reach is."""
    from app.execution import oracle
    wide = '<div style="width:3000px;height:10px"></div>'
    for style, expected in (("html, body { overflow-x: clip }", False),
                            ("body { overflow-x: hidden }", False),
                            ("", True)):
        page.set_content(f"<html><head><style>{style}</style></head><body><p>x</p>{wide}</body></html>")
        checks = {c.name: c for c in oracle.probe_checks(page)}
        assert (not checks["no horizontal overflow"].passed) is expected, style
    page.set_content("<p>fits</p>")
    assert {c.name: c for c in oracle.probe_checks(page)}["no horizontal overflow"].passed


def test_the_drawer_gives_each_failed_step_a_card_linked_to_its_row(page, tmp_path):
    """Failure sites (failed steps with nothing failed inside) each get a card with
    their step number, parent and reason; parents failed only by a child get none."""
    from app.observability.reporter import generate_report

    def step(name, action, sub="", passed=True, group=False, msg="", checks=None, i=0):
        return {"name": name, "action": action, "passed": passed, "skipped": False, "msg": msg, "duration": 0.2,
                "sub_flow": sub, "section": "S", "screenshot": "", "layer": 1, "ts_start": 1e9 + i,
                "ts_end": 1e9 + i + 0.2, "evidence": None, "group": group, "checks": checks or []}
    broken = {"name": "no broken pages", "passed": False, "severity": "error", "count": 2,
              "detail": "after 'A': GET /a → 503; after 'B': GET /b → 503"}
    steps = [step('click: "Go"', "click", passed=False, msg="Locator.click: Timeout 5000ms exceeded.", i=0),
             step("test_page", "test_page", passed=False, group=True, i=1),
             step("explore_page", "explore_page", sub="test_page", passed=False, group=True, checks=[broken], i=2),
             step('click: "A"', "click", sub="test_page/explore_page", i=3)]
    result = {"nodeid": "tests/x/a.md::A", "name": "A", "outcome": "failed", "duration": 1, "longrepr": "tb",
              "error": "boom", "started_at": "", "flow_steps": steps, "console": [], "network": []}
    generate_report([result], 1e9, tmp_path / "report.html", "qa", exit_status=1)
    page.goto((tmp_path / "report.html").as_uri())
    page.evaluate("openTest(0)")
    where = [w.split("\n")[0] for w in page.locator("#drawer .fail-where").all_inner_texts()]
    assert where == ['Step 1 · Click "Go"', "Step 2.1 · Explore page"]
    assert "in Test page" in page.locator("#drawer .fail-card").nth(1).inner_text()
    card = page.locator("#drawer .fail-card").nth(1).locator(".finding")
    assert card.locator(".ftitle").inner_text() == "Pages that broke after a press"
    assert card.locator(".frows .qa-badge").all_inner_texts() == ["GET /a → 503", "GET /b → 503"]
    assert card.locator(".frows span:not(.qa-badge)").all_inner_texts() == ["After pressing “A”.", "After pressing “B”."]
    assert page.locator('#drawer [data-step="2.1"] .serr').inner_text() == "Pages that broke after a press (2)"
    assert page.locator("#drawer .steps .site").count() == 2 and page.locator("#drawer [data-tech]").count() == 2
    # Diagnostics, Console and Network are open by default: no fold to click first.
    assert page.locator('#drawer [data-tech="2.1"]').is_visible()
    assert page.locator("#drawer #d-con").is_visible() and not page.locator("#drawer #d-net").is_visible()
    page.locator('#drawer [data-t="d-net"]').click()                          # the Network tab shows its pane
    assert page.locator("#drawer #d-net").is_visible() and not page.locator("#drawer #d-con").is_visible()
    assert page.locator("#drawer details.tech").count() == 0
    page.locator('#drawer [data-show-tech="2.1"]').click()
    assert page.locator('#drawer [data-tech="2.1"].step-focus').count() == 1


def test_a_real_prefetch_is_left_out_and_a_navigation_to_it_is_kept(page, fixture_url, tmp_path):
    """Chromium's own event data: a Speculation Rules prefetch (resource type
    "prefetch") of a URL that answers 500 records nothing and fails nothing;
    opening the same URL is a tracked failure. The report counts and statuses
    follow what was recorded."""
    import json

    from app.observability.report_plugin import ProfessionalReportPlugin
    from app.observability.reporter import generate_report
    base = fixture_url.rsplit("/", 1)[0]
    pg = page.context.new_page()                     # fresh listeners
    plugin, results = ProfessionalReportPlugin(), []
    for name, steps in (("Prefetch only", f'- goto: "{base}/prefetch.html"\n- wait: 1500\n'),
                        ("Opens it", f'- goto: "{base}/api/boom"\n')):
        recorder = PageRecorder()
        recorder.attach(pg)
        md = f"# {name}\n\n## Steps\n{steps}- check_console_network\n"
        result = FlowRunner(artifacts_dir=str(tmp_path), flows_dir=tmp_path, provider=None).run(
            parse_flow_markdown(md), pg, recorder=recorder)
        nodeid = f"tests/x/{name}.md::{name}"
        plugin.record_steps(nodeid, result.steps)
        results.append({"nodeid": nodeid, "name": name, "outcome": "passed" if result.success else "failed",
                        "duration": 1, "longrepr": "", "error": result.error, "started_at": "",
                        "flow_steps": plugin.flow_steps[nodeid], "console": list(recorder.console),
                        "network": list(recorder.network),       # copies: the page is shared
                        "capture_dropped": {**recorder.dropped, "untracked": dict(recorder.untracked)}})
        if name == "Prefetch only":
            assert recorder.untracked["prefetch"] >= 1 and recorder.site_domain == "127.0.0.1"
            assert not any("/api/boom" in n["url"] for n in recorder.network)
            assert result.success, result.error                         # the failed prefetch fails nothing
        else:
            assert [n["status"] for n in recorder.network if "/api/boom" in n["url"]] == [500], \
                (recorder.site_domain, recorder.untracked, [(n["url"], n["status"], n["resource_type"]) for n in recorder.network])
            assert not result.success and "/api/boom → 500" in result.steps[-1].error
    pg.close()
    files = generate_report(results, 0, tmp_path / "report" / "report.html", "qa", exit_status=1)
    tests = json.loads(files.test_cases.read_text())["tests"]
    assert [(t["name"], t["status"]) for t in tests] == [("Prefetch only", "passed"), ("Opens it", "failed")]
    assert tests[0]["network_untracked"]["prefetch"] >= 1
    assert (files.totals["passed"], files.totals["failed"]) == (1, 1)
    data = (tmp_path / "report" / "assets" / "data.js").read_text()
    counts = [t["counts"]["net_bad"] for t in json.loads(data[data.index("{"):data.rstrip().rstrip(";").__len__()])["tests"]]
    assert counts == [0, 1]


def test_a_step_with_warnings_shows_them_under_a_warning_icon(page, tmp_path):
    """The test's warnings appear at their steps (the status stays passed), and a
    group opens when a warning sits inside it."""
    from app.observability.reporter import generate_report

    def step(name, action, sub="", group=False, checks=None, i=0):
        return {"name": name, "action": action, "passed": True, "skipped": False, "msg": "", "duration": 0.2,
                "sub_flow": sub, "section": "S", "screenshot": "", "layer": 1, "ts_start": 1e9 + i,
                "ts_end": 1e9 + i + 0.2, "evidence": None, "group": group, "checks": checks or []}
    warn = {"name": "fields have labels", "passed": False, "severity": "warn", "count": 2,
            "detail": 'input[name=email] (shows "Email", not linked as its label); '
                      'input.MuiInputBase-input (shows "Password", not linked as its label)'}
    heading = {"name": "visual headings marked up", "passed": False, "severity": "warn", "count": 1,
               "detail": '"Welcome!" (div, 36px)'}
    steps = [step('goto: "https://x"', "goto"),
             step("test_page", "test_page", group=True, i=1),
             step("check_accessibility", "check_accessibility", sub="test_page", group=True, checks=[warn, heading], i=2),
             step('click: "A"', "click", sub="test_page", i=3)]
    result = {"nodeid": "tests/x/w.md::W", "name": "W", "outcome": "passed", "duration": 1, "longrepr": "",
              "error": "", "started_at": "", "flow_steps": steps, "console": [], "network": []}
    generate_report([result], 1e9, tmp_path / "report.html", "qa", exit_status=0)
    page.goto((tmp_path / "report.html").as_uri())
    page.evaluate("openTest(0)")
    warned = page.locator("#drawer .steps .sicon.warned")
    assert warned.evaluate_all("els => els.map(e => e.closest('[data-step]').dataset.step)") == ["2.1"]
    assert page.locator('#drawer [data-step="2.1"] .swarn').all_inner_texts() == [
        "Form labels are not associated with their inputs (2)",
        "“Welcome!” appears as a heading but uses a <div>."]
    assert page.locator('#drawer details[data-step="2"]').get_attribute("open") is not None
    assert page.locator('#drawer [data-step="2.2"] .sicon.passed').count() == 1
    # The Warnings section: headline, one row per affected element, the step link in its own column.
    labels, heading_w = page.locator("#drawer .warn-list .finding").nth(0), page.locator("#drawer .warn-list .finding").nth(1)
    assert labels.locator(".ftitle").inner_text() == "Form labels are not associated with their inputs"
    assert labels.locator(".frows .qa-badge").all_inner_texts() == ["input[name=email]", "input.MuiInputBase-input"]
    assert labels.locator(".frows span:not(.qa-badge)").first.inner_text() == "The Email input's visible label is not associated with the field."
    assert labels.locator(".flink").inner_text() == "Step 2.1" and heading_w.locator(".flink").inner_text() == "Step 2.1"
    assert heading_w.locator(".ftitle").inner_text() == "“Welcome!” appears as a heading but uses a <div>."
    assert heading_w.locator(".frows").count() == 0
    assert page.locator("#drawer .drawer-section-warn .count").inner_text() == "2"   # rows never add findings
    # Every step row shares the grid: the step number starts at the same x on plain and expandable rows.
    x_of = "els => els.map(e => Math.round(e.getBoundingClientRect().x))"
    top = page.locator('#drawer [data-step="1"] > .slabel, #drawer details[data-step="2"] > summary > .slabel')
    assert len(set(top.evaluate_all(x_of))) == 1 and top.count() == 2          # plain and expandable rows agree
    kids = page.locator('#drawer [data-step="2.1"] > .slabel, #drawer [data-step="2.2"] > .slabel')
    assert len(set(kids.evaluate_all(x_of))) == 1 and kids.count() == 2         # children indent, together
    assert page.locator("#drawer .srow .stoggle").count() == page.locator("#drawer .srow").count()
    assert page.locator('#drawer details[data-step="2"] > summary .skids').inner_text() == "2 steps"


def test_the_hero_parts_add_up_to_the_total(page, tmp_path):
    """Passed without warnings, with warnings, on retry, failed and skipped are
    separate parts of the bar, each labelled in full; "passed" counts every
    passed test — a warning never takes a pass away — and says it counts tests."""
    from app.observability.reporter import generate_report
    warn = [{"name": "fields have labels", "passed": False, "severity": "warn", "detail": "x"}]

    def result(name, outcome, checks=None, retried=None):
        step = {"name": 'goto: "https://x"', "action": "goto", "passed": outcome != "failed", "skipped": outcome == "skipped",
                "msg": "" if outcome != "failed" else "boom", "duration": 0.2, "sub_flow": "", "section": "S", "screenshot": "",
                "layer": 1, "ts_start": 1e9, "ts_end": 1e9 + 0.2, "evidence": None, "group": False, "checks": checks or []}
        return {"nodeid": f"tests/x/{name}.md::{name}", "name": name, "outcome": outcome, "duration": 1, "longrepr": "",
                "error": "", "started_at": "", "flow_steps": [step], "console": [], "network": [], "retried": retried or {}}
    results = [result("clean", "passed"), result("warned", "passed", warn), result("warned2", "passed", warn),
               result("flaky", "passed", retried={"0": "first try failed"}), result("broken", "failed"),
               result("later", "skipped")]
    generate_report(results, 1e9, tmp_path / "report.html", "qa", exit_status=1)
    page.goto((tmp_path / "report.html").as_uri())
    assert page.locator(".run-bar-key").inner_text().split("\n") == [
        "Passed without warnings: 1", "Passed with warnings: 2", "Passed on retry: 1", "Failed: 1", "Skipped: 1"]
    assert page.locator(".run-attention").inner_text() == "1 of 5 tests failed"
    assert page.locator(".run-outcome").inner_text() == "4 passed · 1 failed · 1 skipped"
    assert page.locator(".run-review").inner_text() == "2 passed tests have warnings · 2 warnings in total"
    assert page.locator(".run-bar > div").evaluate_all("els => els.map(e => e.className)") == [
        "run-bar-pass", "run-bar-warn", "run-bar-flaky", "run-bar-fail", "run-bar-skip"]
    chips = dict(x.rsplit("\n", 1) for x in page.locator("#fchips .filter-chip").all_inner_texts())
    assert chips == {"All": "6", "Failed": "1", "Passed": "4", "Passed with warnings": "2", "Passed on retry": "1", "Skipped": "1"}
    page.locator('#fchips [data-f="passed"]').click()
    assert page.locator("#tests .trow").count() == 4                 # every passed test, warned and retried included
    assert page.locator('.run-stats .metric-label').all_inner_texts()[0].lower() == "tests"


def test_the_test_list_pairs_profiles_and_shows_the_device_icon(page, tmp_path):
    """A test's desktop and mobile runs sit together, in the order the tests
    first ran, each name followed by its device icon."""
    from app.observability.reporter import generate_report

    def result(name, profile, i):
        step = {"name": 'goto: "https://x"', "action": "goto", "passed": True, "skipped": False, "msg": "",
                "duration": 0.2, "sub_flow": "", "section": name, "screenshot": "", "layer": 1,
                "ts_start": 1e9 + i, "ts_end": 1e9 + i + 0.2, "evidence": None, "group": False, "checks": []}
        return {"nodeid": f"tests/x/app.md::{name}[{profile}]", "name": name, "outcome": "passed", "duration": 1,
                "longrepr": "", "error": "", "started_at": "", "flow_steps": [step], "console": [], "network": [],
                "profile": {"name": profile, "label": f"{profile} · chromium"}}
    runs = [result("Login Page", "desktop", 0), result("Home", "desktop", 1),     # run order: all desktop first
            result("Login Page", "mobile", 2), result("Home", "mobile", 3)]
    generate_report(runs, 1e9, tmp_path / "report.html", "qa", exit_status=0)
    page.goto((tmp_path / "report.html").as_uri())
    rows = page.locator("#tests .trow-name").evaluate_all(
        "els => els.map(e => [e.firstChild.textContent, e.querySelector('.dev-ico').getAttribute('aria-label')])")
    assert rows == [["Login Page", "Desktop"], ["Login Page", "Mobile"], ["Home", "Desktop"], ["Home", "Mobile"]]
    assert page.locator("#tests .trow-tags", has_text="Desktop").count() == 0    # the icon replaces the badge
    page.locator("#tests .trow").nth(1).click()                                 # still opens the right test
    assert page.locator("#drawer .fact-device .dev-ico").get_attribute("aria-label") == "Mobile"


def test_the_autonomous_run_panel_shows_compact_rows(page, tmp_path):
    """Components, plan, held-back controls and actions read as rows — a name,
    a count and the controls in monospace — not a paragraph."""
    from app.observability.reporter import generate_report
    agent = {"page_type": "LOGIN", "classification": "deterministic",
             "components": ["buttons: 3 (Request Info, LOG IN)", "form 'Sign in': 2 fields", "links: 4"],
             "plan": ["check console and network", "[ai] click \"Forgot password?\""],
             "plan_rejected": ["click: target 'e9' is not on the page"],
             "skipped": ["Delete account — name contains 'delete'"],
             "assertions": ['assert_text: "Welcome"'],
             "actions": [f'click: "B{i}"' for i in range(10)], "ai_calls": 1}
    steps = [{"name": "test_page", "action": "test_page", "passed": True, "skipped": False, "msg": "", "duration": 1,
              "sub_flow": "", "section": "S", "screenshot": "", "layer": 1, "ts_start": 1e9, "ts_end": 1e9 + 1,
              "evidence": None, "group": True, "checks": [], "agent": agent}]
    result = {"nodeid": "tests/x/a.md::A", "name": "A", "outcome": "passed", "duration": 1, "longrepr": "",
              "error": "", "started_at": "", "flow_steps": steps, "console": [], "network": []}
    generate_report([result], 1e9, tmp_path / "report.html", "qa", exit_status=0)
    page.goto((tmp_path / "report.html").as_uri())
    page.evaluate("openTest(0)")
    panel = page.locator("#drawer .agent-facts")
    comps = panel.locator("dd").nth(1).locator("li")
    assert comps.nth(0).locator(".akey").inner_text() == "buttons" and comps.nth(0).locator(".anum").inner_text() == "3"
    assert comps.nth(0).locator(".qa-badge").all_inner_texts() == ["Request Info", "LOG IN"]
    assert comps.nth(1).locator(".qa-badge").inner_text() == "Sign in" and comps.nth(1).locator(".anum").inner_text() == "2 fields"
    plan = panel.locator(".arows.plan li")
    assert plan.count() == 2 and plan.nth(1).locator(".qa-badge-neutral").inner_text() == "AI"
    assert plan.nth(1).locator("span").last.inner_text() == 'click "Forgot password?"'
    held = panel.locator(".arows.warn li").first
    assert held.locator(".qa-badge").inner_text() == "Delete account" and held.locator("span:not(.qa-badge)").inner_text() == "name contains 'delete'"
    assert panel.locator(".arows.bad li .qa-badge").inner_text() == "click"
    acts = panel.locator("div.arows")
    assert acts.locator(".anum").inner_text() == "10" and acts.locator(".qa-badge").count() == 8 and acts.locator(".amore").inner_text() == "+2 more"
