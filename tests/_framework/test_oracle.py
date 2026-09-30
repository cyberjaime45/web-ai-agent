"""Oracle: recorder diagnostics, ignore rules, probe, summaries."""

from __future__ import annotations

from app.execution import oracle
from app.observability.recorder import PageRecorder
from app.schemas.actions import ActionType, FlowAction


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


def test_automatic_checks_flag_only_what_breaks_the_page():
    """After a step, a log level or a status code alone is no impact: an API 401
    (not signed in), a 404 lookup or a console message is information."""
    out = {c.name: c.outcome for c in oracle.diagnostics_checks(_rec(), 0)}
    assert out["no page errors"] == "failed"                  # uncaught JS: the code broke
    assert out["no failed requests"] == "failed"              # API 500
    assert out["no console errors"] == "info"
    assert out["no 401/403 responses"] == "info"
    assert out["no 4xx responses"] == "info"
    checks = {c.name: c for c in oracle.diagnostics_checks(_rec(), 0)}
    assert "api/save → 500" in checks["no failed requests"].detail
    assert "img.png" not in checks["no failed requests"].detail          # cancelled, not failed
    assert checks["requests cancelled"].outcome == "info"
    assert "img.png → net::ERR_ABORTED" in checks["requests cancelled"].detail
    assert "analytics" in checks["no 4xx responses"].detail


def test_an_explicit_check_makes_the_lesser_findings_warnings():
    out = {c.name: c.outcome for c in oracle.diagnostics_checks(_rec(), 0, explicit=True)}
    assert (out["no console errors"], out["no 401/403 responses"], out["no 4xx responses"]) == (
        "warning", "warning", "warning")
    assert out["no page errors"] == "failed" and out["no failed requests"] == "failed"


def test_a_request_is_judged_by_what_it_was_for():
    rec = PageRecorder(site_domain="x.test")
    for url, rt, status in [("https://x.test/", "document", 404), ("https://x.test/app.js", "script", 404),
                            ("https://x.test/me", "fetch", 401), ("https://x.test/logo.png", "image", 404)]:
        rec._push_network({"method": "GET", "url": url, "status": status, "ok": False, "failure": None,
                           "resource_type": rt, "ts": 1, "duration_ms": 1, "size": None, "body": None})
    rec._push_console("error", "tracker blew up", "https://tracker.example/t.js:1:1")
    checks = {c.name: c for c in oracle.diagnostics_checks(rec, 0)}
    assert checks["no failed requests"].count == 2            # the page and its script
    assert checks["no failed resources"].outcome == "info" and "logo.png" in checks["no failed resources"].detail
    assert "no console errors" not in checks                  # not the site's own script
    assert checks["console errors from other scripts"].outcome == "info"


def test_diagnostics_count_what_they_found():
    # The report shows "Console errors · 2" from the count, never by splitting
    # the detail text (console messages contain "; " themselves).
    counts = {c.name: c.count for c in oracle.diagnostics_checks(_rec(), 0)}
    assert counts == {"no page errors": 1, "no console errors": 2, "no failed requests": 1,
                      "no 401/403 responses": 1, "no 4xx responses": 1, "requests cancelled": 1}
    assert {c.count for c in oracle.probe_checks(_Page(spinner=3))} >= {3}
    assert all(c.count == 0 for c in oracle.diagnostics_checks(_rec(), _rec().seq))


def test_ignore_rules_drop_known_noise():
    ignore = oracle.IgnoreRules(console=["ResizeObserver"], network=["/analytics/"])
    checks = {c.name: c for c in oracle.diagnostics_checks(_rec(), 0, ignore)}
    assert checks["no console errors"].detail == "TypeError: boom"
    assert "no 4xx responses" not in checks                   # automatic mode lists only what it found


def test_since_seq_windows_the_checks():
    rec = _rec()
    checks = oracle.diagnostics_checks(rec, rec.seq)
    assert all(c.passed for c in checks)


class _Page:
    url = "https://x.test/"

    def __init__(self, **probe):
        self.probe = {"readyState": "complete", "textLength": 120, "spinner": 0,
                      "dialog": "", "overflow": 0, **probe}

    def evaluate(self, js):
        return self.probe


def test_probe_checks():
    ok = {c.name: c.passed for c in oracle.probe_checks(_Page())}
    assert ok == {"page rendered": True, "no horizontal overflow": True}     # notes only when seen
    bad = {c.name: c for c in oracle.probe_checks(_Page(textLength=0, spinner=2, dialog="Confirm", overflow=340))}
    assert not bad["page rendered"].passed and bad["page rendered"].severity == "error"
    assert bad["no blocking dialog"].detail == "modal dialog open: Confirm"
    assert (bad["no stuck spinner"].outcome, bad["no blocking dialog"].outcome) == ("info", "info")
    assert bad["no horizontal overflow"].detail == "content 340px wider than the viewport"


