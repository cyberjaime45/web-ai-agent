"""Unit tests for the Astra-schema report generator."""

from __future__ import annotations

import json
import time
import xml.etree.ElementTree as ET

import pytest

from app.observability.report_model import _build_steps, _build_test
from app.observability.report_model import build_tests as _build_tests
from app.observability.reporter import generate_report


def make_step(label="click: \"Login\"", passed=True, skipped=False, msg="",
              duration=0.5, sub_flow="", section="", screenshot="", layer=1,
              ts_start=0.0, ts_end=0.0, action=None, evidence=None):
    return {
        "label": label, "name": label, "action": action, "passed": passed,
        "skipped": skipped, "msg": msg, "duration": duration, "sub_flow": sub_flow,
        "section": section, "screenshot": screenshot, "layer": layer,
        "ts_start": ts_start, "ts_end": ts_end, "evidence": evidence,
    }


def _json_report(report_dir):
    """test_cases.json in *report_dir*: the full per-test detail."""
    return report_dir / "test_cases.json"


def make_result(nodeid="flows/login/sso.md::SSO Login", outcome="passed",
                duration=2.5, longrepr="", error="", started_at="2026-07-28T10:00:00",
                flow_steps=None, console=None, network=None, flow_title=None,
                flow_markers=None, section_markers=None, flow_expected=None):
    return {
        "nodeid": nodeid,
        "name": nodeid.split("::")[-1],
        "flow_title": flow_title,
        "flow_markers": flow_markers or [],
        "section_markers": section_markers or {},
        "flow_expected": flow_expected or [],
        "outcome": outcome,
        "duration": duration,
        "longrepr": longrepr,
        "error": error,
        "started_at": started_at,
        "flow_steps": flow_steps if flow_steps is not None else [],
        "console": console or [],
        "network": network or [],
    }


# ── _build_steps ─────────────────────────────────────────────────────────────

def test_flat_steps_no_sections():
    steps = _build_steps([make_step(section=""), make_step(section="")], "2026-07-28T10:00:00")
    assert [s["depth"] for s in steps] == [0, 0]
    assert steps[0]["status"] == "passed"


def test_single_default_section_not_grouped():
    steps = _build_steps([make_step(section="Steps"), make_step(section="Steps")], "t")
    assert [s["depth"] for s in steps] == [0, 0]


def test_multiple_sections_become_groups():
    raw = [
        make_step(label="a", section="Setup"),
        make_step(label="b", section="Setup"),
        make_step(label="c", section="Checkout", passed=False, msg="boom"),
    ]
    steps = _build_steps(raw, "t")
    names = [(s["name"], s["depth"], s["status"]) for s in steps]
    assert names == [
        ("Setup", 0, "passed"),
        ("a", 1, "passed"),
        ("b", 1, "passed"),
        ("Checkout", 0, "failed"),
        ("c", 1, "failed"),
    ]
    # group duration = sum of children
    assert steps[0]["duration_ms"] == pytest.approx(1000.0)
    # failed leaf carries the error message
    assert steps[4]["error"] == "boom"


def test_all_skipped_section_is_skipped_group():
    raw = [
        make_step(label="a", section="One"),
        make_step(label="b", section="Two", passed=False, skipped=True),
        make_step(label="c", section="Two", passed=False, skipped=True),
    ]
    steps = _build_steps(raw, "t")
    group = [s for s in steps if s["name"] == "Two"][0]
    assert group["status"] == "skipped"


def test_sub_flow_marker_becomes_group():
    raw = [
        make_step(label='run_flow: "Login"', duration=0.0),
        make_step(label="fill user", sub_flow="Login"),
        make_step(label="fill pass", sub_flow="Login", passed=False, msg="nope"),
        make_step(label="assert dashboard"),
    ]
    steps = _build_steps(raw, "t")
    names = [(s["name"], s["depth"], s["status"]) for s in steps]
    assert names == [
        ('run_flow: "Login"', 0, "failed"),
        ("fill user", 1, "passed"),
        ("fill pass", 1, "failed"),
        ("assert dashboard", 0, "passed"),
    ]
    # group duration aggregates its children
    assert steps[0]["duration_ms"] == pytest.approx(1000.0)


def test_sub_flow_inside_section():
    raw = [
        make_step(label="a", section="Setup"),
        make_step(label="x", section="Setup", sub_flow="Login"),
        make_step(label="b", section="Other"),
    ]
    steps = _build_steps(raw, "t")
    names = [(s["name"], s["depth"]) for s in steps]
    assert names == [
        ("Setup", 0),
        ("a", 1),
        ("run_flow: Login", 1),
        ("x", 2),
        ("Other", 0),
        ("b", 1),
    ]


def test_step_screenshot_is_attachment():
    steps = _build_steps([make_step(screenshot="images/shot.png")], "t")
    assert steps[0]["attachment"] == "images/shot.png"


# ── _build_test ──────────────────────────────────────────────────────────────

def test_build_test_basic_fields():
    t = _build_test(make_result())
    assert t["id"] == "flows/login/sso.md::SSO Login"
    assert t["file"] == "flows/login/sso.md"
    assert t["title"] == "SSO Login"
    assert t["status"] == "passed"
    assert t["duration_ms"] == pytest.approx(2500.0)
    assert t["retries"] == 0
    assert t["markers"] == []
    assert t["file_title"] is None
    assert "error" not in t


def test_build_test_failure_error_info():
    r = make_result(
        outcome="failed",
        error="Flow 'SSO Login' failed — element not found",
        longrepr="full traceback here",
        flow_steps=[make_step(passed=False, msg="element not found",
                              screenshot="images/fail.png")],
    )
    t = _build_test(r)
    assert t["status"] == "failed"
    assert t["error"]["message"] == "Flow 'SSO Login' failed — element not found"
    assert t["error"]["kind"] == "FlowError"
    assert t["error"]["traceback"] == "full traceback here"
    # failure screenshot comes from the failing step — the single source
    assert t["artifacts"]["screenshot"] == "images/fail.png"


