"""Live console reporting — one line per finished test, plus a run summary.

Replaces pytest's dot-per-test progress with output that names what just ran:

    tests/fms/flows/production_smoke.md
      ✓ production_smoke.md » FMS MVC Smoke Tests  3m00s
    tests/framework/test_reporter.py
      ✓ test_generate_report_html_references_assets  0.0s

Everything is derived from data pytest already carries through its lifecycle
hooks — no extra I/O, parsing, or Playwright calls. The reporter is adopted
in place (`install_console_reporter`) by swapping the class of the standard
``TerminalReporter`` instance, so registration, accumulated state, failure
sections, and the exit line all keep working exactly as stock pytest.

Stock output is preserved whenever it is the better tool: ``-v`` and ``-q``
disable the takeover, as does another console plugin (e.g. pytest-sugar)
owning the reporter.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from _pytest.terminal import TerminalReporter

if TYPE_CHECKING:
    from collections.abc import Sequence

    import pytest

# user_properties keys stamped by FlowItem (conftest.py) — they ride on the
# TestReport, so both the live line and the summary can read them.
FLOW_FILE_PROP = "webagent_flow_file"
FLOW_NAME_PROP = "webagent_flow_name"
HEALINGS_PROP = "webagent_healings"

# category (from pytest_report_teststatus) → console glyph + markup
_GLYPHS: dict[str, tuple[str, dict[str, bool]]] = {
    "passed": ("✓", {"green": True}),
    "failed": ("✗", {"red": True}),
    "error": ("✗", {"red": True}),
    "skipped": ("↷", {"yellow": True}),
    "xfailed": ("↷", {"yellow": True}),
    "xpassed": ("✓", {"yellow": True}),
    "rerun": ("↻", {"yellow": True}),
}

# Result categories that represent test outcomes; TerminalReporter.stats also
# holds non-report entries under other keys ("deselected", "warnings", "").
_OUTCOMES = ("passed", "failed", "error", "skipped", "xfailed", "xpassed")

# How many of the slowest tests the execution summary lists.
_SLOWEST_N = 3


def flow_info(nodeid: str, user_properties: Sequence[tuple] | None) -> tuple[str, str] | None:
    """(flow file, flow name) when the report came from a markdown flow.

    The flow item stamps both onto ``user_properties`` at runtest. Reports
    from phases that never ran the test body (setup skips/errors) carry no
    properties, so fall back to the collected nodeid — ``path/to/file.md::name``.
    """
    props = dict(user_properties or ())
    if FLOW_FILE_PROP in props:
        return str(props[FLOW_FILE_PROP]), str(props.get(FLOW_NAME_PROP, ""))
    base, sep, case = nodeid.rpartition("::")
    if sep and base.endswith(".md"):
        return base.rpartition("/")[2], case
    return None


def flow_label(info: tuple[str, str]) -> str:
    """``file » name``; inline flows have no file, parsed-only reports no name."""
    file_part, name = info
    return f"{file_part} » {name}" if file_part and name else (name or file_part)


def format_duration(seconds: float) -> str:
    if seconds < 10:
        return f"{seconds:.1f}s"
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes}m{secs:02d}s"


class WebAgentTerminalReporter(TerminalReporter):
    """Stock reporter with the per-test output swapped for named lines.

    Instances are never constructed — ``install_console_reporter`` re-classes
    the live ``TerminalReporter``, so ``__init__`` state and plugin
    registration carry over untouched. Only the two writing hooks differ;
    collection status, failure sections, warnings, and the final stats line
    are inherited.
    """

    def _wa_write_header(self, nodeid: str) -> None:
        # The nodeid names the collected file (the .md flow or test module);
        # report.location[0] would name where the item class is *defined*.
        fspath = nodeid.partition("::")[0]
        if not fspath:
            return  # --flow / --flow_file items hang off the session: no file to name
        if fspath != getattr(self, "_wa_last_fspath", None):
            first = not hasattr(self, "_wa_last_fspath")
            self._wa_last_fspath = fspath
            self.ensure_newline()
            if not first:
                self._tw.line()
            self._tw.line(fspath, bold=True)
            self.flush()

    def pytest_runtest_logstart(self, nodeid: str, location) -> None:
        """Name the file before its first test runs — the 'currently running' cue."""
        # Under xdist many files start interleaved and results print their own
        # headers; start-time headers would mostly sit empty. Sequential runs
        # keep them — they show what is running before the first result lands.
        if not self.config.pluginmanager.hasplugin("dsession"):
            self._wa_write_header(nodeid)

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        # Bookkeeping mirrored from TerminalReporter — stats feed the -ra
        # summaries and the exit line; only the writing differs.
        self._tests_ran = True
        category, letter, word = self.config.hook.pytest_report_teststatus(
            report=report, config=self.config
        )
        self._add_stats(category, [report])
        if not letter and not word:
            return  # passed setup/teardown — silent, same as stock pytest
        self._progress_nodeids_reported.add(report.nodeid)
        # Under xdist, starts and finishes interleave across files — make sure
        # the line lands under the header of the file it belongs to.
        self._wa_write_header(report.nodeid)

        glyph, markup = _GLYPHS.get(category, ("·", {}))
        info = flow_info(report.nodeid, getattr(report, "user_properties", None))
        if info is not None:
            label = flow_label(info)
        else:
            label = report.location[2]  # test function name (with parameters)

        self.ensure_newline()
        self._tw.write(f"  {glyph} ", **markup)
        self._tw.write(label)
        if report.when == "call":
            self._tw.write(f"  {format_duration(report.duration)}", light=True)
        if self._show_progress_info:
            progress = self._get_progress_information_message()
            padding = self._tw.fullwidth - self._tw.width_of_current_line - len(progress)
            self._tw.write(" " * max(padding, 1) + progress, light=True)
        self._tw.line()
        self.flush()

    def _write_progress_information_filling_space(self) -> None:
        """Progress is already printed on every line; the deferred fill-space
        write (stock pytest's end-of-loop 100%) would land on a line of its own.
        """


def install_console_reporter(config: pytest.Config) -> None:
    """Adopt the live per-test console output. Idempotent; controller only.

    Skipped whenever stock output is the better fit: quiet/verbose runs,
    xdist workers, no terminal plugin, or a reporter owned by another plugin.
    """
    if hasattr(config, "workerinput"):
        return
    standard = config.pluginmanager.get_plugin("terminalreporter")
    if standard is None or type(standard) is not TerminalReporter:
        return
    if config.get_verbosity() != 0:
        return
    # Re-classing alone is not enough: pluggy bound the stock methods at
    # registration time, so re-register the (re-classed) instance to make the
    # hook manager pick up the overrides. All accumulated state carries over.
    config.pluginmanager.unregister(standard)
    standard.__class__ = WebAgentTerminalReporter
    config.pluginmanager.register(standard, "terminalreporter")


def execution_summary(
    stats: dict[str, list],
    duration_s: float,
    environment: str | None = None,
    build_name: str | None = None,
) -> list[str]:
    """The end-of-run summary block, from counters pytest already keeps.

    One pass over ``TerminalReporter.stats`` — no filesystem or report-file
    access. Returns no lines when nothing ran (collect-only, full deselect).
    *environment* is a preformatted label (e.g. ``staging · chromium · headless``);
    *build_name* is the run label (BUILD_NAME or its fallback).
    """
    counts = {category: len(stats.get(category, [])) for category in _OUTCOMES}
    total = sum(counts.values())
    if total == 0:
        return []

    flow_files: set[str] = set()
    flows = 0
    healings = 0
    timed: list[tuple[float, str]] = []
    for category in _OUTCOMES:
        for report in stats.get(category, []):
            props = getattr(report, "user_properties", None)
            info = flow_info(report.nodeid, props)
            if info is not None:
                flows += 1
                flow_files.add(info[0])
                label = flow_label(info)
            else:
                label = report.nodeid.rpartition("::")[2]
            healings += int(dict(props or ()).get(HEALINGS_PROP, 0))
            timed.append((float(getattr(report, "duration", 0.0) or 0.0), label))

    rows: list[tuple[str, str]] = []
    if build_name:
        rows.append(("Build", build_name))
    if environment:
        rows.append(("Environment", environment))
    if flows:
        rows.append(("Python tests", str(total - flows)))
        rows.append(("Flows", f"{flows} (in {len(flow_files)} files)"))
    else:
        rows.append(("Tests", str(total)))
    rows.append(("Passed", str(counts["passed"] + counts["xpassed"])))
    rows.append(("Failed", str(counts["failed"] + counts["error"])))
    rows.append(("Skipped", str(counts["skipped"] + counts["xfailed"])))
    if retries := len(stats.get("rerun", [])):
        rows.append(("Retries", str(retries)))
    if healings:
        rows.append(("Healed steps", f"{healings} (resolved by L2/L3)"))
    rows.append(("Duration", format_duration(duration_s)))
    if total >= 2:
        top = sorted(timed, key=lambda pair: -pair[0])[:_SLOWEST_N]
        for index, (duration, label) in enumerate(top):
            rows.append(("Slowest" if index == 0 else "", f"{label}  {format_duration(duration)}"))

    width = max(len(name) for name, _ in rows if name) + 2
    return [f"{(name + ':') if name else '':<{width}} {value}" for name, value in rows]
