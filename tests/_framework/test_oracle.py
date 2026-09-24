"""Oracle: recorder diagnostics, ignore rules, probe, summaries."""

from __future__ import annotations

from app.execution import oracle
from app.observability.recorder import PageRecorder


def _rec():
    rec = PageRecorder()
    rec._push_console("error", "ResizeObserver loop limit exceeded", None)
    rec._push_console("error", "TypeError: boom", None)
    rec._push_console("pageerror", "Uncaught ReferenceError", None)
    for url, status, failure in [("https://x.test/api/save", 500, None),
                                 ("https://x.test/analytics/beat", 404, None),
                                 ("https://x.test/me", 401, None),
                                 ("https://x.test/img.png", None, "net::ERR_ABORTED"),
                                 ("https://x.test/ok", 200, None)]:
        rec._push_network({"method": "GET", "url": url, "status": status, "ok": status == 200,
                           "failure": failure, "resource_type": "xhr", "ts": 1,
                           "duration_ms": 1, "size": None, "body": None})
    return rec


def test_diagnostics_split_by_severity():
    checks = {c.name: c for c in oracle.diagnostics_checks(_rec(), 0)}
    assert not checks["no page errors"].passed and checks["no page errors"].severity == "error"
    assert not checks["no console errors"].passed and checks["no console errors"].severity == "warn"
    assert not checks["no failed requests"].passed
    assert "api/save → 500" in checks["no failed requests"].detail
    assert "img.png → net::ERR_ABORTED" in checks["no failed requests"].detail
    assert not checks["no 401/403 responses"].passed
    assert not checks["no 4xx responses"].passed and "analytics" in checks["no 4xx responses"].detail


def test_diagnostics_count_what_they_found():
    # The report shows "Console errors · 2" from the count, never by splitting
    # the detail text (console messages contain "; " themselves).
    counts = {c.name: c.count for c in oracle.diagnostics_checks(_rec(), 0)}
    assert counts == {"no page errors": 1, "no console errors": 2, "no failed requests": 2,
                      "no 401/403 responses": 1, "no 4xx responses": 1}
    assert {c.count for c in oracle.probe_checks(_Page(spinner=3))} >= {3}
    assert all(c.count == 0 for c in oracle.diagnostics_checks(_rec(), _rec().seq))


def test_ignore_rules_drop_known_noise():
    ignore = oracle.IgnoreRules(console=["ResizeObserver"], network=["/analytics/"])
    checks = {c.name: c for c in oracle.diagnostics_checks(_rec(), 0, ignore)}
    assert checks["no console errors"].detail == "TypeError: boom"
    assert checks["no 4xx responses"].passed


def test_since_seq_windows_the_checks():
    rec = _rec()
    checks = oracle.diagnostics_checks(rec, rec.seq)
    assert all(c.passed for c in checks)


class _Page:
    def __init__(self, **probe):
        self.probe = {"readyState": "complete", "textLength": 120, "spinner": 0,
                      "dialog": "", "overflow": 0, **probe}

    def evaluate(self, js):
        return self.probe


def test_probe_checks():
    ok = {c.name: c.passed for c in oracle.probe_checks(_Page())}
    assert ok == {"page rendered": True, "no stuck spinner": True,
                  "no blocking dialog": True, "no horizontal overflow": True}
    bad = {c.name: c for c in oracle.probe_checks(_Page(textLength=0, spinner=2, dialog="Confirm", overflow=340))}
    assert not bad["page rendered"].passed and bad["page rendered"].severity == "error"
    assert bad["no blocking dialog"].detail == "modal dialog open: Confirm"
    assert bad["no horizontal overflow"].detail == "content 340px wider than the viewport"


def test_probe_never_raises():
    class Dead:
        def evaluate(self, js):
            raise RuntimeError("closed")
    assert oracle.probe_checks(Dead()) == []


def test_summary_wording():
    checks = oracle.probe_checks(_Page())
    assert oracle.summary(checks) == "4 checks passed"
    checks = oracle.probe_checks(_Page(textLength=0, spinner=1))
    assert oracle.summary(checks) == "1 of 4 checks failed, 1 warning"
    assert oracle.summary([]) == "no checks"


def test_network_ignore_also_drops_the_console_echo_of_that_request():
    rec = PageRecorder()
    rec._push_console("error", "Failed to load resource: the server responded with a status of 404",
                      "https://x.test/api/missing:0:0")
    rec._push_console("error", "Unrelated", None)
    ignore = oracle.IgnoreRules(network=["/api/"])
    checks = {c.name: c for c in oracle.diagnostics_checks(rec, 0, ignore)}
    assert checks["no console errors"].detail == "Unrelated"
