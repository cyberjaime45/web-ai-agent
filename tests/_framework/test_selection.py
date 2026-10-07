"""Marker selection: one parser and one evaluator for `pytest -m` and the MCP
`list_flows(markers=...)`. No browser."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.flow.selection import (
    SelectionError,
    compile_selection,
    markers_from_ini,
    matches,
    registered_markers,
)

_KNOWN = ["non_destructive", "regression", "smoke"]
_REPO = Path(__file__).resolve().parents[2]


def test_registered_markers_come_from_the_ini_lines():
    assert registered_markers(["smoke: quick", "title(text): a title", "", "regression"]) == \
        ["regression", "smoke", "title"]
    assert {"smoke", "regression", "non_destructive"} <= set(markers_from_ini(_REPO / "pytest.ini"))


@pytest.mark.parametrize("expression, markers, selected", [
    ("smoke", ["smoke", "non_destructive"], True),
    ("smoke", ["regression"], False),
    ("smoke and non_destructive", ["smoke"], False),              # AND: every name
    ("smoke and non_destructive", ["non_destructive", "smoke"], True),
    ("smoke or regression", ["regression"], True),                # OR: any name
    ("not regression", [], True),                                 # an untagged flow
    ("smoke and not regression", ["smoke", "regression"], False),
    ("(smoke or regression) and non_destructive", ["regression", "non_destructive"], True),
])
def test_expressions_follow_pytest_m(expression, markers, selected):
    assert matches(compile_selection(expression, _KNOWN), markers) is selected


@pytest.mark.parametrize("expression, message", [
    ("smokee", "Unknown marker 'smokee'"),
    ("smoke or nightly", "Unknown marker 'nightly'"),
    ("smoke and", "Invalid marker expression"),
])
def test_unknown_names_and_bad_syntax_are_errors(expression, message):
    with pytest.raises(SelectionError, match=message):
        compile_selection(expression, _KNOWN)
