"""Unit tests for PageRecorder v2 — timestamps, levels, redaction, caps."""

from __future__ import annotations

import json
import time
from types import SimpleNamespace

import pytest

from app.execution import oracle
from app.observability.recorder import (
    MAX_ERROR_CONSOLE, MAX_INFO_CONSOLE, MAX_NETWORK_ENTRIES, REDACTED,
    PageRecorder, redact_headers, redact_text, redact_url,
)
from app.utils.urls import in_site, registrable_domain, site_domain


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


def test_pending_lists_inflight_requests_by_type_age_and_ignore(rec_page, monkeypatch):
    import app.observability.recorder as r
    rec, page = rec_page
    api = make_request(url="https://x.test/api/members")
    img = make_request(url="https://x.test/logo.png", resource_type="image")
    beacon = make_request(url="https://x.test/analytics/beacon")
    for req in (api, img, beacon):
        page.emit("request", req)
    xhr = frozenset({"xhr", "fetch"})
    assert rec.pending(xhr, 10) == ["https://x.test/api/members", "https://x.test/analytics/beacon"]
    assert rec.pending(xhr, 10, ignore=("/analytics/",)) == ["https://x.test/api/members"]
    page.emit("response", make_response(api))
    assert rec.pending(xhr, 10, ignore=("/analytics/",)) == []
    later = time.time() + 60                     # the beacon is now long-lived
    monkeypatch.setattr(r.time, "time", lambda: later)
    assert rec.pending(xhr, 10) == []


# ── sequence marks (per-step diagnostics for failure evidence) ───────────────

def test_seq_mark_windows_console_and_network(rec_page):
    rec, page = rec_page
    assert rec.seq == 0
    page.emit("console", console_msg(type_="error", text="before"))
    mark = rec.seq
    page.emit("console", console_msg(type_="error", text="during"))
    page.emit("console", console_msg(type_="info", text="chatter"))
    page.emit("console", console_msg(type_="warning", text="warned"))
    bad = make_request(url="https://x.test/api/save")
    page.emit("request", bad)
    page.emit("response", make_response(bad, status=500))
    ok = make_request(url="https://x.test/api/ok")
    page.emit("request", ok)
    page.emit("response", make_response(ok, status=200))
    page.emit("requestfailed", make_request(url="https://x.test/img.png", failure="net::ERR"))
    assert [c["text"] for c in rec.errors_since(mark)] == ["during", "warned"]
    assert [n["url"] for n in rec.failures_since(mark)] == [
        "https://x.test/api/save", "https://x.test/img.png"]
    assert rec.errors_since(mark, limit=1)[0]["text"] == "warned"   # newest kept


# ── only the site under test: prefetches and other sites are never recorded ──



def _nav(url):
    """A main-frame navigation request, the way Playwright reports one."""
    req = make_request(url=url, resource_type="document")
    req.is_navigation_request = lambda: True
    req.frame = SimpleNamespace(parent_frame=None)
    return req


def _serve(page, req, status):
    page.emit("request", req)
    page.emit("response", make_response(req, status=status))


def test_site_domain_is_the_registrable_domain():
    assert registrable_domain("memberssitestaging.wheelsup.com") == "wheelsup.com"
    assert registrable_domain("a.shop.example.co.uk") == "example.co.uk"
    assert registrable_domain("127.0.0.1") == "127.0.0.1" and registrable_domain("localhost") == "localhost"
    assert site_domain("https://one.wheelsup.com/home") == "wheelsup.com"
    assert site_domain("tel:855-FLY-8760") == site_domain("about:blank") == ""


@pytest.mark.parametrize("url, inside", [
    ("https://wheelsup.com/", True),
    ("https://memberssitestaging.wheelsup.com/signin", True),
    ("https://WheelsUp.com:8443/api", True),
    ("wss://live.wheelsup.com/socket", True),
    ("https://otherwheelsup.com/", False),                 # lookalike: not a subdomain
    ("https://wheelsup.com.example.org/", False),          # the domain as a label of another
    ("https://tracker.test/?ref=wheelsup.com", False),      # the domain only in the query
    ("tel:855-FLY-8760", False),
])
def test_in_site_checks_the_hostname_label_by_label(url, inside):
    assert in_site(url, "wheelsup.com") is inside


def test_a_failed_prefetch_is_not_recorded_but_the_same_navigation_is(rec_page):
    rec, page = rec_page
    rec.site_domain = "wheelsup.com"
    signin = "https://memberssitestaging.wheelsup.com/signin"
    _serve(page, make_request(url=signin, resource_type="prefetch"), 503)
    page.emit("console", console_msg(text="Failed to load resource: the server responded with a status of 503", url=signin))
    assert rec.network == [] and rec.console == [] and rec.untracked == {"prefetch": 1, "other_site": 0}
    assert {c.name: c for c in oracle.diagnostics_checks(rec, 0)}["no failed requests"].passed

    _serve(page, _nav(signin), 503)                         # a real navigation to the same URL
    assert [(n["url"], n["status"], n["resource_type"]) for n in rec.network] == [(signin, 503, "document")]
    failed = {c.name: c for c in oracle.diagnostics_checks(rec, 0)}["no failed requests"]
    assert not failed.passed and "signin → 503" in failed.detail


