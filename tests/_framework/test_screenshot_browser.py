"""`screenshot` captures the viewport; with "full_page" the whole scrollable page.
A web font that never loads does not block it (L2 captures without the font
wait); a capture that cannot happen is a warning, after one bounded attempt."""

from __future__ import annotations

import base64
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from app.execution.engine import SHOT_CHECK, FlowRunner, _screenshot_warning
from app.flow.parser import FlowParseError, parse_flow_markdown
from app.layers.deterministic import DeterministicRunner
from app.layers.deterministic_l2 import FONTS_CHECK
from app.schemas.actions import ActionType, Evidence, FlowAction, StepResult

_TALL = '<body style="margin:0"><div style="height:1800px;background:linear-gradient(#fff,#000)">top</div></body>'


@pytest.fixture(autouse=True)
def quick(monkeypatch):
    monkeypatch.setattr(DeterministicRunner, "_L1_TIMEOUT", 600)


# A font requested after load (lazy CSS, a widget, JS) — `load` has fired, fonts have not.
_LATE_FONT = """() => { const s = document.createElement('style');
  s.textContent = "@font-face{font-family:Slow;src:url(https://fonts.example.test/slow.woff2)} div{font-family:Slow}";
  document.head.appendChild(s); }"""


def _run(page, tmp_path, steps: str, late_font: bool = False):
    page.set_viewport_size({"width": 800, "height": 600})
    page.set_content(_TALL)
    if late_font:
        page.evaluate(_LATE_FONT)
    runner = FlowRunner(artifacts_dir=str(tmp_path), flows_dir=tmp_path, provider=None)
    return runner.run(parse_flow_markdown("# T\n\n## Steps\n" + steps), page)


def _height(step) -> int:
    with Image.open(step.screenshot_path) as image:
        return image.height


def test_the_viewport_by_default_and_the_whole_page_with_full_page(page, tmp_path):
    result = _run(page, tmp_path, '- screenshot\n- screenshot: "named"\n'
                                  '- screenshot: "whole" | "full_page"\n- screenshot: "full_page"\n')
    assert result.success, [s.error for s in result.steps]
    viewport, named, whole, unnamed_whole = result.steps
    assert _height(viewport) == _height(named) == 600
    assert _height(whole) == _height(unnamed_whole) == 1800
    assert named.screenshot_path.endswith("_named.png") and whole.screenshot_path.endswith("_whole.png")
    assert unnamed_whole.screenshot_path.endswith("_step_4.png")          # the option is not taken as the name


def test_a_second_argument_must_be_the_option(page, tmp_path):
    result = _run(page, tmp_path, '- screenshot: "a" | "b"\n')
    assert not result.success and 'option "full_page"' in (result.steps[0].error or result.steps[0].message)
    assert result.steps[0].evidence.diagnosis["verdict"] != "timing"     # a flow error, not a slow capture
    assert "viewport" in result.steps[0].evidence.screenshots            # so the failure keeps its picture
    with pytest.raises(FlowParseError):
        parse_flow_markdown('# T\n\n## Steps\n- screenshot: "a" | "full_page" | "x"\n')


@pytest.fixture
def stuck_font(page):
    page.route("**/slow.woff2", lambda route: None)     # the font request is never answered
    yield
    page.unroute_all(behavior="ignoreErrors")
    page.set_content("")                                # drop the pending font with the document


def test_a_web_font_that_never_loads_does_not_block_the_screenshot(page, tmp_path, stuck_font, monkeypatch):
    monkeypatch.setattr(DeterministicRunner, "_SHOT_TIMEOUT", 700)        # L1 waits this long on the font
    monkeypatch.setattr(DeterministicRunner, "_FULL_SHOT_TIMEOUT", 900)
    result = _run(page, tmp_path, '- screenshot: "home"\n- screenshot: "whole" | "full_page"\n', late_font=True)
    assert result.success, [s.error for s in result.steps]
    viewport, whole = result.steps
    assert viewport.layer_used == whole.layer_used == 2
    assert _height(viewport) == _height(whole) == 600          # the fallback captures the visible part
    assert "visible part only" in next(c for c in whole.checks if c.name == FONTS_CHECK).detail
    assert viewport.screenshot_path.endswith("001_home.png") and whole.screenshot_path.endswith("002_whole.png")
    for step in (viewport, whole):
        warn = next(c for c in step.checks if c.name == FONTS_CHECK)
        assert warn.severity == "warn" and "fallback fonts" in warn.detail
        assert not any(c.severity == "error" for c in step.checks)         # a warning never fails the flow


def test_the_font_fallback_leaves_the_device_emulation_alone(page, tmp_path):
    """A clipped CDP capture from a second session resets Playwright's emulation;
    the fallback must not, or every later step of a mobile flow runs on a desktop-sized page."""
    mobile = page.context.browser.new_context(viewport={"width": 390, "height": 664}, device_scale_factor=3,
                                              is_mobile=True, has_touch=True)
    try:
        pg = mobile.new_page()
        pg.route("**/slow.woff2", lambda route: None)
        pg.set_content(_TALL)
        pg.evaluate(_LATE_FONT)
        state = "() => [devicePixelRatio, innerWidth, innerHeight]"
        before = pg.evaluate(state)
        runner = DeterministicRunner(pg, artifacts_dir=tmp_path)
        for args in (["home"], ["whole", "full_page"]):
            assert runner._l2_screenshot(FlowAction(type=ActionType.SCREENSHOT, args=args, step_num=1))
            assert pg.evaluate(state) == before, args
    finally:
        mobile.close()


