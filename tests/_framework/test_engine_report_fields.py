"""Engine emits wall-clock step timestamps and skipped StepResults."""

from __future__ import annotations

import time

import pytest

from app.execution.engine import FlowRunner
from app.flow.parser import parse_flow_markdown
from app.schemas.actions import StepResult


class FakePage:
    url = "https://x.test/"

    def title(self):
        return "t"


@pytest.fixture
def runner(tmp_path):
    return FlowRunner(artifacts_dir=str(tmp_path), flows_dir=tmp_path, provider=None)


def _patch_run_step(monkeypatch, fail_raws=()):
    def fake(self, action, page, runner, ctx):
        ok = action.raw not in fail_raws
        return StepResult(action=action, success=ok,
                          message="" if ok else "boom", layer_used=1)
    monkeypatch.setattr(FlowRunner, "_run_step", fake)


MD = """# T

## One
- click: "a"
- click: "b"

## Two
- click: "c"
"""


def test_steps_get_wallclock_timestamps(monkeypatch, runner):
    _patch_run_step(monkeypatch)
    before = time.time()
    result = runner.run(parse_flow_markdown(MD), FakePage())
    after = time.time()
    assert result.success
    for s in result.steps:
        assert before <= s.started_at <= s.ended_at <= after


def test_failed_section_steps_recorded_as_skipped(monkeypatch, runner):
    _patch_run_step(monkeypatch, fail_raws=('click: "a"',))
    result = runner.run(parse_flow_markdown(MD), FakePage())
    assert not result.success
    raws = [(s.action.raw, s.success, s.skipped) for s in result.steps]
    assert raws == [
        ('click: "a"', False, False),
        ('click: "b"', False, True),   # was silently dropped before
        ('click: "c"', True, False),   # next section still runs
    ]
    skipped = result.steps[1]
    assert skipped.started_at == 0.0 and skipped.ended_at == 0.0
    assert skipped.duration == 0.0
    # pass/fail math unchanged: skipped steps are not failures
    assert result.failed == 1 and result.skipped == 1


# ── failure evidence ─────────────────────────────────────────────────────────

class ShootingPage(FakePage):
    """FakePage that can be photographed."""
    viewport_size = {"width": 1920, "height": 1080}

    def screenshot(self, path, full_page=False, timeout=None):
        from pathlib import Path
        Path(path).write_bytes(b"png")


def test_failed_step_gets_evidence_with_layers_and_screenshots(monkeypatch, runner, tmp_path):
    _patch_run_step(monkeypatch, fail_raws=('click: "a"',))
    result = runner.run(parse_flow_markdown(MD), ShootingPage())
    failed, skipped, ok = result.steps
    assert failed.evidence is not None
    assert failed.evidence.layers == {"L1": "failed"}          # the fake gave no layer detail
    assert failed.evidence.url == "https://x.test/"
    assert failed.evidence.profile.startswith("desktop")
    assert failed.evidence.screenshots["viewport"].endswith("__desktop__01__viewport.png")
    assert failed.screenshot_path == failed.evidence.screenshots["viewport"]
    assert "full_page" in failed.evidence.screenshots
    assert skipped.evidence is None and ok.evidence is None


def test_evidence_files_are_numbered_per_failure(monkeypatch, runner):
    _patch_run_step(monkeypatch, fail_raws=('click: "a"', 'click: "c"'))
    result = runner.run(parse_flow_markdown(MD), ShootingPage())
    stems = [s.evidence.screenshots["viewport"].rsplit("/", 1)[1]
             for s in result.steps if s.evidence]
    assert stems == ["t__desktop__01__viewport.png", "t__desktop__02__viewport.png"]


def test_unresolved_placeholder_fails_with_evidence(monkeypatch, runner):
    monkeypatch.delenv("WEBAGENT_MISSING_VAR", raising=False)
    flow = parse_flow_markdown('# T\n\n## Steps\n- fill: "Email" | "<WEBAGENT_MISSING_VAR>"\n')
    result = runner.run(flow, ShootingPage())
    step = result.steps[0]
    assert not step.success and "WEBAGENT_MISSING_VAR" in step.message
    assert step.evidence.layers == {"L1 exact": "not attempted (placeholder unresolved)"}
    assert step.evidence.screenshots["viewport"]


