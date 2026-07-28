"""Unit tests for the Astra-schema report generator."""

from __future__ import annotations

import json
import time

import pytest

from app.observability.reporter import _build_steps, _build_test, generate_report


def make_step(label="click: \"Login\"", passed=True, skipped=False, msg="",
              duration=0.5, sub_flow="", section="", screenshot="", layer=1):
    return {
        "label": label, "name": label, "passed": passed, "skipped": skipped,
        "msg": msg, "duration": duration, "sub_flow": sub_flow,
        "section": section, "screenshot": screenshot, "layer": layer,
    }


def make_result(nodeid="flows/login/sso.md::SSO Login", outcome="passed",
                duration=2.5, longrepr="", error="", started_at="2026-07-28T10:00:00",
                screenshot=None, flow_steps=None, console=None, network=None):
    return {
        "nodeid": nodeid,
        "name": nodeid.split("::")[-1],
        "outcome": outcome,
        "duration": duration,
        "longrepr": longrepr,
        "error": error,
        "started_at": started_at,
        "screenshot": screenshot,
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
        screenshot="images/fail.png",
        flow_steps=[make_step(passed=False, msg="element not found")],
    )
    t = _build_test(r)
    assert t["status"] == "failed"
    assert t["error"]["message"] == "Flow 'SSO Login' failed — element not found"
    assert t["error"]["kind"] == "FlowError"
    assert t["error"]["traceback"] == "full traceback here"
    assert t["artifacts"]["screenshot"] == "images/fail.png"


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


# ── generate_report ──────────────────────────────────────────────────────────

def test_generate_report_writes_all_files(tmp_path):
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
    # report.json mirrors the payload
    assert json.loads((tmp_path / "report.json").read_text(encoding="utf-8")) == payload


def test_generate_report_html_references_assets(tmp_path):
    out = tmp_path / "report.html"
    generate_report([make_result()], time.time(), out, "qa1")
    html = out.read_text(encoding="utf-8")
    assert "assets/data.js" in html
    assert "assets/report.js" in html
    assert "assets/report.css" in html
    assert "Web Agent Test Report" in html