def test_skipped_steps_never_carry_screenshots():
    steps = [
        make_step(label="goto", section="One", ts_start=BASE, ts_end=BASE + 1),
        make_step(label="boom", section="One", passed=False, msg="fail",
                  screenshot="images/failed_step.png",
                  ts_start=BASE + 1, ts_end=BASE + 2),
        make_step(label="after", section="One", passed=False, skipped=True,
                  screenshot="images/stray.png"),   # must be ignored
        make_step(label="next", section="Two", ts_start=BASE + 2, ts_end=BASE + 3),
    ]
    tests = _build_tests(make_result(outcome="failed", flow_steps=steps))
    failed_test = tests[0]
    assert failed_test["artifacts"]["screenshot"] == "images/failed_step.png"
    skipped_leaf = [s for s in failed_test["steps"] if s["status"] == "skipped"][0]
    assert "attachment" not in skipped_leaf
    # the failure screenshot is the failed step's, never the skipped step's
    failed_leaf = [s for s in failed_test["steps"] if s["status"] == "failed"][0]
    assert failed_leaf["attachment"] == "images/failed_step.png"


def test_build_test_healings_from_layers():
    r = make_result(flow_steps=[
        make_step(label="click a", layer=1),
        make_step(label="click b", layer=2),
        make_step(label="click c", layer=3),
    ])
    t = _build_test(r)
    assert len(t["healings"]) == 2
    assert t["healings"][0]["layer"] == 2
    assert t["healings"][0]["description"] == "click b"
    assert t["healings"][1]["healed_by"] == "L3 (AI)"


def test_build_test_console_network_passthrough():
    r = make_result(
        console=[{"level": "error", "text": "boom", "location": None}],
        network=[{"method": "GET", "url": "https://x.test/", "status": 200,
                  "ok": True, "failure": None, "resource_type": "document", "body": None}],
    )
    t = _build_test(r)
    assert t["console"][0]["text"] == "boom"
    assert t["network"][0]["status"] == 200


# ── _build_tests: section splitting ─────────────────────────────────────────

BASE = 1_700_000_000.0  # epoch seconds


def sectioned_steps():
    return [
        make_step(label="goto a", section="Login Page", ts_start=BASE, ts_end=BASE + 1),
        make_step(label="assert a", section="Login Page", ts_start=BASE + 1, ts_end=BASE + 2),
        make_step(label="goto b", section="Home Page", passed=False, msg="nope",
                  screenshot="images/f.png", ts_start=BASE + 2, ts_end=BASE + 4),
        make_step(label="assert b", section="Home Page", passed=False, skipped=True),
        make_step(label="goto c", section="Leads Page", ts_start=BASE + 4, ts_end=BASE + 5),
    ]


def test_split_produces_one_test_per_section():
    r = make_result(outcome="failed", error="boom", longrepr="tb",
                    flow_steps=sectioned_steps())
    tests = _build_tests(r)
    assert [(t["name"], t["status"]) for t in tests] == [
        ("Login Page", "passed"), ("Home Page", "failed"), ("Leads Page", "passed"),
    ]
    assert [t["id"] for t in tests] == [    # the pytest node id, so each device profile has its own
        "flows/login/sso.md::SSO Login::s1", "flows/login/sso.md::SSO Login::s2", "flows/login/sso.md::SSO Login::s3",
    ]
    assert all(t["file"] == "flows/login/sso.md" for t in tests)
    assert all(t["file_title"] is None for t in tests)   # no # H1 → UI shows the path
    assert "flow" not in tests[0]
    # steps are depth-0 within their section (no redundant section group)
    assert [s["depth"] for s in tests[0]["steps"]] == [0, 0]
    # failing section carries its own error + failed-step screenshot
    assert tests[1]["error"]["message"] == "nope"
    assert tests[1]["error"]["traceback"] == "tb"
    assert tests[1]["artifacts"]["screenshot"] == "images/f.png"
    assert "error" not in tests[0]
    # timing window per section
    assert tests[0]["t0"] == round(BASE * 1000)
    assert tests[0]["duration_ms"] == pytest.approx(2000.0)


def test_retried_sections_carry_the_first_attempts_verdict():
    r = make_result(flow_steps=sectioned([("One", 'goto: "/"'), ("Two", 'goto: "/"')]))
    r["retried"], r["retried_verdicts"] = {"1": "Two failed"}, {"1": "application"}
    one, two = _build_tests(r)
    assert "retry_verdict" not in one and (two["retry_error"], two["retry_verdict"]) == ("Two failed", "application")
    single = make_result(flow_steps=sectioned([("Steps", 'goto: "/"')]))
    single["retried"] = {"0": "boom"}
    assert _build_tests(single)[0]["retry_verdict"] == ""


def test_retried_sections_carry_retries_and_the_first_error():
    r = make_result(outcome="failed", flow_steps=sectioned_steps())
    r["retried"] = {"0": "first try: timeout", "1": "first try: nope"}
    login, home, leads = _build_tests(r)
    assert (login["retries"], login["retry_error"]) == (1, "first try: timeout")   # passed on retry
    assert (home["retries"], home["status"]) == (1, "failed")                     # failed again
    assert leads["retries"] == 0 and "retry_error" not in leads


def test_single_test_retried():
    r = make_result(flow_steps=[make_step(section="Steps", ts_start=BASE, ts_end=BASE + 1)])
    r["retried"] = {"0": "first try failed"}
    (test,) = _build_tests(r)
    assert test["retries"] == 1 and test["retry_error"] == "first try failed"


def test_no_split_for_single_section():
    r = make_result(flow_steps=[make_step(section="Steps", ts_start=BASE, ts_end=BASE + 1)])
    tests = _build_tests(r)
    assert len(tests) == 1 and tests[0]["name"] == "SSO Login"


def test_no_split_without_step_timestamps():
    r = make_result(flow_steps=[
        make_step(section="One"), make_step(section="Two"),
    ])
    tests = _build_tests(r)
    assert len(tests) == 1   # old data → flow-level fallback


def test_all_skipped_section_becomes_skipped_test():
    steps = sectioned_steps()
    steps[4] = make_step(label="goto c", section="Leads Page",
                         passed=False, skipped=True)
    tests = _build_tests(make_result(outcome="failed", flow_steps=steps))
    assert tests[2]["status"] == "skipped"
    assert tests[2]["duration_ms"] == 0.0


