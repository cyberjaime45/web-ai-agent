"""test_table's sort-order judgement (numbers, dates, text)."""

from __future__ import annotations

import pytest

from app.skills.test_table import sort_order


@pytest.mark.parametrize("values, expected", [
    (["Adam", "ben", "Chloe"], "asc"),
    (["9", "10", "100"], "asc"),                         # numeric, not text order
    (["$1,200", "$950", "$20"], "desc"),
    (["2019-11-02", "2021-04-03", "2024-05-10"], "asc"),
    (["Mar 3, 2024", "Jan 9, 2024"], "desc"),
    (["b", "a", "c"], "none"),
    (["same", "same", ""], "equal"),
    (["Name ▲", "Other"], "asc"),
])
def test_sort_order(values, expected):
    assert sort_order(values) == expected