def test_a_screenshot_that_cannot_capture_is_a_warning_not_a_failure(page, tmp_path, monkeypatch):
    real, calls = page.screenshot, []

    def first_two_stuck(**kwargs):
        calls.append(kwargs)
        if len(calls) <= 2:
            raise PlaywrightTimeoutError(f"Page.screenshot: Timeout {kwargs['timeout']}ms exceeded.")
        return real(**kwargs)

    monkeypatch.setattr(page, "screenshot", first_two_stuck)
    result = _run(page, tmp_path, '- screenshot: "home"\n- screenshot: "whole" | "full_page"\n'
                                  '- screenshot: "a:b/c d"\n')
    assert result.success, [s.error for s in result.steps]
    stuck, stuck_whole, taken = result.steps                   # one section: nothing stopped it
    # one bounded attempt per step: no settle-retry, no failure evidence captures after it
    assert [c["timeout"] for c in calls] == [10_000, 30_000, 10_000]
    assert [c["full_page"] for c in calls] == [False, True, False]
    for step in (stuck, stuck_whole):
        warn = next(c for c in step.checks if c.name == SHOT_CHECK)
        assert warn.severity == "warn" and not warn.passed
        assert "Timeout" in warn.detail and "Call log" not in warn.detail
        assert not step.screenshot_path and step.evidence is None
    assert taken.screenshot_path.endswith("001_a_b_c_d.png")      # misses kept no number; name made file-safe


def test_a_screenshot_still_fails_when_the_flow_or_the_browser_is_broken():
    def failed(args, triage):
        return StepResult(action=FlowAction(type=ActionType.SCREENSHOT, args=args), success=False,
                          message="x", error="Page.screenshot: Target page, context or browser has been closed",
                          evidence=Evidence(layers={"triage": triage}))
    assert not _screenshot_warning(failed(["a", "b"], "not_found")).success      # invalid arguments
    assert not _screenshot_warning(failed(["home"], "closed")).success            # the browser went away
    assert not _screenshot_warning(failed(["home"], "loading, then closed")).success
    assert _screenshot_warning(failed(["home"], "capture")).success


# ── L2 without a browser: what the CDP fallback does when a part of it fails ──

class _Cdp:
    def __init__(self, fail=False, fail_detach=False):
        self.fail, self.fail_detach, self.sent, self.detached = fail, fail_detach, [], False

    def send(self, method, params=None):
        self.sent.append((method, params))
        if self.fail:
            raise RuntimeError("Protocol error")
        return {"data": base64.b64encode(b"png").decode()}

    def detach(self):
        self.detached = True
        if self.fail_detach:
            raise RuntimeError("Target closed")


def _fake_page(fonts="loading", cdp=None, probe_error=None, cdp_error=None):
    def wait_for_function(js, polling=None, timeout=None):
        assert timeout                                  # the probe is always bounded
        if probe_error:
            raise probe_error
        return SimpleNamespace(json_value=lambda: fonts)

    def new_cdp_session(page):
        if cdp_error:
            raise cdp_error
        return cdp
    return SimpleNamespace(wait_for_function=wait_for_function,
                           context=SimpleNamespace(new_cdp_session=new_cdp_session))


def _l2(tmp_path, page, *args):
    runner = DeterministicRunner(page, artifacts_dir=tmp_path)
    return runner, runner._l2_screenshot(FlowAction(type=ActionType.SCREENSHOT, args=list(args), step_num=1))


@pytest.mark.parametrize("fake", [
    _fake_page(fonts="loaded"),                                            # fonts are not what blocked it
    _fake_page(probe_error=PlaywrightTimeoutError("Timeout 5000ms exceeded")),    # no frame drawn
    _fake_page(cdp_error=RuntimeError("CDP session is only available in Chromium")),
], ids=["fonts-loaded", "no-frame", "not-chromium"])
def test_l2_screenshot_gives_up_without_a_file(tmp_path, fake):
    runner, sr = _l2(tmp_path, fake, "home")
    assert sr is None and runner._shot_counter == 0 and not list(tmp_path.iterdir())


def test_l2_screenshot_detaches_when_the_capture_fails(tmp_path):
    cdp = _Cdp(fail=True)
    runner, sr = _l2(tmp_path, _fake_page(cdp=cdp), "home")
    assert sr is None and cdp.detached and runner._shot_counter == 0 and not list(tmp_path.iterdir())


def test_l2_screenshot_rejects_bad_arguments(tmp_path):
    assert _l2(tmp_path, _fake_page(cdp=_Cdp()), "a", "b")[1] is None


def test_l2_captures_the_visible_page_without_a_clip(tmp_path):
    cdp = _Cdp()
    runner, sr = _l2(tmp_path, _fake_page(cdp=cdp), "whole", "full_page")
    assert cdp.sent == [("Page.captureScreenshot", {"format": "png"})]    # no clip: emulation untouched
    assert sr.layer_used == 2 and runner._shot_counter == 1 and cdp.detached
    assert sr.screenshot_path.endswith("001_whole.png") and Path(sr.screenshot_path).read_bytes() == b"png"


def test_l2_keeps_the_capture_when_detach_fails(tmp_path):
    runner, sr = _l2(tmp_path, _fake_page(cdp=_Cdp(fail_detach=True)), "home")
    assert sr is not None and runner._shot_counter == 1


@pytest.mark.parametrize("name, stem", [
    ("../../etc/x", ".._.._etc_x"),            # no separator survives: the file stays in the folder
    ("!!!", "_"),
    ("Résumé page", "Résumé_page"),
    ("x" * 300, "x" * 100),
])
def test_screenshot_names_become_safe_file_names(tmp_path, name, stem):
    runner = DeterministicRunner(SimpleNamespace(), artifacts_dir=tmp_path)
    path = runner._shot_path(name)
    assert path.parent == tmp_path.resolve() and path.name == f"001_{stem}.png"
    assert runner._shot_path(name) == path      # asking for a path does not use up a number
