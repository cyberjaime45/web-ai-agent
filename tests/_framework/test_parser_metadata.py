"""Parser: the # H1 is the suite title; `markers:` lines tag tests, not steps."""

from __future__ import annotations

from app.flow.parser import parse_flow_markdown

SAMPLE = """# Home Page

This is the home page for the marketing site

markers: site

## Test One

markers: smoke

- goto: "https://wheelsup.com/"
- wait_load

## Test Two

marker: another_tag, regression

- goto: "https://wheelsup.com/"

## Notes
markers: ignored_in_metadata
- not a step either
"""


def test_h1_is_both_title_and_name():
    flow = parse_flow_markdown(SAMPLE, name="sample_run")
    assert flow.title == "Home Page"
    assert flow.name == "Home Page"


def test_without_h1_title_is_none_and_name_falls_back():
    flow = parse_flow_markdown('## Steps\n- goto: "https://example.com"\n', name="login")
    assert flow.title is None
    assert flow.name == "login"
    assert flow.markers == [] and flow.section_markers == {}


def test_markers_are_file_wide_or_per_section():
    flow = parse_flow_markdown(SAMPLE)
    assert flow.markers == ["site"]
    assert flow.section_markers == {
        "Test One": ["smoke"],
        "Test Two": ["another_tag", "regression"],
    }


def test_marker_lines_are_not_steps():
    flow = parse_flow_markdown(SAMPLE)
    assert [a.raw for a in flow.actions] == [
        'goto: "https://wheelsup.com/"', "wait_load", 'goto: "https://wheelsup.com/"',
    ]
    assert [a.section for a in flow.actions] == ["Test One", "Test One", "Test Two"]