def test_events_routed_by_start_time():
    console = [
        {"level": "error", "text": "early", "location": None,
         "ts": round((BASE - 5) * 1000), "seq": 1},          # before first → s1
        {"level": "error", "text": "home", "location": None,
         "ts": round((BASE + 2.5) * 1000), "seq": 2},        # inside Home window
        {"level": "warning", "text": "late", "location": None,
         "ts": round((BASE + 99) * 1000), "seq": 3},         # after last → s3
    ]
    network = [
        {"method": "GET", "url": "https://x.test/a", "status": 200, "ok": True,
         "failure": None, "resource_type": "xhr",
         "ts": round((BASE + 0.5) * 1000), "duration_ms": 40.0,
         "size": 10, "body": None, "seq": 4},
    ]
    r = make_result(outcome="failed", flow_steps=sectioned_steps(),
                    console=console, network=network)
    tests = _build_tests(r)
    assert [c["text"] for c in tests[0]["console"]] == ["early"]
    assert [c["text"] for c in tests[1]["console"]] == ["home"]
    assert [c["text"] for c in tests[2]["console"]] == ["late"]
    assert [n["url"] for n in tests[0]["network"]] == ["https://x.test/a"]
    # step attribution: the xhr started during "goto a"
    assert tests[0]["network"][0]["step"] == "goto a"
    assert tests[1]["console"][0]["step"] == "goto b"


def test_duplicate_section_names_split_with_distinct_ids():
    # ## Page / ## Other / ## Page — same name twice, non-adjacent
    steps = [
        make_step(label="a", section="Page", ts_start=BASE, ts_end=BASE + 1),
        make_step(label="b", section="Other", ts_start=BASE + 1, ts_end=BASE + 2),
        make_step(label="c", section="Page", ts_start=BASE + 2, ts_end=BASE + 3),
    ]
    tests = _build_tests(make_result(flow_steps=steps))
    assert [t["name"] for t in tests] == ["Page", "Other", "Page"]
    assert [t["id"][-4:] for t in tests] == ["::s1", "::s2", "::s3"]


def test_dropped_counters_attach_to_last_test():
    r = make_result(outcome="failed", flow_steps=sectioned_steps())
    r["capture_dropped"] = {"console": 7, "network": 9}
    tests = _build_tests(r)
    assert "console_dropped" not in tests[0]
    assert tests[-1]["console_dropped"] == 7 and tests[-1]["network_dropped"] == 9


def test_single_test_path_gets_t0_and_step_attribution():
    r = make_result(flow_steps=[make_step(ts_start=BASE, ts_end=BASE + 1)],
                    console=[{"level": "error", "text": "x", "location": None,
                              "ts": round((BASE + 0.2) * 1000), "seq": 1}])
    t = _build_tests(r)[0]
    assert t["t0"] == round(BASE * 1000)
    assert t["console"][0]["step"] == 'click: "Login"'


def test_generate_report_counts_section_tests(tmp_path):
    out = tmp_path / "report.html"
    r = make_result(outcome="failed", error="boom", longrepr="tb",
                    flow_steps=sectioned_steps())
    files = generate_report([r], time.time() - 5, out, "staging")
    payload = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert payload["totals"]["total"] == 3
    assert payload["totals"]["passed"] == 2
    assert payload["totals"]["failed"] == 1
    assert files.totals == payload["totals"]   # what the console summary prints


def test_junit_has_one_testcase_per_report_test(tmp_path):
    """CI sees the sections as test cases: a flow with one failed section is
    2 passed + 1 failed, not one failed test — the same counts as summary.json."""
    flow = make_result(outcome="failed", error="boom", longrepr="tb",
                       flow_steps=sectioned_steps(), flow_title="SSO")
    py = make_result(nodeid="tests/x.py::test_a")
    skip = make_result(nodeid="tests/x.py::test_b", outcome="skipped")
    files = generate_report([flow, py, skip], time.time(), tmp_path / "report.html", "qa1")
    root = ET.parse(files.junit).getroot()
    assert (root.get("tests"), root.get("failures"), root.get("errors"), root.get("skipped")) == (
        "5", "1", "0", "1")
    totals = files.totals
    assert (totals["total"], totals["passed"], totals["failed"], totals["skipped"]) == (5, 3, 1, 1)
    suites = root.findall("testsuite")
    assert [(s.get("name"), s.get("tests"), s.get("failures")) for s in suites] == [
        ("SSO", "3", "1"), ("tests/x.py", "2", "0")]
    cases = suites[0].findall("testcase")
    assert [c.get("name") for c in cases] == ["Login Page", "Home Page", "Leads Page"]
    assert cases[0].get("classname") == "flows/login/sso.md"
    failure = cases[1].find("failure")
    assert failure.get("message") == "nope" and failure.text == "tb"
    assert suites[1].findall("testcase")[1].find("skipped") is not None


# ── generate_report ──────────────────────────────────────────────────────────

def test_generate_report_writes_all_files(tmp_path, monkeypatch):
    monkeypatch.delenv("BUILD_NAME", raising=False)  # payload must carry the fallback
    out = tmp_path / "report.html"
    results = [
        make_result(),
        make_result(nodeid="flows/nav/main.md::Nav", outcome="failed",
                    error="boom", longrepr="tb"),
        make_result(nodeid="flows/nav/skip.md::Skip", outcome="skipped"),
    ]
    generate_report(results, session_start=time.time() - 10,
                    output_path=out, environment="staging")

    assert out.exists()
    assert (tmp_path / "assets" / "report.css").exists()
    assert (tmp_path / "assets" / "report.js").exists()
    assert (tmp_path / "assets" / "report-detail.js").exists()
    assert (tmp_path / "assets" / "report-logs.js").exists()
    html = out.read_text(encoding="utf-8")
    assert html.index("report.js") < html.index("report-logs.js") < html.index("report-detail.js")   # load order
    assert (tmp_path / "assets" / "nunito.woff2").read_bytes()[:4] == b"wOF2"          # bundled font, no network
    data_js = (tmp_path / "assets" / "data.js").read_text(encoding="utf-8")
    assert data_js.startswith("window.__WEBAGENT_DATA__ = {")
    payload = json.loads(data_js[len("window.__WEBAGENT_DATA__ = "):].rstrip().rstrip(";"))
    assert payload["tool"] == "web-agent"
    assert payload["totals"]["total"] == 3
    assert payload["totals"]["passed"] == 1
    assert payload["totals"]["failed"] == 1
    assert payload["totals"]["skipped"] == 1
    # pass rate excludes skipped: 1 passed of 2 executed
    assert payload["totals"]["pass_rate"] == 50.0
    assert payload["environment"]["env"] == "staging"
    assert payload["environment"]["build_name"] == "Web Test Report"
    # summary.json = run meta + totals; test_cases.json = the tests, full detail inline
    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert summary == {k: v for k, v in payload.items() if k != "tests"}
    full = json.loads(_json_report(tmp_path).read_text(encoding="utf-8"))
    assert full["run_id"] == summary["run_id"]
    assert [t["id"] for t in full["tests"]] == [t["id"] for t in payload["tests"]]


