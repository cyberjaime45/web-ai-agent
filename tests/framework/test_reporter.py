"""Unit tests for the Astra-schema report generator."""

from __future__ import annotations

import json
import time

import pytest

from app.observability.reporter import (
    _build_steps, _build_test, _build_tests, generate_report,
)


def make_step(label="click: \"Login\"", passed=True, skipped=False, msg="",
              duration=0.5, sub_flow="", section="", screenshot="", layer=1,
              ts_start=0.0, ts_end=0.0):
    return {
        "label": label, "name": label, "passed": passed, "skipped": skipped,
        "msg": msg, "duration": duration, "sub_flow": sub_flow,
        "section": section, "screenshot": screenshot, "layer": layer,
        "ts_start": ts_start, "ts_end": ts_end,
    }


def _json_report(report_dir):
    """The single report_<build>.json in *report_dir*."""
    (found,) = report_dir.glob("report_*.json")
    return found


def make_result(nodeid="flows/login/sso.md::SSO Login", outcome="passed",
                duration=2.5, longrepr="", error="", started_at="2026-07-28T10:00:00",
                flow_steps=None, console=None, network=None):
    return {
        "nodeid": nodeid,
        "name": nodeid.split("::")[-1],
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
    assert [t["id"] for t in tests] == [
        "flows/login/sso.md::s1", "flows/login/sso.md::s2", "flows/login/sso.md::s3",
    ]
    assert all(t["file"] == "flows/login/sso.md" for t in tests)
    assert all(t["flow"] == "SSO Login" for t in tests)
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
    generate_report([r], time.time() - 5, out, "staging")
    payload = json.loads(_json_report(tmp_path).read_text(encoding="utf-8"))
    assert payload["totals"]["total"] == 3
    assert payload["totals"]["passed"] == 2
    assert payload["totals"]["failed"] == 1


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
    assert _json_report(tmp_path).name == "report_web_test_report.json"
    # the JSON report mirrors the payload, plus the full inline detail arrays
    full = json.loads(_json_report(tmp_path).read_text(encoding="utf-8"))
    assert full["totals"] == payload["totals"]
    assert [t["id"] for t in full["tests"]] == [t["id"] for t in payload["tests"]]


def test_json_report_is_named_for_the_build_and_replaces_stale_ones(tmp_path, monkeypatch):
    out = tmp_path / "report.html"
    (tmp_path / "report.json").write_text("{}")              # legacy unsuffixed name
    monkeypatch.setenv("BUILD_NAME", "Release 4.2 Smoke")
    assert generate_report([make_result()], time.time(), out, "qa1").name == "report_release_4_2_smoke.json"
    monkeypatch.setenv("BUILD_NAME", "Nightly")
    path = generate_report([make_result()], time.time(), out, "qa1")
    assert path.name == "report_nightly.json"
    assert sorted(p.name for p in tmp_path.glob("report*.json")) == ["report_nightly.json"]
    assert json.loads(path.read_text(encoding="utf-8"))["environment"]["build_name"] == "Nightly"


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
        {"console": 1, "con_err": 1, "con_warn": 0, "network": 0, "net_bad": 0},
        {"console": 1, "con_err": 0, "con_warn": 1, "network": 0, "net_bad": 0},
        {"console": 0, "con_err": 0, "con_warn": 0, "network": 1, "net_bad": 0},
    ]
    # one JSONP-style shard per test, holding the routed events
    assert [c["text"] for c in _shard(tmp_path, 0)["console"]] == ["boom"]
    assert [c["text"] for c in _shard(tmp_path, 1)["console"]] == ["meh"]
    assert [n["url"] for n in _shard(tmp_path, 2)["network"]] == ["https://x/a"]
    # report.json keeps the inline arrays (machine mirror, CI compat)
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
        "console": 1, "con_err": 1, "con_warn": 0, "network": 2, "net_bad": 1,
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
    assert "assets/report.css" in html
    assert "Web Test Report" in html  # static fallback; BUILD_NAME overrides it at load time