def test_attach_evidence_is_idempotent(monkeypatch, runner):
    _patch_run_step(monkeypatch, fail_raws=('click: "a"',))
    page = ShootingPage()
    result = runner.run(parse_flow_markdown(MD), page)
    failed = result.steps[0]
    first = dict(failed.evidence.screenshots)
    runner.attach_evidence(failed, page)         # conftest's flow-end fallback
    assert failed.evidence.screenshots == first  # nothing re-shot, nothing renumbered


# ── verify stage: after-state and effect checks ─────────────────────────────

class _ProbePage(FakePage):
    """A page whose probe answers change only when a step's hash says so."""

    def __init__(self, hashes):
        self.hashes = list(hashes)

    def evaluate(self, js, arg=None):
        h = self.hashes.pop(0) if self.hashes else 0
        return {"readyState": "complete", "textLength": 10, "spinner": 0, "dialog": "", "modal": False,
                "overflow": 0, "hash": h, "heading": "Home", "alert": "", "active": ""}


def test_verify_records_after_state_and_flags_a_press_that_changed_nothing(monkeypatch, runner):
    from types import SimpleNamespace

    from app.execution import oracle
    _patch_run_step(monkeypatch)
    monkeypatch.setattr("app.execution.engine.settings",
                        SimpleNamespace(oracle="warn", images_dir=None, allow_destructive=False))
    flow = parse_flow_markdown('# T\n\n## S\n- goto: "https://x"\n- fill: "Name" | "Ada"\n- click: "Save"\n- click: "Next"\n')
    goto, fill, save, nxt = runner.run(flow, _ProbePage([1, 1, 2])).steps
    assert goto.after["hash"] == 1 and goto.after["heading"] == "Home" and goto.after["url"] == "https://x.test/"
    assert goto.checks and not any(c.name == oracle.EFFECT_CHECK for c in goto.checks)   # nothing to compare yet
    assert fill.after == {} and fill.checks == []                    # not a navigation step; runner=None: no read-back
    effect = {c.name: c for c in save.checks}[oracle.EFFECT_CHECK]
    assert not effect.passed and effect.severity == "warn" and '"Save" changed nothing' in effect.detail
    assert save.success                                              # a warning, never a failure
    assert {c.name: c for c in nxt.checks}[oracle.EFFECT_CHECK].passed   # the hash moved: an effect


# ── failure path: triage decides what is tried after L1 ─────────────────────

class _Layers:
    """A runner whose L1 and L2 fail or pass on demand, counting the calls."""

    def __init__(self, l1=("raise",), l2="raise"):
        self.l1, self.l2, self.calls = list(l1), l2, {"l1": 0, "l2": 0}

    def layer1(self, action):
        self.calls["l1"] += 1
        outcome = self.l1.pop(0) if self.l1 else "raise"
        if outcome == "raise":
            raise TimeoutError("Locator.click: Timeout 5000ms exceeded.")
        return StepResult(action=action, success=True, message="ok", layer_used=1)

    def layer2(self, action, original_error):
        self.calls["l2"] += 1
        if self.l2 == "raise":
            raise RuntimeError("Layers 1+2 could not resolve")
        return StepResult(action=action, success=True, message="fuzzy", layer_used=2)

    def locate(self, action):
        return None


class _AI:
    def __init__(self):
        self.calls = 0
        self.available = True

    def supports(self, action_type):
        return True

    def resolve(self, action, page, error, ctx, cause=""):
        self.calls += 1
        return StepResult(action=action, success=True, message="ai", layer_used=3)


def _step(runner, monkeypatch, cause, layers, ai=None, settle=""):
    from app.execution import engine as eng
    from app.schemas.actions import ActionType, FlowAction, RunContext
    causes = list(cause) if isinstance(cause, list) else [cause]
    monkeypatch.setattr(eng.diagnosis, "triage", lambda *a, **k: causes.pop(0) if len(causes) > 1 else causes[0])
    monkeypatch.setattr(eng.stability, "wait_stable", lambda *a, **k: settle)
    monkeypatch.setattr(eng, "settings", __import__("types").SimpleNamespace(oracle="off", images_dir=None,
                                                                             allow_destructive=False))
    monkeypatch.setattr(runner, "attach_evidence", lambda sr, *a, **k: sr)
    if ai is not None:
        runner._ai = ai
    action = FlowAction(type=ActionType.CLICK, args=["Save"], raw='click: "Save"', step_num=1)
    return runner.execute(action, FakePage(), layers, RunContext())