def test_json_files_have_fixed_names_and_summary_counts_the_test_cases(tmp_path, monkeypatch):
    monkeypatch.setenv("BUILD_NAME", "Release 4.2 Smoke")
    out = tmp_path / "report.html"
    results = [make_result(), make_result(nodeid="flows/b.md::B", outcome="failed", error="x"),
               make_result(nodeid="flows/c.md::C", outcome="skipped")]
    files = generate_report(results, time.time() - 2, out, "qa1")
    summary_path, cases_path = files.summary, files.test_cases
    assert (summary_path.name, cases_path.name) == ("summary.json", "test_cases.json")
    assert sorted(p.name for p in tmp_path.glob("*.json")) == ["summary.json", "test_cases.json"]
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    tests = json.loads(cases_path.read_text(encoding="utf-8"))["tests"]
    assert "tests" not in summary
    assert summary["environment"]["build_name"] == "Release 4.2 Smoke"
    statuses = [t["status"] for t in tests]
    totals = summary["totals"]
    assert totals["total"] == len(tests) == 3
    assert [totals[k] for k in ("passed", "failed", "skipped", "errors")] == [
        statuses.count(s) for s in ("passed", "failed", "skipped", "error")]
    assert totals["pass_rate"] == 50.0 and totals["duration_ms"] >= 2000


def _slim_payload(tmp_path):
    data_js = (tmp_path / "assets" / "data.js").read_text(encoding="utf-8")
    return json.loads(data_js[len("window.__WEBAGENT_DATA__ = "):].rstrip().rstrip(";"))


def _shard(tmp_path, i):
    raw = (tmp_path / "assets" / "data" / f"t-{i}.js").read_text(encoding="utf-8")
    prefix = f"window.__WEBAGENT_DETAIL__({i}, "
    assert raw.startswith(prefix)
    return json.loads(raw[len(prefix):].rstrip().rstrip(";").rstrip(")"))


def test_generate_report_shards_detail_per_test(tmp_path):
    console = [
        {"level": "error", "text": "boom", "ts": round((BASE + 0.5) * 1000), "seq": 1},
        {"level": "warning", "text": "meh", "ts": round((BASE + 2.5) * 1000), "seq": 2},
    ]
    network = [{"method": "GET", "url": "https://x/a", "status": 200, "ok": True,
                "ts": round((BASE + 4.2) * 1000), "seq": 3}]
    r = make_result(outcome="failed", error="boom", longrepr="tb",
                    flow_steps=sectioned_steps(), console=console, network=network)
    generate_report([r], time.time() - 5, tmp_path / "report.html", "staging")

    slim = _slim_payload(tmp_path)
    # detail arrays never ship in the upfront payload — counts replace them
    assert all("console" not in t and "network" not in t for t in slim["tests"])
    assert [t["counts"] for t in slim["tests"]] == [
        {"console": 1, "con_err": 1, "con_warn": 0, "network": 0, "net_bad": 0, "checks": 0, "warnings": 0},
        {"console": 1, "con_err": 0, "con_warn": 1, "network": 0, "net_bad": 0, "checks": 0, "warnings": 0},
        {"console": 0, "con_err": 0, "con_warn": 0, "network": 1, "net_bad": 0, "checks": 0, "warnings": 0},
    ]
    # one JSONP-style shard per test, holding the routed events
    assert [c["text"] for c in _shard(tmp_path, 0)["console"]] == ["boom"]
    assert [c["text"] for c in _shard(tmp_path, 1)["console"]] == ["meh"]
    assert [n["url"] for n in _shard(tmp_path, 2)["network"]] == ["https://x/a"]
    # test_cases.json keeps the inline arrays (machine mirror, CI compat)
    full = json.loads(_json_report(tmp_path).read_text(encoding="utf-8"))
    assert [len(t["console"]) for t in full["tests"]] == [1, 1, 0]
    assert [len(t["network"]) for t in full["tests"]] == [0, 0, 1]


def test_generate_report_counts_pageerror_and_failed_requests(tmp_path):
    r = make_result(
        console=[{"level": "pageerror", "text": "TypeError"}],
        network=[{"method": "GET", "url": "https://x/bad", "ok": False},
                 {"method": "GET", "url": "https://x/ok", "ok": True}],
    )
    generate_report([r], time.time(), tmp_path / "report.html", "staging")
    assert _slim_payload(tmp_path)["tests"][0]["counts"] == {
        "console": 1, "con_err": 1, "con_warn": 0, "network": 2, "net_bad": 1, "checks": 0, "warnings": 0,
    }


def test_generate_report_removes_stale_shards(tmp_path):
    stale = tmp_path / "assets" / "data" / "t-7.js"
    stale.parent.mkdir(parents=True)
    stale.write_text("window.__WEBAGENT_DETAIL__(7, {});", encoding="utf-8")
    generate_report([make_result()], time.time(), tmp_path / "report.html", "staging")
    assert not stale.exists()
    assert (tmp_path / "assets" / "data" / "t-0.js").exists()


def test_generate_report_html_references_assets(tmp_path):
    out = tmp_path / "report.html"
    generate_report([make_result()], time.time(), out, "qa1")
    html = out.read_text(encoding="utf-8")
    assert "assets/data.js" in html
    assert "assets/report.js" in html
    assert "assets/report-detail.js" in html
    assert "assets/report.css" in html
    assert "logo.png" not in html
    assert "Web Test Report" in html  # static fallback; BUILD_NAME overrides it at load time


def test_generate_report_does_not_mutate_results_and_is_idempotent(tmp_path):
    shot = tmp_path / "images" / "fail.png"
    shot.parent.mkdir(parents=True)
    shot.write_bytes(b"png")
    step = make_step(label="click: \"x\"", passed=False, msg="boom", screenshot=str(shot))
    results = [make_result(outcome="failed", error="boom", flow_steps=[step])]
    out = tmp_path / "report.html"
    generate_report(results, time.time(), out, "qa1")
    assert step["screenshot"] == str(shot)          # caller's data untouched
    generate_report(results, time.time(), out, "qa1")
    payload = json.loads(_json_report(tmp_path).read_text(encoding="utf-8"))
    assert payload["tests"][0]["steps"][0]["attachment"] == "images/fail.png"


