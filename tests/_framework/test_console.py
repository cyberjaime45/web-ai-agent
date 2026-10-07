"""Console reporting — flow labeling, duration formatting, summary lines."""

from types import SimpleNamespace

from app.observability.console import execution_summary, flow_info, flow_label, format_duration


def _report(
    nodeid: str, props: list[tuple] | None = None, duration: float = 0.0
) -> SimpleNamespace:
    return SimpleNamespace(nodeid=nodeid, user_properties=props or [], duration=duration)


# ── flow_info ─────────────────────────────────────────────────────────────


def test_flow_info_prefers_user_properties():
    props = [("webagent_flow_file", "home_page.md"), ("webagent_flow_name", "Home Page")]
    assert flow_info("tests/x.py::test_flow[home::Home Page]", props) == (
        "home_page.md",
        "Home Page",
    )


def test_flow_info_falls_back_to_the_flow_file_nodeid():
    nodeid = "tests/fms/flows/production_smoke.md::FMS MVC Smoke Tests"
    assert flow_info(nodeid, None) == ("production_smoke.md", "FMS MVC Smoke Tests")


def test_flow_info_rejects_regular_tests():
    assert flow_info("tests/x.py::test_footer_navigates_to_the_blog", None) is None
    assert flow_info("tests/x.py::test_parametrized[chromium-1440]", None) is None


def test_flow_label_drops_a_missing_side():
    assert flow_label(("home_page.md", "Home Page")) == "home_page.md » Home Page"
    assert flow_label(("", "Inline Check")) == "Inline Check"  # --flow / --flow_file items
    assert flow_label(("home_page.md", "")) == "home_page.md"


# ── format_duration ───────────────────────────────────────────────────────


def test_durations_scale_with_magnitude():
    assert format_duration(1.23) == "1.2s"
    assert format_duration(42.8) == "43s"
    assert format_duration(95) == "1m35s"


# ── execution_summary ─────────────────────────────────────────────────────


def _flow_report(file: str, name: str) -> SimpleNamespace:
    return _report(
        f"tests/x/flows/{file}::{name}",
        [("webagent_flow_file", file), ("webagent_flow_name", name)],
    )


def _totals(passed=0, failed=0, skipped=0, errors=0) -> dict:
    total = passed + failed + skipped + errors
    return {"total": total, "passed": passed, "failed": failed,
            "skipped": skipped, "errors": errors}


def _rows(lines: list[str]) -> dict[str, str]:
    return {name: value.strip()
            for name, sep, value in (line.partition(":") for line in lines) if sep}


def test_summary_is_empty_without_report_totals():
    flow = {"passed": [_flow_report("home_page.md", "Home Page")]}
    assert execution_summary(flow, None, 1.0) == []
    assert execution_summary({"deselected": [object()]}, _totals(), 1.0) == []


def test_summary_counts_test_cases_from_the_report_totals():
    """One flow of 31 sections, one failed: the console agrees with summary.json."""
    stats = {"failed": [_flow_report("production_smoke.md", "FMS MVC Smoke Tests")]}
    lines = execution_summary(stats, _totals(passed=30, failed=1), 89.0,
                              "production · chromium · headless", "FMS MVC Smoke Test")
    assert lines == [
        "Build:        FMS MVC Smoke Test",
        "Environment:  production · chromium · headless",
        "Flows:        1 (in 1 file)",
        "Passed:       30 of 31 tests",
        "Failed:       1",
        "Skipped:      0",
        "Duration:     1m29s",
    ]


def test_summary_counts_flows_and_files_and_folds_errors_into_failed():
    stats = {
        "passed": [_flow_report("home_page.md", "Home Page"),
                   _flow_report("booking_flow.md", "One Way Booking")],
        "failed": [_flow_report("booking_flow.md", "Round Trip Booking")],
        "rerun": [_flow_report("booking_flow.md", "Round Trip Booking")],
    }
    rows = _rows(execution_summary(stats, _totals(passed=8, failed=1, errors=1, skipped=2), 42.8))
    assert rows["Flows"] == "3 (in 2 files)"
    assert (rows["Passed"], rows["Failed"], rows["Skipped"]) == ("8 of 10 tests", "2", "2")
    assert rows["Retries"] == "1"
    assert rows["Duration"] == "43s"


