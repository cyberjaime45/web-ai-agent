"""Failure evidence: screenshots, page state, diagnostics — always best-effort."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from app.observability.evidence import collect, slugify
from app.observability.recorder import PageRecorder
from app.schemas.actions import Evidence


class FakePage:
    url = "https://x.test/account"

    def __init__(self, fail_full_page=False):
        self.viewport_size = {"width": 390, "height": 664}
        self.fail_full_page = fail_full_page
        self.calls: list[dict] = []

    def title(self):
        return "Account"

    def screenshot(self, path, full_page=False, timeout=None):
        if full_page and self.fail_full_page:
            raise RuntimeError("Timeout 10000ms exceeded")
        self.calls.append({"path": path, "full_page": full_page, "timeout": timeout})
        Path(path).write_bytes(b"png")


class FakeLocator:
    def screenshot(self, path, timeout=None):
        Path(path).write_bytes(b"el")


def _recorder_with_activity():
    rec = PageRecorder()
    rec._push_console("info", "before", None)
    mark = rec.seq
    rec._push_console("error", "TypeError: x is undefined", "https://x.test/app.js:1:1")
    rec._push_console("info", "noise", None)
    rec._push_network({"method": "POST", "url": "https://x.test/api/contact", "status": 500,
                       "ok": False, "failure": None, "resource_type": "xhr", "ts": 1,
                       "duration_ms": 5, "size": None, "body": None})
    rec._push_network({"method": "GET", "url": "https://x.test/ok", "status": 200,
                       "ok": True, "failure": None, "resource_type": "xhr", "ts": 2,
                       "duration_ms": 5, "size": None, "body": None})
    return rec, mark


def test_slugify_is_file_name_safe():
    assert slugify("FMS MVC Smoke Tests") == "fms_mvc_smoke_tests"
    assert slugify("  Home / Page!  ") == "home_page"
    assert slugify("") == "flow"


def test_collect_captures_all_three_shots_and_page_state(tmp_path):
    page = FakePage()
    ev = collect(page, tmp_path, "login__mobile__01", profile="mobile",
                 locator=FakeLocator())
    assert ev.url == "https://x.test/account" and ev.title == "Account"
    assert ev.profile.startswith("mobile · ") and ev.profile.endswith("390x664")
    assert set(ev.screenshots) == {"viewport", "full_page", "element"}
    assert ev.screenshots["viewport"].endswith("login__mobile__01__viewport.png")
    assert ev.screenshots["full_page"].endswith("login__mobile__01__full.png")
    assert ev.screenshots["element"].endswith("login__mobile__01__element.png")
    assert all(Path(p).exists() for p in ev.screenshots.values())
    # the full-page capture is capped so long pages cannot hang the run
    full = next(c for c in page.calls if c["full_page"])
    assert full["timeout"] == 10_000


def test_collect_skips_a_failing_capture_and_keeps_the_rest(tmp_path):
    ev = collect(FakePage(fail_full_page=True), tmp_path, "s", locator=None)
    assert "viewport" in ev.screenshots
    assert "full_page" not in ev.screenshots
    assert "element" not in ev.screenshots       # no locator → no element shot


def test_collect_keeps_existing_layers_and_shots(tmp_path):
    existing = Evidence(layers={"L1 exact": "failed"}, screenshots={"viewport": "/kept.png"})
    ev = collect(FakePage(), tmp_path, "s", evidence=existing)
    assert ev is existing
    assert ev.layers == {"L1 exact": "failed"}
    assert ev.screenshots["viewport"] == "/kept.png"      # not re-shot
    assert "full_page" in ev.screenshots


def test_collect_reports_only_activity_since_the_mark(tmp_path):
    rec, mark = _recorder_with_activity()
    ev = collect(FakePage(), tmp_path, "s", recorder=rec, since_seq=mark)
    assert [c["text"] for c in ev.console] == ["TypeError: x is undefined"]
    assert [n["url"] for n in ev.network] == ["https://x.test/api/contact"]


def test_collect_never_raises_on_a_dead_page(tmp_path):
    dead = SimpleNamespace(
        url="x", viewport_size=None,
        title=lambda: (_ for _ in ()).throw(RuntimeError("closed")),
        screenshot=lambda **kw: (_ for _ in ()).throw(RuntimeError("closed")),
        evaluate=lambda *_: (_ for _ in ()).throw(RuntimeError("closed")),
    )
    ev = collect(dead, tmp_path, "s", recorder=object(), since_seq=0)
    assert ev.screenshots == {} and ev.title == "" and ev.console == []


def test_slugify_caps_very_long_names():
    slug = slugify("file:///" + "x/" * 100 + "page.html")
    assert len(slug) <= 80 and not slug.endswith("_")