def test_attribute_steps_uses_step_windows():
    from app.observability.report_model import _attribute_steps
    steps = [
        {"name": "a", "ts_start": 10.0, "ts_end": 10.5},
        {"name": "b", "ts_start": 10.5, "ts_end": 11.0},
        {"name": "c", "ts_start": 11.0, "ts_end": 11.5},
    ]
    entries = [{"ts": 10_200}, {"ts": 10_900}, {"ts": 11_400}, {"ts": 20_000}, {"ts": None}]
    _attribute_steps(entries, steps)
    assert [e.get("step") for e in entries] == ["a", "b", "c", None, None]


# ── suite title, markers, and step detail ────────────────────────────────────

def sectioned(title_steps):
    """[(section, label)] → timestamped steps so the flow splits per section."""
    return [make_step(label=label, section=sec, ts_start=BASE + i, ts_end=BASE + i + 1)
            for i, (sec, label) in enumerate(title_steps)]


def test_split_tests_carry_the_file_title_and_their_own_markers():
    r = make_result(
        nodeid="tests/marketing_site/flows/sample_run.md::Home Page",
        flow_title="Home Page", flow_markers=["site"],
        section_markers={"Test One": ["smoke"], "Test Two": ["another_tag"]},
        flow_steps=sectioned([("Test One", 'goto: "/"'), ("Test Two", 'goto: "/"')]),
    )
    tests = _build_tests(r)
    assert [(t["title"], t["file_title"], t["markers"]) for t in tests] == [
        ("Test One", "Home Page", ["site", "smoke"]),
        ("Test Two", "Home Page", ["site", "another_tag"]),
    ]
    assert all(t["file"] == "tests/marketing_site/flows/sample_run.md" for t in tests)


def test_single_named_section_becomes_the_test_and_the_h1_the_suite():
    r = make_result(nodeid="flows/login.md::Login", flow_title="Login",
                    section_markers={"Valid Login": ["smoke"]},
                    flow_steps=sectioned([("Valid Login", 'goto: "/"')]))
    (t,) = _build_tests(r)
    assert (t["title"], t["file_title"], t["markers"]) == ("Valid Login", "Login", ["smoke"])
    assert t["id"] == "flows/login.md::Login"   # nodeid unchanged — one pytest item


def test_expected_outcome_reaches_every_test_of_the_file():
    r = make_result(flow_expected=["Profile saved"],
                    flow_steps=sectioned([("One", 'goto: "/"'), ("Two", 'goto: "/"')]))
    assert [t["expected"] for t in _build_tests(r)] == [["Profile saved"], ["Profile saved"]]
    (single,) = _build_tests(make_result(flow_steps=sectioned([("Steps", 'goto: "/"')])))
    assert single["expected"] == []


def test_generic_steps_section_keeps_the_flow_name_as_the_test_title():
    r = make_result(nodeid="flows/login.md::Login", flow_title="Login",
                    flow_markers=["smoke"],
                    flow_steps=sectioned([("Steps", 'goto: "/"')]))
    (t,) = _build_tests(r)
    assert (t["title"], t["file_title"], t["markers"]) == ("Login", "Login", ["smoke"])


def test_leaf_steps_expose_verb_argument_and_fallback_layer():
    steps = _build_steps([
        make_step(label='goto: "https://wheelsup.com/"', action="goto", layer=1),
        make_step(label="wait_load", action="wait_load", layer=1),
        make_step(label='click_link_text: "Accept All Cookies"', action="click_link_text", layer=2),
        make_step(label="legacy row", action=None),
        make_step(label='assert_text: "x"', action="assert_text", skipped=True, passed=False, layer=1),
    ], "t")
    assert (steps[0]["action"], steps[0]["args"]) == ("goto", '"https://wheelsup.com/"')
    assert (steps[1]["action"], steps[1]["args"]) == ("wait_load", "")
    assert steps[0]["layer"] == 1 and steps[2]["layer"] == 2   # UI chips only L2/L3
    assert "action" not in steps[3]
    assert "layer" not in steps[4]   # skipped steps never ran on any layer


# ── failure evidence + profiles ─────────────────────────────────────────────

def _evidence(**over):
    ev = {
        "url": "https://x.test/account", "title": "Account",
        "profile": "mobile · iPhone 13 · chromium · 390x664",
        "layers": {"L1 exact": "failed", "L2 fuzzy": "failed", "L3 AI": "skipped: provider not configured"},
        "screenshots": {"viewport": "/abs/images/f__viewport.png", "full_page": "/abs/images/f__full.png"},
        "trace": "/abs/traces/f__mobile.zip",
        "console": [{"level": "error", "text": "boom", "ts": 1, "seq": 1}],
        "network": [],
    }
    ev.update(over)
    return ev


def test_failed_leaf_carries_evidence_and_test_artifacts_list_every_shot():
    steps = [make_step(passed=False, msg="nope", screenshot="images/f__viewport.png",
                       evidence=_evidence(screenshots={"viewport": "images/f__viewport.png",
                                                       "element": "images/f__element.png"},
                                          trace="traces/f__mobile.zip"))]
    steps[0]["evidence"] = steps[0].pop("evidence")
    t = _build_test(make_result(outcome="failed", flow_steps=steps))
    leaf = t["steps"][0]
    assert leaf["evidence"]["layers"]["L3 AI"].startswith("skipped")
    assert leaf["attachment"] == "images/f__viewport.png"
    assert t["artifacts"] == {
        "screenshot": "images/f__viewport.png",
        "screenshots": [{"kind": "viewport", "path": "images/f__viewport.png"},
                        {"kind": "element", "path": "images/f__element.png"}],
        "trace": "traces/f__mobile.zip",
    }


def test_skipped_leaves_drop_evidence_and_artifacts_come_from_failures_only():
    steps = [make_step(evidence=_evidence()),                          # a skill's screenshots
             make_step(passed=False, skipped=True, evidence=_evidence())]
    t = _build_test(make_result(flow_steps=steps))
    assert "evidence" in t["steps"][0] and "evidence" not in t["steps"][1]
    assert t["artifacts"] == {"screenshot": None, "screenshots": [], "trace": None}


def test_profile_is_passed_through_to_each_test():
    profile = {"name": "mobile", "label": "mobile · iPhone 13 · chromium · 390x664"}
    r = make_result(flow_steps=sectioned_steps())
    r["profile"] = profile
    assert all(t["profile"] == profile for t in _build_tests(r))
    assert _build_test(make_result())["profile"] is None


