"""Flaky classification — merge a failed flow with one rerun, section by section.

With RERUN_FAILED=true, a flow with a failed section runs once more, whole,
in a fresh browser context (sections can depend on earlier ones — a login
section before the pages it opens). Then, per ``## section``:

  passed the first time      the first attempt's steps are kept
  failed, then passed        the rerun's steps: the report says "passed on retry"
  failed both times          the rerun's steps: a consistent failure

A section that passed the first time is never replaced by the rerun, so a
rerun can only turn red into green-on-retry, never green into red. The first
attempt's error and likely cause (its diagnosis verdict) of every retried
section are kept for the report, so "passed on retry" after a server failure
reads differently from a locator that was slow once. A flow whose failures
are all the flow's own (``framework``: an unset placeholder, a missing
sub-flow) is not rerun — it would fail the same way. Console and
network entries follow their section: each attempt contributes the entries
recorded inside the time windows of the sections taken from it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.schemas.actions import FlowResult, StepResult, section_runs


def _failed(steps: list[StepResult]) -> list[StepResult]:
    return [s for s in steps if s.fails_flow]


def failed_sections(result: FlowResult) -> list[int]:
    """Indexes of the sections with a failed (non-skipped) step."""
    return [i for i, (_, steps) in enumerate(section_runs(result.steps)) if _failed(steps)]


def verdicts(result: FlowResult) -> dict[int, str]:
    """Failed section index → the diagnosis verdict of its failing step."""
    return {i: _verdict(steps) for i, (_, steps) in enumerate(section_runs(result.steps)) if _failed(steps)}


# A failure the flow or its setup caused (an unset placeholder, a missing
# sub-flow) fails the same way every time: a rerun proves nothing.
NO_RERUN = frozenset({"framework"})


def worth_rerunning(result: FlowResult) -> list[int]:
    """The failed sections a rerun could tell something about."""
    return [i for i, v in verdicts(result).items() if v not in NO_RERUN]


def _verdict(steps: list[StepResult]) -> str:
    failed = _failed(steps)
    ev = failed[-1].evidence if failed else None
    return (ev.diagnosis or {}).get("verdict", "") if ev else ""


def _window(steps: list[StepResult]) -> tuple[int, int] | None:
    stamped = [s for s in steps if s.started_at]
    if not stamped:
        return None
    return round(min(s.started_at for s in stamped) * 1000), round(max(s.ended_at for s in stamped) * 1000)


@dataclass
class Merged:
    result:  FlowResult
    retried: dict[int, str] = field(default_factory=dict)   # section index → first attempt's error
    first_verdicts: dict[int, str] = field(default_factory=dict)   # section index → first attempt's likely cause
    console: list[dict] = field(default_factory=list)
    network: list[dict] = field(default_factory=list)

    @property
    def passed_on_retry(self) -> int:
        runs = section_runs(self.result.steps)
        return sum(1 for i in self.retried if i < len(runs) and not _failed(runs[i][1]))


def merge(first: FlowResult, first_capture: tuple[list, list],
          rerun: FlowResult, rerun_capture: tuple[list, list]) -> Merged:
    """Combine two attempts of the same flow (see the module docstring)."""
    a, b = section_runs(first.steps), section_runs(rerun.steps)
    retry = set(failed_sections(first))
    if [name for name, _ in a] != [name for name, _ in b]:
        # The rerun did not reach the same sections (it crashed early): keep
        # the first attempt and still say which sections were retried.
        return Merged(first, {i: _error(a[i][1]) for i in retry}, {i: _verdict(a[i][1]) for i in retry},
                      list(first_capture[0]), list(first_capture[1]))

    steps: list[StepResult] = []
    windows: list[tuple[int, tuple[int, int]]] = []   # (attempt 0 | 1, window)
    retried: dict[int, str] = {}
    first_verdicts: dict[int, str] = {}
    for i, ((_, sa), (_, sb)) in enumerate(zip(a, b)):
        chosen, attempt = (sb, 1) if i in retry else (sa, 0)
        if i in retry:
            retried[i], first_verdicts[i] = _error(sa), _verdict(sa)
        steps.extend(chosen)
        if win := _window(chosen):
            windows.append((attempt, win))

    merged = FlowResult(flow_name=first.flow_name, steps=steps)
    failed = _failed(steps)
    merged.success = not failed
    merged.error = "\n".join(s.message for s in failed)

    captures = (first_capture, rerun_capture)

    def keep(kind: int) -> list[dict]:
        return sorted((e for attempt, (lo, hi) in windows for e in captures[attempt][kind]
                       if e.get("ts") is not None and lo <= e["ts"] <= hi),
                      key=lambda e: e["ts"])

    return Merged(merged, retried, first_verdicts, keep(0), keep(1))


def _error(steps: list[StepResult]) -> str:
    """The section's failure message, without Playwright's call log."""
    failed = _failed(steps)
    return failed[-1].message.split("Call log:")[0].strip() if failed else ""
