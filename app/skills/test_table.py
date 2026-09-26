"""test_table — does the table behave like a table?

    - test_table
    - test_table: "table=2" | "sort=false" | "paginate=false" | "open=false"

Reads the first visible table (``table=N`` for another; ``<table>``,
``role=grid`` or ``role=table``), then, through ordinary child steps:

    structure   header row present; rows, or an empty-state message
    sort        click the first sortable header (aria-sort, a button inside,
                a sort class or a pointer cursor) and check that column is now
                in ascending or descending order — numbers, dates and text
                compared as such; clicked twice when the first click changes
                nothing
    paginate    press Next: the rows change; press Previous: they come back
    open        press the first link or button in the first row: the URL
                changes or a dialog opens; then Back or Escape

Every finding is a warning (these are heuristics: equal values, server-side
paging, virtualised rows can all look "unchanged" — reported as
inconclusive). A control the safety policy blocks (a row's "Delete") is
never pressed.
"""

from __future__ import annotations

import datetime
import re
import time

from app.agent.observer import EMPTY_STATE_RE, PREV_NAMES
from app.schemas.actions import ActionType, Check
from app.skills.base import SkillContext, info, skill

MAX_ROWS = 50
_ARROWS = "▲▼↑↓⇅⬆⬇△▽"
_NUMBER_RE = re.compile(r"[$€£]?\s*(-?[\d,]*\.?\d+)\s*%?")
_DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%b %d, %Y", "%B %d, %Y", "%d %b %Y", "%d %B %Y")

_TABLE_JS = r"""
(idx) => {
  const vis = el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const text = el => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
  const name = el => (el.getAttribute('aria-label') || text(el)).trim();
  const tables = [...document.querySelectorAll('table, [role="grid"], [role="table"]')]
    .filter(t => vis(t) && !t.parentElement.closest('table, [role="grid"], [role="table"]'));
  const t = tables[idx];
  if (!t) return null;
  const rowsOf = [...t.querySelectorAll('tr, [role="row"]')].filter(vis);
  const isHeader = r => !!r.closest('thead') || [...r.children].every(c =>
    c.tagName === 'TH' || c.getAttribute('role') === 'columnheader');
  const headerRow = rowsOf.find(isHeader);
  const sortable = h => h.hasAttribute('aria-sort') || !!h.querySelector('button, a, [role="button"]')
    || /sort/i.test(`${h.className} ${h.getAttribute('onclick') || ''}`) || getComputedStyle(h).cursor === 'pointer';
  const headers = headerRow ? [...headerRow.children].map(h => {
    const btn = h.querySelector('button, a, [role="button"]');
    return { name: text(h), click: btn ? name(btn) : text(h), sortable: sortable(h) };
  }) : [];
  const placeholder = r => r.children.length === 1 && r.children[0].colSpan > 1;   // "No records" row
  const body = rowsOf.filter(r => !isHeader(r) && !placeholder(r));
  const cells = body.slice(0, __MAX_ROWS__).map(r => [...r.children].map(text));
  const control = body[0] && [...body[0].querySelectorAll('a[href], button, [role="button"], [role="link"]')].find(vis);
  return {
    tables: tables.length, headers, rows: body.length, cells,
    rowControl: control ? { name: name(control), role: control.tagName === 'A' || control.getAttribute('role') === 'link' ? 'link' : 'button' } : null,
    text: text(t).slice(0, 200),
  };
}
""".replace("__MAX_ROWS__", str(MAX_ROWS))


def _key(value: str) -> tuple:
    v = value.strip().strip(_ARROWS).strip()
    if m := _NUMBER_RE.fullmatch(v):
        try:
            return (0, float(m.group(1).replace(",", "")))
        except ValueError:
            pass
    for fmt in _DATE_FORMATS:
        try:
            return (1, datetime.date(*time.strptime(v, fmt)[:3]).toordinal())
        except ValueError:
            continue
    return (2, v.casefold())


def sort_order(values: list[str]) -> str:
    """``asc`` / ``desc`` / ``equal`` (nothing to judge) / ``none`` (unsorted)."""
    keys = [_key(v) for v in values if v.strip()]
    if len(set(keys)) < 2:
        return "equal"
    if len({k[0] for k in keys}) > 1:                 # mixed kinds: compare as text
        keys = [(2, v.strip().casefold()) for v in values if v.strip()]
    if keys == sorted(keys):
        return "asc"
    if keys == sorted(keys, reverse=True):
        return "desc"
    return "none"


def _column(read: dict, col: int) -> list[str]:
    return [row[col] for row in read["cells"] if col < len(row)]