def test_generate_report_makes_evidence_paths_relative(tmp_path):
    report_dir = tmp_path / "reports" / "staging"
    shot = report_dir / "images" / "f__viewport.png"
    full = report_dir / "images" / "f__full.png"
    trace = report_dir / "traces" / "f__desktop.zip"
    steps = [make_step(passed=False, msg="nope", screenshot=str(shot),
                       evidence=_evidence(screenshots={"viewport": str(shot), "full_page": str(full)},
                                          trace=str(trace)))]
    generate_report(results=[make_result(outcome="failed", flow_steps=steps)],
                    session_start=time.time(), output_path=report_dir / "report.html")
    payload = json.loads(_json_report(report_dir).read_text())
    test = payload["tests"][0]
    assert test["artifacts"]["trace"] == "traces/f__desktop.zip"
    assert test["steps"][0]["evidence"]["screenshots"] == {
        "viewport": "images/f__viewport.png", "full_page": "images/f__full.png"}
    # the caller's step dicts are untouched (a second generate_report still works)
    assert steps[0]["evidence"]["trace"] == str(trace)


# ── skill groups and checks ─────────────────────────────────────────────────

def test_skill_marker_becomes_a_group_with_its_checks():
    checks = [{"name": "empty submission rejected", "passed": False, "severity": "error", "detail": "posted"},
              {"name": "fields", "passed": True, "severity": "info", "detail": "2 fields"}]
    raw = [
        make_step(label='test_form: "submit=false"', action="test_form", passed=False, msg="test_form: 1 of 1 checks failed"),
        make_step(label='fill: "Email" | "x"', action="fill", sub_flow="test_form"),
        make_step(label='click: "Save"', action="click", sub_flow="test_form"),
        make_step(label='assert_text: "done"', action="assert_text"),
    ]
    raw[0]["checks"], raw[0]["group"] = checks, True
    steps = _build_steps(raw, "t")
    group = steps[0]
    assert group["depth"] == 0 and group["status"] == "failed"      # the skill's verdict, children passed
    assert group["action"] == "test_form" and group["args"] == '"submit=false"'
    assert group["checks"] == checks and group["error"] == "test_form: 1 of 1 checks failed"
    assert [(s["name"], s["depth"]) for s in steps[1:]] == [
        ('fill: "Email" | "x"', 1), ('click: "Save"', 1), ('assert_text: "done"', 0)]


def test_skill_without_children_is_a_leaf_with_checks():
    raw = [make_step(label="check_console_network", action="check_console_network")]
    raw[0]["checks"], raw[0]["group"] = [{"name": "no page errors", "passed": True, "severity": "error", "detail": ""}], True
    (leaf,) = _build_steps(raw, "t")
    assert leaf["depth"] == 0 and leaf["checks"][0]["name"] == "no page errors"


def test_skill_screenshots_ride_on_a_passed_group():
    raw = [make_step(label="test_responsive", action="test_responsive",
                     evidence={"screenshots": {"390x664": "/abs/images/r.png"}, "trace": None, "layers": {}}),
           make_step(label='click: "Open menu"', action="click", sub_flow="test_responsive")]
    raw[0]["group"] = True
    group = _build_steps(raw, "t")[0]
    assert group["status"] == "passed" and group["evidence"]["screenshots"] == {"390x664": "/abs/images/r.png"}


def test_check_counts_in_slim_payload(tmp_path):
    report_dir = tmp_path / "reports" / "staging"
    step = make_step(label='goto: "x"', action="goto")
    step["checks"] = [{"name": "page rendered", "passed": True, "severity": "error", "detail": ""},
                      {"name": "no console errors", "passed": False, "severity": "warn", "detail": "boom"},
                      {"name": "url", "passed": True, "severity": "info", "detail": "x"}]
    generate_report(results=[make_result(flow_steps=[step])], session_start=time.time(),
                    output_path=report_dir / "report.html")
    data = (report_dir / "assets" / "data.js").read_text()
    assert '"checks": 2' in data and '"warnings": 1' in data


def test_nested_skill_groups_two_levels_deep():
    raw = [
        make_step(label="test_page", action="test_page"),
        make_step(label="check_console_network", action="check_console_network", sub_flow="test_page"),
        make_step(label='test_form: "submit=false"', action="test_form", sub_flow="test_page"),
        make_step(label='fill: "Email" | "x"', action="fill", sub_flow="test_page/test_form"),
        make_step(label='click: "Save"', action="click", sub_flow="test_page/test_form"),
        make_step(label='goto: "https://x"', action="goto", sub_flow="test_page"),
        make_step(label='assert_text: "done"', action="assert_text"),
    ]
    raw[0]["group"] = raw[1]["group"] = raw[2]["group"] = True
    raw[0]["agent"] = {"page_type": "FORM", "plan": ["a"], "generated": "/abs/generated/f.md"}
    steps = _build_steps(raw, "t")
    assert [(s["name"], s["depth"]) for s in steps] == [
        ("test_page", 0), ("check_console_network", 1), ('test_form: "submit=false"', 1),
        ('fill: "Email" | "x"', 2), ('click: "Save"', 2), ('goto: "https://x"', 1), ('assert_text: "done"', 0)]
    assert steps[0]["agent"]["page_type"] == "FORM"
    t = _build_test(make_result(flow_steps=raw))
    assert t["agent"]["plan"] == ["a"]


def test_generate_report_relativizes_agent_and_evidence_files(tmp_path):
    report_dir = tmp_path / "reports" / "staging"
    gen = report_dir / "generated" / "f.md"
    step = make_step(label="test_page", action="test_page",
                     evidence={"screenshots": {}, "trace": None, "layers": {}, "files": {"generated flow": str(gen)}})
    step["group"], step["agent"] = True, {"page_type": "FORM", "generated": str(gen)}
    generate_report(results=[make_result(flow_steps=[step])], session_start=time.time(),
                    output_path=report_dir / "report.html")
    payload = json.loads(_json_report(report_dir).read_text())
    test = payload["tests"][0]
    assert test["agent"]["generated"] == "generated/f.md"
    assert test["steps"][0]["evidence"]["files"] == {"generated flow": "generated/f.md"}


# ── one result model: statuses, ids, warnings, totals, run status ───────────

