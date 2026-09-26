"""test_search — search for something the page itself shows.

    - test_search
    - test_search: "term=John Smith"         search for a given value instead
    - test_search: "search=Find a member"    which field, when there are several

No test data is needed: the term is read from the results already on the
page (the first cell of the first table row, else the first list item).
Through ordinary child steps (``fill``, ``press Enter``, ``wait_stable``):

    finds a visible value     the term is on the page after searching (an
                              ``assert_text`` step is added when it is, so the
                              generated flow keeps the check)
    narrows the results       the result count did not grow
    no match shows nothing    a nonsense term leaves no results or an empty-state message
    clearing restores         clearing the field brings back the original count

Every finding is a warning: a search can legitimately match on fields the
page does not show. When searching opens another page, the skill goes back
to the start page before the next search.
"""

from __future__ import annotations

from app.agent.observer import EMPTY_STATE_RE
from app.schemas.actions import ActionType, Check
from app.skills.base import SkillContext, info, skill
from app.utils.urls import same_page

NO_MATCH = "zzqx-no-match-7f3"

# Result count and a term candidate: table rows first, else list items in main content.
_RESULTS_JS = r"""
() => {
  const vis = el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const text = el => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
  const table = [...document.querySelectorAll('table, [role="grid"], [role="table"]')].find(vis);
  let rows = [];
  if (table) {
    rows = [...table.querySelectorAll('tr, [role="row"]')].filter(r => vis(r) && !r.closest('thead')
      && ![...r.children].every(c => c.tagName === 'TH' || c.getAttribute('role') === 'columnheader')
      && !(r.children.length === 1 && r.children[0].colSpan > 1));      // a "No records" placeholder row
  } else {
    const scope = document.querySelector('main, [role="main"]') || document.body;
    rows = [...scope.querySelectorAll('[role="listitem"], li')].filter(li => vis(li) && !li.closest('nav, header, footer'));
  }
  const cells = rows.length ? [...rows[0].querySelectorAll('td, [role="cell"], [role="gridcell"], a')].map(text) : [];
  const candidate = (cells.find(c => c.length >= 3 && c.length <= 40 && /[a-z]/i.test(c)) || text(rows[0] || document.createElement('i')).slice(0, 40));
  return { count: table || rows.length ? rows.length : null, candidate, text: text(document.body).slice(0, 4000) };
}
"""


def _results(sc: SkillContext) -> dict:
    return sc.evaluate(_RESULTS_JS) or {"count": None, "candidate": "", "text": ""}


def _search(sc: SkillContext, box: str, term: str) -> dict:
    sc.run(ActionType.FILL, box, term)
    sc.run(ActionType.PRESS, "Enter")
    sc.run(ActionType.WAIT_STABLE)
    return _results(sc)


def _back_to_start(sc: SkillContext, start_url: str) -> None:
    if not same_page(sc.page.url, start_url):
        sc.run(ActionType.GOTO, start_url)
        sc.run(ActionType.WAIT_STABLE)


@skill(ActionType.TEST_SEARCH)
def test_search(sc: SkillContext) -> list[Check]:
    ob = sc.observe(fresh=True)
    wanted = sc.option("search")
    box = next((n for n in ob.by_role("searchbox", "textbox") if n.name == wanted), None) if wanted \
        else ob.search_box()
    if box is None or not box.name:
        return [info("search", "no search field found" + (f" named '{wanted}'" if wanted else ""))]

    start_url = sc.page.url
    baseline = _results(sc)
    term = sc.option("term") or (baseline["candidate"] or "").strip()
    if not term:
        return [info("search", f"'{box.name}' found, but no result on the page to search for (term=…)")]
    checks = [info("search", f"'{box.name}': searched for '{term}'; {baseline['count']} result(s) before")]

    found = _search(sc, box.name, term)
    visible = term.lower() in (found["text"] or "").lower()
    if visible:
        sc.run(ActionType.ASSERT_TEXT, term)
    checks.append(Check("search finds a visible value", visible, "warn",
                        "" if visible else f"'{term}' is not on the page after searching for it"))
    if baseline["count"] is not None and found["count"] is not None:
        narrowed = found["count"] <= baseline["count"]
        checks.append(Check("search narrows the results", narrowed, "warn",
                            f"{baseline['count']} → {found['count']} result(s)"))

    _back_to_start(sc, start_url)
    miss = _search(sc, box.name, NO_MATCH)
    empty = miss["count"] == 0 or bool(EMPTY_STATE_RE.search(miss["text"] or ""))
    checks.append(Check("no match shows no results", empty, "warn",
                        "" if empty else f"'{NO_MATCH}' still shows {miss['count']} result(s)"))

    if not same_page(sc.page.url, start_url):
        _back_to_start(sc, start_url)
        return checks
    sc.run(ActionType.CLEAR, box.name)
    sc.run(ActionType.PRESS, "Enter")
    sc.run(ActionType.WAIT_STABLE)
    restored = _results(sc)
    if baseline["count"] is not None:
        ok = restored["count"] == baseline["count"]
        checks.append(Check("clearing restores the results", ok, "warn",
                            "" if ok else f"{baseline['count']} result(s) before, {restored['count']} after clearing"))
    return checks