@pytest.mark.parametrize("headers", [{"sec-purpose": "prefetch"}, {"purpose": "prefetch"},
                                     {"sec-purpose": "prefetch;prerender"}, {"next-router-prefetch": "1"}])
def test_prefetch_purpose_headers_are_prefetches_too(rec_page, headers):
    rec, page = rec_page
    req = make_request(url="https://wheelsup.com/next", resource_type="fetch", headers=headers)
    page.emit("request", req)
    page.emit("requestfailed", SimpleNamespace(**{**vars(req), "failure": "net::ERR_FAILED"}))
    assert rec.network == [] and rec.untracked["prefetch"] == 1


def test_the_site_is_learned_from_the_first_navigation_and_other_sites_are_left_out(rec_page):
    rec, page = rec_page
    _serve(page, _nav("https://memberssitestaging.wheelsup.com/"), 200)
    assert rec.site_domain == "wheelsup.com"
    for url, status in [("https://api.wheelsup.com/v1/me", 500),               # subdomain: kept
                        ("https://otherwheelsup.com/x.js", 404),               # lookalike: left out
                        ("https://pagead2.googlesyndication.com/collect", 503)]:  # third party: left out
        _serve(page, make_request(url=url), status)
    page.emit("console", console_msg(text="Failed to load resource: 404", url="https://otherwheelsup.com/x.js"))
    page.emit("console", console_msg(text="TypeError: boom", url="https://otherwheelsup.com/x.js"))
    assert [n["url"] for n in rec.network] == ["https://memberssitestaging.wheelsup.com/",
                                               "https://api.wheelsup.com/v1/me"]
    assert [n["url"] for n in rec.failures_since(0)] == ["https://api.wheelsup.com/v1/me"]
    assert rec.untracked == {"prefetch": 0, "other_site": 2}
    assert [c["text"] for c in rec.console] == ["TypeError: boom"]     # only the resource echo is dropped


def test_a_given_site_domain_stays_and_navigations_elsewhere_are_still_recorded():
    rec, page = PageRecorder("wheelsup.com"), FakePage()
    rec.attach(page)
    _serve(page, _nav("https://login.example-sso.com/"), 500)       # the flow lands on an SSO page
    _serve(page, make_request(url="https://login.example-sso.com/app.js", resource_type="script"), 404)
    assert rec.site_domain == "wheelsup.com"
    assert [(n["url"], n["status"]) for n in rec.network] == [("https://login.example-sso.com/", 500)]
    assert rec.untracked == {"prefetch": 0, "other_site": 1}


def test_domains_as_written_are_normalized():
    from app.utils.urls import normalize_domain
    assert [normalize_domain(v) for v in ("Example.com", "https://example.com/", "localhost:3000",
                                          " .wheelsup.com. ", "bücher.de")] == [
        "example.com", "example.com", "localhost", "wheelsup.com", "xn--bcher-kva.de"]
    assert in_site("https://xn--bcher-kva.de/a", normalize_domain("bücher.de"))
    assert site_domain("https://myapp.azurewebsites.net/") == "myapp.azurewebsites.net"   # a tenant, not the platform
    assert in_site("file:///tmp/fixture.html", "") and not in_site("tel:123", "")


def test_other_browsers_cancelled_requests_are_not_failures():
    for failure in ("net::ERR_ABORTED", "NS_BINDING_ABORTED", "Load request cancelled"):
        assert oracle.cancelled({"failure": failure})
    assert not oracle.cancelled({"failure": "net::ERR_CONNECTION_REFUSED"})


def test_prefetches_are_never_waited_for(rec_page):
    rec, page = rec_page
    page.emit("request", make_request(url="https://x.test/next", resource_type="fetch",
                                      headers={"next-router-prefetch": "1"}))
    page.emit("request", make_request(url="https://x.test/api/me", resource_type="fetch"))
    assert rec.pending(frozenset({"fetch"}), 10) == ["https://x.test/api/me"]


def test_the_site_is_the_domain_of_the_first_goto_step(monkeypatch):
    from app.flow.placeholders import flow_site_domain
    from app.flow.parser import parse_flow_markdown

    def site(md: str) -> str:
        return flow_site_domain(parse_flow_markdown("# F\n\n" + md))

    assert site('## S\n- click: "x"\n- goto: "https://memberssitestaging.wheelsup.com/"\n'
                '- goto: "https://other.test/"\n') == "wheelsup.com"
    monkeypatch.setenv("APP_URL", "https://one.wheelsup.com/home")
    assert site('## S\n- goto: "<APP_URL>"\n') == "wheelsup.com"            # placeholders resolved
    monkeypatch.delenv("APP_URL")
    assert site('## S\n- goto: "<APP_URL>"\n') == ""                        # unset: the page load decides
    assert site('## Config\n- site_domain: "wheelsup.com"\n\n## S\n- goto: "https://sso.example.com/"\n') == "wheelsup.com"
    assert site('## S\n- run_flow: "components/login.md"\n') == ""