def _sort(sc: SkillContext, read: dict, idx: int) -> list[Check]:
    header = next((h for h in read["headers"] if h["sortable"] and h["click"]
                   and sc.policy.allows(h["click"], role="columnheader")), None)
    if header is None:
        return [info("sorting", "no sortable column header found")]
    col = read["headers"].index(header)
    label = header["name"].strip(_ARROWS).strip() or header["click"]
    before = _column(read, col)
    for _attempt in range(2):
        if not sc.run(ActionType.CLICK, header["click"]).success:
            return []
        sc.run(ActionType.WAIT_STABLE)
        after = _column(sc.evaluate(_TABLE_JS, idx) or read, col)
        if after != before:
            break
    order = sort_order(after)
    if order == "equal":
        return [info("sorting", f"'{label}' has too few distinct values to judge")]
    ok = order in ("asc", "desc") and after != before
    detail = (f"'{label}' sorted {'ascending' if order == 'asc' else 'descending'}" if ok else
              f"clicking '{label}' changed nothing" if after == before else
              f"after clicking '{label}' the column is not in order")
    return [Check("sorting works", ok, "warn", detail)]


def _paginate(sc: SkillContext, read: dict, idx: int) -> list[Check]:
    nxt = sc.observe(fresh=True).paging_control()
    if nxt is None or not sc.policy.allows(nxt.name, role=nxt.role):
        return [info("pagination", "no next-page control found")]
    first = read["cells"][:1]
    if not sc.run(ActionType.CLICK, nxt.name).success:
        return []
    sc.run(ActionType.WAIT_STABLE)
    moved = (sc.evaluate(_TABLE_JS, idx) or {}).get("cells", [])[:1]
    checks = [Check("pagination works", moved != first, "warn",
                    f"'{nxt.name}' shows other rows" if moved != first else f"'{nxt.name}' changed nothing")]
    prev = sc.observe(fresh=True).paging_control(PREV_NAMES)
    if moved != first and prev is not None and sc.run(ActionType.CLICK, prev.name).success:
        sc.run(ActionType.WAIT_STABLE)
        back = (sc.evaluate(_TABLE_JS, idx) or {}).get("cells", [])[:1]
        checks.append(Check("previous page restores the rows", back == first, "warn",
                            "" if back == first else f"'{prev.name}' did not bring the first page back"))
    return checks


def _open_row(sc: SkillContext, read: dict) -> list[Check]:
    control = read.get("rowControl")
    if not control or not control["name"]:
        return [info("row details", "the first row has no link or button")]
    if not sc.policy.allows(control["name"], role=control["role"], url=sc.page.url):
        return [info("row details", f"'{control['name']}' not pressed (safety policy)")]
    before = sc.observe(fresh=True)
    if not sc.run(ActionType.CLICK, control["name"]).success:
        return []
    sc.run(ActionType.WAIT_STABLE)
    after = sc.observe(fresh=True)
    navigated = after.url.split("#", 1)[0] != before.url.split("#", 1)[0]
    dialog = after.dialogs > before.dialogs
    opened = navigated or dialog or after.fingerprint() != before.fingerprint()
    how = "opens a page" if navigated else "opens a dialog" if dialog else "changes the page" if opened else ""
    if navigated:
        sc.run(ActionType.BACK)
        sc.run(ActionType.WAIT_STABLE)
    elif dialog:
        sc.run(ActionType.PRESS, "Escape")
    return [Check("row opens details", opened, "warn",
                  f"'{control['name']}' {how}" if opened else f"'{control['name']}' changed nothing")]


@skill(ActionType.TEST_TABLE)
def test_table(sc: SkillContext) -> list[Check]:
    idx = max(int(sc.option("table", "1") or 1) - 1, 0)
    read = sc.evaluate(_TABLE_JS, idx)
    if not read:
        return [Check("table found", False, "warn", f"no visible table #{idx + 1} on the page")]
    names = [h["name"] for h in read["headers"] if h["name"]]
    empty = read["rows"] == 0 and bool(EMPTY_STATE_RE.search(read["text"]))
    checks = [
        info("table", f"table {idx + 1} of {read['tables']}: {read['rows']} row(s); "
                      f"columns: {', '.join(names) or 'none named'}"),
        Check("table has headers", bool(names), "warn", "" if names else "no header row with text"),
        Check("table has rows", read["rows"] > 0 or empty, "warn",
              "empty-state message shown" if empty else "" if read["rows"] else "no rows and no empty-state message"),
    ]
    if read["rows"] == 0:
        return checks
    if sc.flag("sort", True):
        checks += _sort(sc, read, idx)
    if sc.flag("paginate", True):
        checks += _paginate(sc, sc.evaluate(_TABLE_JS, idx) or read, idx)
    if sc.flag("open", True):
        checks += _open_row(sc, sc.evaluate(_TABLE_JS, idx) or read)
    return checks
