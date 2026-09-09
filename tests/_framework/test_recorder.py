"""Unit tests for PageRecorder v2 — timestamps, levels, redaction, caps."""

from __future__ import annotations

import json
import time
from types import SimpleNamespace

import pytest

from app.observability.recorder import (
    MAX_ERROR_CONSOLE, MAX_INFO_CONSOLE, MAX_NETWORK_ENTRIES, REDACTED,
    PageRecorder, redact_headers, redact_text, redact_url,
)


class FakePage:
    def __init__(self):
        self.handlers = {}

    def on(self, event, cb):
        self.handlers[event] = cb

    def emit(self, event, arg):
        self.handlers[event](arg)


def console_msg(type_="error", text="boom", url="https://x.test/app.js",
                line=10, col=5):
    return SimpleNamespace(
        type=type_, text=text,
        location={"url": url, "lineNumber": line, "columnNumber": col},
    )


def make_request(method="GET", url="https://x.test/api", resource_type="xhr",
                 headers=None, post_data=None, failure=None):
    return SimpleNamespace(method=method, url=url, resource_type=resource_type,
                           headers=headers or {}, post_data=post_data,
                           failure=failure)


def make_response(request, status=200, headers=None, body=""):
    return SimpleNamespace(request=request, status=status, url=request.url,
                           headers=headers or {}, text=lambda: body)


@pytest.fixture
def rec_page():
    rec, page = PageRecorder(), FakePage()
    rec.attach(page)
    return rec, page


# ── console ──────────────────────────────────────────────────────────────────

def test_console_all_levels_normalized(rec_page):
    rec, page = rec_page
    for t in ("error", "warning", "info", "log", "debug"):
        page.emit("console", console_msg(type_=t, text=t))
    levels = [c["level"] for c in rec.console]
    assert levels == ["error", "warning", "info", "info", "debug"]


def test_console_entry_has_ts_seq_and_full_location(rec_page):
    rec, page = rec_page
    before = round(time.time() * 1000)
    page.emit("console", console_msg())
    c = rec.console[0]
    assert c["ts"] >= before
    assert c["seq"] == 1
    assert c["location"] == "https://x.test/app.js:10:5"


def test_pageerror_recorded(rec_page):
    rec, page = rec_page
    page.emit("pageerror", Exception("TypeError: x is not a function"))
    assert rec.console[0]["level"] == "pageerror"


def test_console_caps_per_class_and_counts_dropped(rec_page):
    rec, page = rec_page
    for i in range(MAX_ERROR_CONSOLE + 3):
        page.emit("console", console_msg(type_="error", text=str(i)))
    for i in range(MAX_INFO_CONSOLE + 2):
        page.emit("console", console_msg(type_="info", text=str(i)))
    assert len(rec.console) == MAX_ERROR_CONSOLE + MAX_INFO_CONSOLE
    assert rec.dropped["console"] == 5


# ── network ──────────────────────────────────────────────────────────────────

def test_response_pairs_with_request_for_ts_and_duration(rec_page):
    rec, page = rec_page
    req = make_request()
    before = round(time.time() * 1000)
    page.emit("request", req)
    page.emit("response", make_response(req))
    n = rec.network[0]
    assert n["ts"] >= before
    assert n["duration_ms"] is not None and n["duration_ms"] >= 0
    assert n["seq"] == 1


def test_all_resource_types_captured_as_metadata(rec_page):
    rec, page = rec_page
    for rt in ("image", "stylesheet", "script", "font"):
        req = make_request(url=f"https://x.test/{rt}", resource_type=rt)
        page.emit("request", req)
        page.emit("response", make_response(req))
    assert [n["resource_type"] for n in rec.network] == \
        ["image", "stylesheet", "script", "font"]
    assert all("request_headers" not in n for n in rec.network)


