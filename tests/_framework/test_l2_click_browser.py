"""L2 click by partial text picks what the page shows, not what textContent glues
together — a react-day-picker calendar, as on the members-site booking page."""

from __future__ import annotations

import pytest

from app.execution.engine import FlowRunner
from app.flow.parser import parse_flow_markdown

_DAY = ('<td role="presentation"><button name="day" role="gridcell" type="button" onclick="pick(\'{d}\')">'
        '<time datetime="2026-10-{d:0>2}">{d}<div class="price">{price}</div></time></button></td>')
_EMPTY = '<td role="presentation"><div role="gridcell"></div></td>'
# Week 1 starts on Thursday with past days (no price): its textContent reads "123".
# Day 5's price holds "12" and comes before day 12 in the page.
_WEEK1 = _EMPTY * 4 + "".join(_DAY.format(d=d, price="") for d in (1, 2, 3))
_WEEK2 = "".join(_DAY.format(d=d, price="$12.4k" if d == 5 else "$7.9k") for d in range(4, 11))
_WEEK3 = "".join(_DAY.format(d=d, price="$7.9k") for d in range(11, 18))
PAGE = f"""
<table role="grid"><tbody>
<tr class="rdp-row">{_WEEK1}</tr><tr class="rdp-row">{_WEEK2}</tr><tr class="rdp-row">{_WEEK3}</tr>
</tbody></table>
<p id="picked">none</p>
<script>function pick(d) {{ document.getElementById('picked').textContent = 'Picked ' + d; }}</script>
"""


@pytest.fixture(autouse=True)
def short_timeouts(monkeypatch):
    from app.layers.deterministic import DeterministicRunner
    monkeypatch.setattr(DeterministicRunner, "_L1_TIMEOUT", 800)


def _run(page, tmp_path, steps: str):
    page.set_content(PAGE)
    runner = FlowRunner(artifacts_dir=str(tmp_path), flows_dir=tmp_path, provider=None)
    return runner.run(parse_flow_markdown("# T\n\n## Steps\n" + steps), page)


def test_a_day_with_a_price_is_clicked_not_the_row_whose_cells_read_12(page, tmp_path):
    result = _run(page, tmp_path, '- click: "12"\n- assert_text: "Picked 12"\n')
    assert result.steps[0].layer_used == 2                    # no exact match: the day reads "12 $7.9k"
    assert result.success, [s.message for s in result.steps]


def test_text_that_is_not_visible_as_written_is_not_clicked(page, tmp_path):
    result = _run(page, tmp_path, '- click: "123"\n')          # only week 1's glued textContent reads "123"
    assert not result.success
