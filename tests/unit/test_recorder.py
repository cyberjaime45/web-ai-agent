"""Unit tests for PageRecorder — console/network capture."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.observability.recorder import (
    MAX_CONSOLE_ENTRIES,
    MAX_NETWORK_ENTRIES,
    PageRecorder,
)


class FakePage:
    """Collects page.on registrations so tests can fire events manually."""

    def __init__(self) -> None:
        self.handlers: dict[str, object] = {}

    def on(self, event: str, handler) -> None:
        self.handlers[event] = handler


def make_console_msg(type_: str, text: str, url: str = "", line: int = 0):
    return SimpleNamespace(
        type=type_,
        text=text,
        location={"url": url, "lineNumber": line} if url else {},
    )


def make_response(status: int, resource_type: str, url: str = "https://api.test/x",
                  method: str = "GET", body: str = ""):
    request = SimpleNamespace(resource_type=resource_type, method=method)
    resp = SimpleNamespace(status=status, url=url, request=request)
    resp.text = lambda: body
    return resp


def make_failed_request(url: str = "https://api.test/y", method: str = "POST",
                        failure: str = "net::ERR_CONNECTION_REFUSED",
                        resource_type: str = "xhr"):
    return SimpleNamespace(
        url=url, method=method, failure=failure, resource_type=resource_type
    )


@pytest.fixture
def recorder() -> PageRecorder:
    rec = PageRecorder()
    rec.attach(FakePage())
    return rec


@pytest.fixture
def page_and_recorder() -> tuple[FakePage, PageRecorder]:
    page = FakePage()
    rec = PageRecorder()
    rec.attach(page)
    return page, rec


def test_attach_registers_listeners(page_and_recorder):
    page, _ = page_and_recorder
    assert set(page.handlers) == {"console", "pageerror", "response", "requestfailed"}


def test_console_keeps_errors_and_warnings(page_and_recorder):
    page, rec = page_and_recorder
    page.handlers["console"](make_console_msg("warning", "deprecated API", "https://a.test/app.js", 12))
    page.handlers["console"](make_console_msg("error", "boom"))
    assert [c["level"] for c in rec.console] == ["warning", "error"]
    assert rec.console[0]["location"] == "https://a.test/app.js:12"
    assert rec.console[1]["location"] is None


def test_console_drops_log_and_info(page_and_recorder):
    page, rec = page_and_recorder
    page.handlers["console"](make_console_msg("log", "hello"))
    page.handlers["console"](make_console_msg("info", "world"))
    assert rec.console == []


def test_pageerror_recorded(page_and_recorder):
    page, rec = page_and_recorder
    page.handlers["pageerror"](Exception("ReferenceError: x is not defined"))
    assert rec.console[0]["level"] == "pageerror"
    assert "ReferenceError" in rec.console[0]["text"]


def test_console_cap(page_and_recorder):
    page, rec = page_and_recorder
    for i in range(MAX_CONSOLE_ENTRIES + 10):
        page.handlers["console"](make_console_msg("error", f"e{i}"))
    assert len(rec.console) == MAX_CONSOLE_ENTRIES


def test_network_keeps_interesting_types(page_and_recorder):
    page, rec = page_and_recorder
    page.handlers["response"](make_response(200, "xhr"))
    page.handlers["response"](make_response(200, "document"))
    assert len(rec.network) == 2
    assert all(n["ok"] for n in rec.network)
    assert rec.network[0]["body"] is None


def test_network_drops_passing_assets(page_and_recorder):
    page, rec = page_and_recorder
    page.handlers["response"](make_response(200, "image"))
    page.handlers["response"](make_response(304, "stylesheet"))
    assert rec.network == []


def test_network_failed_response_keeps_body(page_and_recorder):
    page, rec = page_and_recorder
    page.handlers["response"](make_response(404, "image", body='{"error":"missing"}'))
    entry = rec.network[0]
    assert entry["ok"] is False
    assert entry["status"] == 404
    assert entry["body"] == '{"error":"missing"}'


def test_network_request_failed(page_and_recorder):
    page, rec = page_and_recorder
    page.handlers["requestfailed"](make_failed_request())
    entry = rec.network[0]
    assert entry["ok"] is False
    assert entry["status"] is None
    assert entry["failure"] == "net::ERR_CONNECTION_REFUSED"


def test_network_cap(page_and_recorder):
    page, rec = page_and_recorder
    for _ in range(MAX_NETWORK_ENTRIES + 5):
        page.handlers["response"](make_response(200, "xhr"))
    assert len(rec.network) == MAX_NETWORK_ENTRIES


def test_body_read_error_is_swallowed(page_and_recorder):
    page, rec = page_and_recorder
    resp = make_response(500, "fetch")

    def boom():
        raise RuntimeError("body gone after navigation")

    resp.text = boom
    page.handlers["response"](resp)
    assert rec.network[0]["body"] is None
