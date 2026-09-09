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


def test_summary_is_empty_when_nothing_ran():
    assert execution_summary({}, 1.0) == []
    assert execution_summary({"deselected": [object()]}, 1.0) == []


def test_summary_splits_python_tests_from_flows():
    stats = {
        "passed": [
            _report("tests/x.py::test_a"),
            _flow_report("home_page.md", "Home Page"),
            _flow_report("booking_flow.md", "One Way Booking"),
        ],
        "failed": [_flow_report("booking_flow.md", "Round Trip Booking")],
        "rerun": [_flow_report("booking_flow.md", "Round Trip Booking")],
    }
    lines = execution_summary(stats, 42.8)
    text = "\n".join(lines)
    assert "Python tests:  1" in text
    assert "Flows:         3 (in 2 files)" in text
    assert "Passed:        3" in text
    assert "Failed:        1" in text
    assert "Skipped:       0" in text
    assert "Retries:       1" in text
    assert "Duration:      43s" in text


def test_summary_without_flows_shows_a_single_count():
    lines = execution_summary({"passed": [_report("tests/x.py::test_a")]}, 1.0)
    assert any(line.startswith("Tests:") for line in lines)
    assert not any(line.startswith("Flows:") for line in lines)


def test_summary_environment_line_uses_the_given_label():
    lines = execution_summary(
        {"passed": [_report("tests/x.py::test_a")]}, 1.0, "qa1 · firefox · headed"
    )
    assert any("qa1 · firefox · headed" in line for line in lines)


def test_summary_build_row_leads_when_given():
    report = {"passed": [_report("tests/x.py::test_a")]}
    lines = execution_summary(report, 1.0, "qa1 · chromium · headless", "Release 4.2 Smoke")
    assert lines[0].startswith("Build:") and lines[0].endswith("Release 4.2 Smoke")
    assert lines[1].startswith("Environment:")
    assert not any(line.startswith("Build:") for line in execution_summary(report, 1.0))


def test_summary_counts_healed_steps_only_when_present():
    healed = {
        "passed": [
            _report("tests/x.py::test_a", [("webagent_healings", 2)]),
            _report("tests/x.py::test_b", [("webagent_healings", 1)]),
        ]
    }
    lines = execution_summary(healed, 1.0)
    assert any(line.startswith("Healed steps:  3") for line in lines)

    clean = {"passed": [_report("tests/x.py::test_a"), _report("tests/x.py::test_b")]}
    assert not any("Healed steps" in line for line in execution_summary(clean, 1.0))


def test_summary_lists_the_slowest_tests_first():
    stats = {
        "passed": [
            _report("tests/x.py::test_fast", duration=0.2),
            _report("tests/x.py::test_slow", duration=5.0),
            _flow_report("booking_flow.md", "One Way Booking"),
            _report("tests/x.py::test_mid", duration=2.0),
        ]
    }
    stats["passed"][2].duration = 3.0
    lines = execution_summary(stats, 10.0)
    slowest_at = next(i for i, line in enumerate(lines) if line.startswith("Slowest:"))
    assert "test_slow  5.0s" in lines[slowest_at]
    assert "booking_flow.md » One Way Booking  3.0s" in lines[slowest_at + 1]
    assert "test_mid  2.0s" in lines[slowest_at + 2]
    assert len(lines) == slowest_at + 3  # capped at three entries


def test_summary_skips_slowest_for_a_single_test():
    lines = execution_summary({"passed": [_report("tests/x.py::test_a", duration=1.0)]}, 1.0)
    assert not any("Slowest" in line for line in lines)
