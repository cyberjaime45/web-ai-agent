"""L2 click resolution picks the one control a step names, or fails saying why.

Each page here makes L1 miss (no exact button/link/text name) so L2 decides.
The members-site case: a click on "Book" with no Book control on the page
used to press the share button named "Facebook" (a substring of its name).
"""

from __future__ import annotations

import pytest

from app.execution.engine import FlowRunner
from app.flow.parser import parse_flow_markdown

_SHARE = '<div class="share"><button><img alt="Facebook" src="data:,"></button><button><img alt="Twitter" src="data:,"></button></div>'
_BOOKED = "<p>You already have one or more flights booked on this day.</p>"
_LOG = '<p id="log">nothing</p><script>const log = t => document.getElementById("log").textContent = t;</script>'


@pytest.fixture(autouse=True)
def quick(monkeypatch):
    from app.layers.deterministic import DeterministicRunner
    from app.layers.locator import FallbackLocator
    monkeypatch.setattr(DeterministicRunner, "_L1_TIMEOUT", 600)
    monkeypatch.setattr(FallbackLocator, "_RESOLVE_TIMEOUT_S", 0.4)


def _run(page, tmp_path, body: str, steps: str):
    page.set_content(body + _LOG)
    runner = FlowRunner(artifacts_dir=str(tmp_path), flows_dir=tmp_path, provider=None)
    return runner.run(parse_flow_markdown("# T\n\n## Steps\n" + steps), page)


def _error(result) -> str:
    return next(s.error or s.message for s in result.steps if not s.success)


def test_a_substring_of_another_name_or_of_text_is_never_a_target(page, tmp_path):
    result = _run(page, tmp_path, _SHARE + _BOOKED, '- click: "Book"\n')
    assert not result.success
    assert page.locator("#log").inner_text() == "nothing"
    assert 'no visible control is named "Book"' in _error(result)


def test_a_whole_word_match_is_clicked_and_recorded(page, tmp_path):
    body = _SHARE + _BOOKED + '<button onclick="log(\'booked it\')">Book now</button>'
    result = _run(page, tmp_path, body, '- click: "book"\n- assert_text: "booked it"\n')
    assert result.success, _error(result)
    step = result.steps[0]
    assert step.layer_used == 2
    assert step.resolved.startswith('button "Book now" (button) — whole-word match of a control for "book"')


def test_an_exact_name_beats_a_whole_word_one(page, tmp_path):
    body = '<button onclick="log(\'later\')">Book later</button><a href="#" onclick="log(\'exact\')">BOOK</a>'
    result = _run(page, tmp_path, body, '- click: "book"\n- assert_text: "exact"\n')
    assert result.success, _error(result)
    assert result.steps[0].resolved.startswith('link "BOOK"')


def test_duplicate_labels_are_ambiguous_and_nothing_is_clicked(page, tmp_path):
    body = '<button onclick="log(\'a\')">Book now</button><button onclick="log(\'b\')">Book today</button>'
    result = _run(page, tmp_path, body, '- click: "book"\n')
    assert not result.success and page.locator("#log").inner_text() == "nothing"
    error = _error(result)
    assert '"book" is ambiguous — 2 visible, enabled controls match' in error
    assert 'button "Book now"' in error and 'button "Book today"' in error


def test_hidden_or_disabled_matches_are_skipped_or_reported(page, tmp_path):
    hidden_and_live = ('<button style="display:none">Book now</button><button disabled>Book later</button>'
                       '<button onclick="log(\'live\')">Book today</button>')
    result = _run(page, tmp_path, hidden_and_live, '- click: "book"\n- assert_text: "live"\n')
    assert result.success, _error(result)
    assert "2 hidden or disabled match(es) ignored" in result.steps[0].resolved

    only_disabled = '<button disabled>Book</button><button onclick="log(\'other\')">Booking help</button>'
    result = _run(page, tmp_path, only_disabled, '- click: "book"\n')
    assert not result.success and page.locator("#log").inner_text() == "nothing"   # never falls to a looser match
    assert 'found button "Book" (disabled) for "book", but none can be clicked' in _error(result)


def test_an_element_styled_as_clickable_counts_plain_text_does_not(page, tmp_path):
    body = (_BOOKED + '<div style="cursor:pointer" onmousedown="log(\'card\')"><span>Select</span> this jet</div>'
            '<p>Select a date first</p>')
    result = _run(page, tmp_path, body, '- click: "select"\n- assert_text: "card"\n')
    assert result.success, _error(result)
    assert "element styled as clickable" in result.steps[0].resolved


def test_word_similarity_keeps_a_legitimate_rename_working(page, tmp_path):
    body = '<button onclick="log(\'signed\')">Sign up today</button><button>Cancel</button>'
    result = _run(page, tmp_path, body, '- click: "Sign up now"\n- assert_text: "signed"\n')
    assert result.success, _error(result)
    assert "closest wording of a control" in result.steps[0].resolved