def test_rich_fields_for_xhr(rec_page):
    rec, page = rec_page
    req = make_request(method="POST",
                       headers={"content-type": "application/json"},
                       post_data='{"user":"u","password":"pw"}')
    page.emit("request", req)
    page.emit("response", make_response(
        req,
        headers={"content-type": "application/json", "content-length": "17"},
        body='{"result": "ok"}'))
    n = rec.network[0]
    assert n["request_headers"]["content-type"] == "application/json"
    assert json.loads(n["post_data"])["password"] == REDACTED
    assert n["size"] == 17
    assert json.loads(n["body"]) == {"result": "ok"}   # small JSON xhr body kept


def test_failed_response_keeps_body(rec_page):
    rec, page = rec_page
    req = make_request(resource_type="image", url="https://x.test/a.png")
    page.emit("request", req)
    page.emit("response", make_response(req, status=500, body="err page"))
    n = rec.network[0]
    assert n["ok"] is False and n["body"] == "err page"


def test_request_failed_records_failure(rec_page):
    rec, page = rec_page
    req = make_request(failure="net::ERR_CONNECTION_REFUSED")
    page.emit("request", req)
    page.emit("requestfailed", req)
    n = rec.network[0]
    assert n["ok"] is False and n["failure"] == "net::ERR_CONNECTION_REFUSED"
    assert n["status"] is None and n["duration_ms"] is not None


def test_websocket_row(rec_page):
    rec, page = rec_page
    page.emit("websocket", SimpleNamespace(url="wss://x.test/live"))
    n = rec.network[0]
    assert n["method"] == "WS" and n["resource_type"] == "websocket" and n["ok"]


def test_network_cap_counts_dropped(rec_page):
    rec, page = rec_page
    for i in range(MAX_NETWORK_ENTRIES + 4):
        req = make_request(url=f"https://x.test/{i}", resource_type="image")
        page.emit("request", req)
        page.emit("response", make_response(req, status=500, body=""))
    assert len(rec.network) == MAX_NETWORK_ENTRIES
    assert rec.dropped["network"] == 4


# ── redaction ────────────────────────────────────────────────────────────────

def test_redact_headers_masks_sensitive_keys():
    out = redact_headers({"Authorization": "Bearer abc", "Cookie": "sid=1",
                          "X-Api-Key": "k", "Accept": "text/html"})
    assert out["Authorization"] == REDACTED
    assert out["Cookie"] == REDACTED
    assert out["X-Api-Key"] == REDACTED
    assert out["Accept"] == "text/html"


def test_redact_url_masks_sensitive_query_params():
    url = redact_url("https://x.test/cb?code=1&access_token=abc&page=2")
    assert f"access_token={REDACTED}" in url
    assert "page=2" in url and "code=1" in url


def test_redact_text_masks_nested_json_keys():
    out = json.loads(redact_text(
        '{"user": "u", "creds": {"refresh_token": "r"}, "n": 1}'))
    assert out["creds"]["refresh_token"] == REDACTED
    assert out["user"] == "u" and out["n"] == 1


def test_redact_text_masks_form_encoded():
    out = redact_text("user=u&password=pw&x=1")
    assert f"password={REDACTED}" in out and "x=1" in out


def test_redact_extra_keys_from_env(monkeypatch):
    import app.observability.recorder as r
    monkeypatch.setattr(r, "_extra_keys", lambda: ("wu-member",))
    assert redact_headers({"WU-Member-Id": "7"})["WU-Member-Id"] == REDACTED


def test_inflight_request_map_is_bounded(rec_page):
    import app.observability.recorder as r
    rec, page = rec_page
    reqs = [make_request(url=f"https://x.test/{i}") for i in range(r._MAX_INFLIGHT + 50)]
    for req in reqs:            # kept alive: the map is keyed by id(request)
        page.emit("request", req)
    assert len(rec._starts) == r._MAX_INFLIGHT
    assert id(reqs[0]) not in rec._starts and id(reqs[-1]) in rec._starts   # oldest evicted