def test_probe_never_raises():
    class Dead:
        def evaluate(self, js):
            raise RuntimeError("closed")
    assert oracle.probe_checks(Dead()) == []


def test_summary_wording():
    checks = oracle.probe_checks(_Page())
    assert oracle.summary(checks) == "2 checks passed"          # the spinner and dialog notes are not judged
    checks = oracle.probe_checks(_Page(textLength=0, spinner=1))
    assert oracle.summary(checks) == "1 of 2 checks failed"     # one snapshot cannot tell stuck from loading
    assert oracle.summary([]) == "no checks"


def test_network_ignore_also_drops_the_console_echo_of_that_request():
    rec = PageRecorder()
    rec._push_console("error", "Failed to load resource: the server responded with a status of 404",
                      "https://x.test/api/missing:0:0")
    rec._push_console("error", "Unrelated", None)
    ignore = oracle.IgnoreRules(network=["/api/"])
    checks = {c.name: c for c in oracle.diagnostics_checks(rec, 0, ignore)}
    assert checks["no console errors"].detail == "Unrelated"


# ── after-state, effect and read-back checks ────────────────────────────────

def test_probe_yields_the_after_state_and_the_checks_from_one_evaluate():
    page = _Page(hash=42, heading="Profile", dialog="Edit", modal=False, alert="Saved", active="input#name")
    state, checks = oracle.observe_after(page, None, 0)
    assert state == {"heading": "Profile", "dialog": "Edit", "alert": "Saved", "hash": 42,
                     "active": "input#name", "url": "https://x.test/"}
    assert oracle.DIALOG_CHECK not in {c.name for c in checks}      # a non-modal dialog does not block
    assert oracle.after_state(None) == {}


def test_effect_check_compares_the_page_before_and_after_a_press():
    click = FlowAction(type=ActionType.CLICK, args=["Save"])
    same = {"url": "u", "hash": 1, "heading": "h", "dialog": "", "alert": "", "active": ""}
    none = oracle.effect_check(click, same, dict(same), 0)
    assert none is not None and not none.passed and none.severity == "warn" and '"Save"' in none.detail
    moved = oracle.effect_check(click, same, {**same, "url": "v", "alert": "Saved"}, 0)
    assert moved.passed and moved.detail == "url, alert"
    assert oracle.effect_check(click, same, dict(same), 2).passed          # a request counts
    assert oracle.effect_check(click, {}, same, 0) is None                 # nothing to compare with
    assert oracle.effect_check(FlowAction(type=ActionType.PRESS, args=["Tab"]), same, dict(same), 0) is None
    assert oracle.effect_check(FlowAction(type=ActionType.FILL, args=["a", "b"]), same, dict(same), 0) is None


class _Control:
    def __init__(self, value="", checked=False, chosen=()):
        self._value, self._checked, self._chosen = value, checked, list(chosen)

    def input_value(self, timeout=0):
        return self._value

    def is_checked(self, timeout=0):
        return self._checked

    def evaluate(self, js, timeout=0):
        return self._chosen


def test_readback_check_reads_the_control_after_an_input_step():
    fill = FlowAction(type=ActionType.FILL, args=["Name", "Ada"])
    assert oracle.readback_check(fill, _Control("Ada")).passed
    bad = oracle.readback_check(fill, _Control(""))
    assert not bad.passed and bad.severity == "warn" and "reads ''" in bad.detail
    assert oracle.readback_check(FlowAction(type=ActionType.TYPE, args=["Q", "bo"]), _Control("bos")).passed
    assert not oracle.readback_check(FlowAction(type=ActionType.CHECK, args=["Terms"]), _Control(checked=False)).passed
    assert oracle.readback_check(FlowAction(type=ActionType.UNCHECK, args=["Terms"]), _Control(checked=False)).passed
    select = FlowAction(type=ActionType.SELECT, args=["Country", "Spain"])
    assert oracle.readback_check(select, _Control(chosen=("es", "Spain"))).passed
    assert "shows 'France'" in oracle.readback_check(select, _Control(chosen=("fr", "France"))).detail

    class Custom:
        def input_value(self, timeout=0):
            raise RuntimeError("not an input")
    assert oracle.readback_check(fill, Custom()) is None          # unreadable control: no finding


def test_wait_for_change_polls_the_page_only_when_there_is_a_state_to_compare():
    class Page:
        def __init__(self):
            self.calls = []

        def wait_for_function(self, js, arg=None, polling=None, timeout=None):
            self.calls.append((arg, timeout))
            raise TimeoutError("no change")          # swallowed: a no-op press is a finding, not an error
    page = Page()
    oracle.wait_for_change(page, {"hash": 7, "url": "u"}, 300)
    assert page.calls == [([7, "u"], 300)]
    oracle.wait_for_change(page, {}, 300)
    assert len(page.calls) == 1