def test_a_locator_problem_goes_down_the_whole_chain(runner, monkeypatch):
    layers, ai = _Layers(), _AI()
    sr = _step(runner, monkeypatch, "not_found", layers, ai)
    assert sr.success and sr.layer_used == 3 and layers.calls == {"l1": 1, "l2": 1} and ai.calls == 1


def test_a_server_error_allows_fuzzy_but_never_the_llm(runner, monkeypatch):
    layers, ai = _Layers(), _AI()
    sr = _step(runner, monkeypatch, "server", layers, ai)
    assert not sr.success and layers.calls["l2"] == 1 and ai.calls == 0
    assert sr.evidence.layers == {"L1 exact": "failed", "triage": "server", "L2 fuzzy": "failed",
                                  "L3 AI": "skipped: server error on the page"}


def test_a_broken_or_redirected_page_gets_no_retry_at_all(runner, monkeypatch):
    for cause in ("blank", "session", "covered", "network"):
        layers, ai = _Layers(), _AI()
        sr = _step(runner, monkeypatch, cause, layers, ai)
        assert not sr.success and layers.calls == {"l1": 1, "l2": 0} and ai.calls == 0, cause
        assert sr.evidence.layers["L2 fuzzy"] == sr.evidence.layers["L3 AI"] == f"skipped: {cause}"
        assert sr.message.startswith(f"L1 failed ({cause})")


def test_a_loading_page_gets_one_settle_and_one_more_l1_attempt(runner, monkeypatch):
    from app.execution.engine import SETTLED_CHECK
    layers = _Layers(l1=["raise", "pass"])
    sr = _step(runner, monkeypatch, "loading", layers, _AI())
    assert sr.success and sr.layer_used == 1 and layers.calls == {"l1": 2, "l2": 0}
    settled = {c.name: c for c in sr.checks}[SETTLED_CHECK]
    assert not settled.passed and settled.severity == "warn" and "passed only after waiting" in settled.detail


def test_a_page_that_never_settles_fails_as_timing_without_l2_or_l3(runner, monkeypatch):
    layers, ai = _Layers(), _AI()
    sr = _step(runner, monkeypatch, "loading", layers, ai, settle="2 loading indicator(s) still visible")
    assert not sr.success and layers.calls == {"l1": 1, "l2": 0} and ai.calls == 0
    assert sr.evidence.layers["triage"] == "loading" and "did not settle" in sr.evidence.layers["recovery"]


def test_after_settling_the_second_failure_is_triaged_again(runner, monkeypatch):
    layers = _Layers(l1=["raise", "raise"], l2="pass")
    sr = _step(runner, monkeypatch, ["loading", "not_found"], layers, _AI())
    assert sr.success and sr.layer_used == 2 and layers.calls == {"l1": 2, "l2": 1}


def test_a_press_that_changed_nothing_is_a_note_for_the_next_failure(monkeypatch, runner):
    from types import SimpleNamespace
    _patch_run_step(monkeypatch, fail_raws=('assert_text: "Saved"',))
    monkeypatch.setattr("app.execution.engine.settings",
                        SimpleNamespace(oracle="warn", images_dir=None, allow_destructive=False))
    monkeypatch.setattr(runner, "attach_evidence", lambda sr, *a, **k: sr)   # no browser: keep the note only
    flow = parse_flow_markdown('# T\n\n## S\n- goto: "https://x"\n- click: "Save"\n- assert_text: "Saved"\n')
    runner.run(flow, _ProbePage([1, 1]))
    assert runner._last_effect == 'the step before, click: "Save", changed nothing visible on the page'
    runner.run(parse_flow_markdown('# T\n\n## S\n- goto: "https://x"\n- click: "Save"\n'), _ProbePage([1, 2]))
    assert runner._last_effect == ""