def test_summary_has_no_flows_row_when_no_flow_ran():
    rows = _rows(execution_summary({"passed": [_report("tests/x.py::test_a")]}, _totals(passed=1), 1.0))
    assert "Flows" not in rows and "Python tests" not in rows and "Test cases" not in rows
    assert rows["Passed"] == "1 of 1 test"


def test_summary_build_row_leads_when_given():
    stats = {"passed": [_flow_report("home_page.md", "Home Page")]}
    lines = execution_summary(stats, _totals(passed=1), 1.0, "qa1 · chromium · headless", "Release 4.2")
    assert lines[0].startswith("Build:") and lines[0].endswith("Release 4.2")
    assert lines[1].startswith("Environment:") and lines[1].endswith("qa1 · chromium · headless")
    assert not any(line.startswith("Build:") for line in execution_summary(stats, _totals(passed=1), 1.0))


def test_summary_counts_healed_steps_and_retry_passes_only_when_present():
    props = [("webagent_flow_file", "a.md"), ("webagent_flow_name", "A")]
    healed = {"passed": [
        _report("tests/a.md::A", [*props, ("webagent_healings", 2), ("webagent_passed_on_retry", 1)]),
        _report("tests/b.md::B", [("webagent_healings", 1)]),
    ]}
    rows = _rows(execution_summary(healed, _totals(passed=2), 1.0))
    assert rows["Healed steps"].startswith("3 (informational")       # automatic recovery: not a warning
    assert rows["Passed on retry"].startswith("1 section(s)")

    clean = {"passed": [_flow_report("a.md", "A"), _flow_report("b.md", "B")]}
    rows = _rows(execution_summary(clean, _totals(passed=2), 1.0))
    assert "Healed steps" not in rows and "Passed on retry" not in rows


def test_summary_lists_the_slowest_flows_first():
    stats = {"passed": [_flow_report(f"{n}.md", n.title()) for n in ("fast", "slow", "mid", "tiny")]}
    for report, seconds in zip(stats["passed"], (0.2, 5.0, 2.0, 0.1)):
        report.duration = seconds
    stats["passed"].append(_report("tests/x.py::test_py", duration=9.0))   # not a flow
    lines = execution_summary(stats, _totals(passed=5), 10.0)
    slowest_at = next(i for i, line in enumerate(lines) if line.startswith("Slowest:"))
    assert [line.removeprefix("Slowest:").strip() for line in lines[slowest_at:]] == [
        "slow.md » Slow  5.0s", "mid.md » Mid  2.0s", "fast.md » Fast  0.2s"]


def test_summary_skips_slowest_for_a_single_flow():
    stats = {"passed": [_flow_report("a.md", "A")]}
    assert not any("Slowest" in line for line in execution_summary(stats, _totals(passed=4), 1.0))


def test_summary_shows_warnings_and_an_interrupted_run_only_when_they_apply():
    stats = {"passed": [_flow_report("a.md", "A")]}
    rows = _rows(execution_summary(stats, {**_totals(passed=3), "warnings": 2}, 1.0, status="passed_with_warnings"))
    assert rows["Passed"] == "3 of 3 tests (2 with warnings)" and rows["Warnings"].startswith("2 passed tests have warnings")
    assert "Interrupted" not in rows
    rows = _rows(execution_summary(stats, {**_totals(passed=1), "warnings": 0}, 1.0, status="interrupted"))
    assert "Warnings" not in rows and rows["Interrupted"].startswith("the run stopped early")


def test_summary_says_the_result_first_and_counts_tests_apart_from_warnings():
    stats = {"passed": [_flow_report("a.md", "A")]}
    totals = {**_totals(passed=1), "warnings": 1, "warning_count": 3}
    rows = _rows(execution_summary(stats, totals, 1.0, headline="All tests passed. 1 test has warnings to review."))
    assert rows["Result"] == "All tests passed. 1 test has warnings to review."
    assert rows["Passed"] == "1 of 1 test (1 with warnings)"                  # a warned test still counts as passed
    assert rows["Warnings"].startswith("1 passed test has warnings (3 warnings)")   # tests, then findings


def test_summary_of_a_run_where_every_test_was_skipped_shows_no_pass():
    rows = _rows(execution_summary({"skipped": [_flow_report("a.md", "A")]}, _totals(skipped=2), 1.0))
    assert rows["Passed"] == "0 — no test ran" and rows["Skipped"] == "2"