def _skill_run(child_passed=True, soft=False, marker_checks=None, marker_passed=True):
    marker = make_step(label="test_widgets", action="test_widgets", passed=marker_passed, duration=4.0)
    marker.update(group=True, checks=marker_checks or [])
    child = make_step(label='click: "Tab B"', action="click", sub_flow="test_widgets",
                      passed=child_passed, msg="" if child_passed else "boom", duration=1.0)
    child["soft"] = soft
    return [marker, child, make_step(label='assert_text: "after"', action="assert_text")]


def test_a_soft_failure_passes_its_step_and_is_listed_as_a_warning():
    warn = {"name": "tabs select their panel", "passed": False, "severity": "warn",
            "detail": "could not press 'Tab B'"}
    (t,) = _build_tests(make_result(flow_steps=_skill_run(child_passed=False, soft=True, marker_checks=[warn])))
    group, child, after = t["steps"]
    assert (group["status"], child["status"], after["status"]) == ("passed", "passed", "passed")
    assert child["error"] == "boom"                      # the message is kept in the JSON
    assert t["status"] == "passed"
    assert t["warnings"] == [{"step": "1", "step_name": "test_widgets", "check": "tabs select their panel",
                              "detail": "could not press 'Tab B'", "severity": "warn"}]


def test_a_hard_child_failure_fails_the_group():
    (t,) = _build_tests(make_result(outcome="failed", flow_steps=_skill_run(child_passed=False, marker_passed=False)))
    assert [s["status"] for s in t["steps"]] == ["failed", "failed", "passed"]
    assert t["warnings"] == []


def test_steps_carry_stable_ids_and_parents():
    steps = _build_steps([
        make_step(label="goto a", section="Login"),
        *[dict(s, section="Login") for s in _skill_run()],
        make_step(label="goto b", section="Home"),
    ], "2026-07-28T10:00:00")
    assert [(s["id"], s["parent"], s["depth"]) for s in steps] == [
        ("1", None, 0), ("1.1", "1", 1), ("1.2", "1", 1), ("1.2.1", "1.2", 2), ("1.3", "1", 1),
        ("2", None, 0), ("2.1", "2", 1)]


def test_a_skill_group_takes_its_duration_from_the_skill():
    group = _build_steps(_skill_run(), "2026-07-28T10:00:00")[0]
    assert group["duration_ms"] == 4000.0              # not the 1 s its child took


def test_skipped_blocked_and_info_checks_are_not_warnings():
    checks = [{"name": "sorting works", "passed": True, "severity": "skipped", "detail": "no header"},
              {"name": "blocked by safety", "passed": True, "severity": "blocked", "detail": "Delete"},
              {"name": "table", "passed": True, "severity": "info", "detail": "3 rows"}]
    (t,) = _build_tests(make_result(flow_steps=_skill_run(marker_checks=checks)))
    assert t["steps"][0]["status"] == "passed" and t["warnings"] == []


def test_an_oracle_error_on_a_passing_step_is_a_test_warning():
    step = make_step(label='goto: "x"', action="goto")
    step["checks"] = [{"name": "no page errors", "passed": False, "severity": "error", "detail": "TypeError"}]
    (t,) = _build_tests(make_result(flow_steps=[step]))
    assert t["steps"][0]["status"] == "passed" and t["status"] == "passed"
    assert [w["check"] for w in t["warnings"]] == ["no page errors"]


def test_one_finding_on_several_steps_is_one_warning_with_each_step():
    steps = [make_step(label=f'goto: "{u}"', action="goto") for u in "abc"]
    for st in steps:
        st["checks"] = [{"name": "no horizontal overflow", "passed": False, "severity": "warn", "detail": "12px"}]
    (t,) = _build_tests(make_result(flow_steps=steps))
    (w,) = t["warnings"]
    assert (w["step"], w["also"]) == ("1", ["2", "3"])


def test_inconclusive_checks_are_not_verified_never_warnings(tmp_path):
    gap = {"name": "controls pressable", "passed": True, "severity": "inconclusive", "detail": "Logo (covered)"}
    result = make_result(flow_steps=_skill_run(marker_checks=[gap]))
    (t,) = _build_tests(result)
    assert t["warnings"] == [] and [u["check"] for u in t["unverified"]] == ["controls pressable"]
    _, summary = _totals(tmp_path, [result], exit_status=0)
    assert (summary["status"], summary["totals"]["warnings"], summary["totals"]["unverified"]) == ("passed", 0, 1)


def _totals(tmp_path, results, exit_status=None):
    files = generate_report(results, time.time(), tmp_path / "report.html", "qa1", exit_status=exit_status)
    summary = json.loads(files.summary.read_text(encoding="utf-8"))
    return files, summary


def test_totals_status_and_exit_code_agree(tmp_path):
    warn = {"name": "tabs select their panel", "passed": False, "severity": "warn", "detail": "x"}
    clean = make_result()
    warned = make_result(nodeid="flows/w.md::W", flow_steps=_skill_run(marker_checks=[warn]))
    failed = make_result(nodeid="flows/f.md::F", outcome="failed", error="boom")

    _, summary = _totals(tmp_path, [clean], exit_status=0)
    assert (summary["status"], summary["exit_code"], summary["totals"]["warnings"]) == ("passed", 0, 0)
    _, summary = _totals(tmp_path, [clean, warned], exit_status=0)
    assert (summary["status"], summary["exit_code"], summary["totals"]["warnings"]) == ("passed_with_warnings", 0, 1)
    assert summary["totals"]["passed"] == 2                       # a warning never takes a pass away
    files, summary = _totals(tmp_path, [clean, warned, failed], exit_status=1)
    assert (summary["status"], summary["exit_code"]) == ("failed", 1)
    assert (files.status, files.exit_code, files.totals) == (summary["status"], summary["exit_code"], summary["totals"])
    root = ET.parse(files.junit).getroot()
    assert (root.get("tests"), root.get("failures")) == ("3", "1")   # warnings pass in CI too


def test_an_interrupted_run_reports_what_finished(tmp_path):
    _, summary = _totals(tmp_path, [make_result()], exit_status=2)
    assert (summary["status"], summary["exit_code"], summary["totals"]["total"]) == ("interrupted", 2, 1)


