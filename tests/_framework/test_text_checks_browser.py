"""Text checks match visible elements only — in L1 and in the L2 fallback."""

from __future__ import annotations

from app.execution.engine import FlowRunner
from app.flow.parser import parse_flow_markdown

PAGE = """
<nav><ul style="display:none"><li>Logs</li><li>Reports</li></ul></nav>
<main><h1>Integrations</h1><a href="#">Logs</a><p hidden>Archived</p>
<script>const label = "Secret setting";</script></main>
"""


import pytest


@pytest.fixture(autouse=True)
def short_timeouts(monkeypatch):
    """The failing checks below would each wait out L1's 5 s."""
    from app.layers.deterministic import DeterministicRunner
    monkeypatch.setattr(DeterministicRunner, "_L1_TIMEOUT", 800)


def _run(page, tmp_path, steps: str):
    page.set_content(PAGE)
    runner = FlowRunner(artifacts_dir=str(tmp_path), flows_dir=tmp_path, provider=None)
    return runner.run(parse_flow_markdown("# T\n\n## Steps\n" + steps), page)


def test_a_hidden_first_match_does_not_hide_a_visible_one(page, tmp_path):
    result = _run(page, tmp_path, '- assert_text: "Logs"\n- assert_visible: "Logs"\n- wait_for_text: "Logs"\n')
    assert result.success
    assert all(s.layer_used == 1 and s.duration < 0.5 for s in result.steps)   # L1 at once, no timeout + heal


def test_text_that_is_only_hidden_or_in_a_script_fails(page, tmp_path):
    for text in ("Archived", "Secret setting"):
        result = _run(page, tmp_path, f'- assert_text: "{text}"\n')
        assert not result.success, text                   # the raw HTML has it; the page does not show it


def test_absence_checks_ignore_hidden_copies(page, tmp_path):
    result = _run(page, tmp_path, '- assert_not_text: "Reports"\n- assert_hidden: "Archived"\n')
    assert result.success
    shown = _run(page, tmp_path, '- assert_not_text: "Logs"\n')   # one copy hidden, one visible
    assert not shown.success