def test_the_exit_code_follows_the_model_and_never_lowers_pytests():
    from app.observability.reporter import run_status
    ok = {"failed": 0, "errors": 0, "warnings": 0}
    assert run_status({**ok, "failed": 1}, 0) == ("failed", 1)   # the model saw a failure pytest missed
    assert run_status(ok, 4) == ("error", 4)                      # a usage error: the run broke, its code kept
    assert run_status({**ok, "failed": 1}, 3) == ("error", 3)     # an internal error is never "failed tests"
    assert run_status(ok, 1) == ("error", 1)                      # pytest failed something the model missed
    assert run_status({**ok, "errors": 1}, 1) == ("failed", 1)
    assert run_status({**ok, "warnings": 2}, None) == ("passed_with_warnings", 0)


def test_partial_execution_counts_each_section_once(tmp_path):
    steps = [
        make_step(label="goto a", section="Login", ts_start=BASE, ts_end=BASE + 1),
        make_step(label="assert a", section="Login", passed=False, msg="nope", ts_start=BASE + 1, ts_end=BASE + 2),
        make_step(label="assert a2", section="Login", passed=False, skipped=True),
        *[dict(s, section="Home", ts_start=BASE + 3 + i, ts_end=BASE + 3.5 + i) for i, s in enumerate(_skill_run())],
        make_step(label="goto c", section="Never", passed=False, skipped=True),
    ]
    files, summary = _totals(tmp_path, [make_result(outcome="failed", error="nope", flow_steps=steps)], exit_status=1)
    tests = json.loads(files.test_cases.read_text(encoding="utf-8"))["tests"]
    assert [(t["name"], t["status"]) for t in tests] == [("Login", "failed"), ("Home", "passed"), ("Never", "skipped")]
    assert summary["totals"] == {**summary["totals"], "total": 3, "passed": 1, "failed": 1, "skipped": 1}
    assert [s["id"] for s in tests[1]["steps"]] == ["1", "1.1", "2"]   # nested actions are steps, not tests


def test_a_test_that_is_one_section_is_not_wrapped_in_it():
    steps = [make_step(label="goto a", section="Login Test"), make_step(label="assert a", section="Login Test")]
    (t,) = _build_tests(make_result(flow_steps=steps))
    assert t["name"] == "Login Test"
    assert [(s["id"], s["name"], s["depth"]) for s in t["steps"]] == [("1", "goto a", 0), ("2", "assert a", 0)]


def test_cancelled_requests_are_not_counted_as_failed(tmp_path):
    net = [{"method": "POST", "url": "https://x/cdn-cgi/rum", "status": None, "ok": False, "failure": "net::ERR_ABORTED", "ts": 1},
           {"method": "GET", "url": "https://x/api", "status": 500, "ok": False, "failure": None, "ts": 2}]
    generate_report([make_result(network=net)], time.time(), tmp_path / "report.html", "qa")
    assert _slim_payload(tmp_path)["tests"][0]["counts"]["net_bad"] == 1


def test_a_failed_item_with_passing_sections_is_not_reported_green():
    steps = [make_step(label="a", section="One", ts_start=BASE, ts_end=BASE + 1),
             make_step(label="b", section="Two", ts_start=BASE + 1, ts_end=BASE + 2)]
    tests = _build_tests(make_result(outcome="failed", error="trace upload failed", longrepr="tb", flow_steps=steps))
    assert [t["status"] for t in tests] == ["passed", "failed"]
    assert tests[1]["error"]["message"] == "trace upload failed"


def test_each_profile_has_its_own_ids_and_junit_names(tmp_path):
    steps = [make_step(label="a", section="One", ts_start=BASE, ts_end=BASE + 1),
             make_step(label="b", section="Two", ts_start=BASE + 1, ts_end=BASE + 2)]
    runs = [dict(make_result(nodeid=f"flows/a.md::A[{p}]", flow_steps=steps), profile={"name": p, "label": p})
            for p in ("desktop", "mobile")]
    files = generate_report(runs, time.time(), tmp_path / "report.html", "qa", exit_status=0)
    tests = json.loads(files.test_cases.read_text())["tests"]
    assert len({t["id"] for t in tests}) == 4
    names = [c.get("name") for c in ET.parse(files.junit).getroot().iter("testcase")]
    assert names == ["One", "Two", "One [mobile]", "Two [mobile]"]


def test_setup_errors_skips_and_teardown_errors_reach_the_model():
    from types import SimpleNamespace

    from app.observability.report_plugin import ProfessionalReportPlugin
    plugin = ProfessionalReportPlugin()

    def report(nodeid, when, outcome):
        return SimpleNamespace(nodeid=nodeid, when=when, outcome=outcome, failed=outcome == "failed",
                               skipped=outcome == "skipped", passed=outcome == "passed",
                               duration=0.1, start=None, longrepr=f"{when} {outcome}")
    for r in [report("a.md::A", "setup", "failed"),                                  # setup error
              report("b.md::B", "setup", "skipped"),                                 # skip marker
              report("c.md::C", "setup", "passed"), report("c.md::C", "call", "passed"),
              report("c.md::C", "teardown", "failed")]:                              # teardown error
        plugin.pytest_runtest_logreport(r)
    assert [(r["nodeid"], r["outcome"]) for r in plugin.results] == [
        ("a.md::A", "error"), ("b.md::B", "skipped"), ("c.md::C", "error")]
    assert "teardown failed" in plugin.results[2]["longrepr"]


def test_junit_strips_characters_xml_cannot_hold(tmp_path):
    from xml.dom import minidom
    r = make_result(outcome="failed", error="\x1b[31mboom\x1b[0m\x00\x07 at step", longrepr="tb\x0b\x1f")
    files = generate_report([r], time.time(), tmp_path / "report.html", "qa", exit_status=1)
    failure = minidom.parse(str(files.junit)).getElementsByTagName("failure")[0]   # parses at all
    assert failure.getAttribute("message") == "boom at step"


def test_interrupted_matches_pytests_exit_code():
    import pytest

    from app.observability.reporter import INTERRUPTED
    assert INTERRUPTED == pytest.ExitCode.INTERRUPTED


def test_a_warned_test_that_passed_on_retry_counts_once(tmp_path):
    warn = {"name": "w", "passed": False, "severity": "warn", "detail": "x"}
    step = dict(make_step(label='goto: "x"', action="goto"), checks=[warn])
    r = dict(make_result(flow_steps=[step]), retried={"0": "first attempt failed"})
    files = generate_report([r], time.time(), tmp_path / "report.html", "qa", exit_status=0)
    assert (files.totals["warnings"], files.status) == (0, "passed")
