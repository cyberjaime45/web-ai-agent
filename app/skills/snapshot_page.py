"""snapshot_page — structural regression: what disappeared from the page?

    - snapshot_page: "members_list"
    - snapshot_page: "members_list" | "update=true"      save a new baseline
    - snapshot_page: "members_list" | "strict=true"      a removal fails the step
    - snapshot_page: "members_list" | "ignore=Promo,Chat"

The page's structure — headings, controls by role and name, form fields,
table columns — is compared with a JSON baseline saved the first time the
step ran, per device profile: ``<flow folder>/baselines/<name>__<profile>.json``
(``reports/<env>/baselines/`` for flows outside the project). Baselines are
plain JSON, reviewed in pull requests like the flows next to them.

Removed items are a warning (an error with ``strict=true``); added items
are listed. Controls inside table rows, and names that look like data
(numbers, dates, amounts — ``writer.stable_text``), are left out of the
structure: they change with the data, not with the UI. No pixels, so fonts,
animation and content do not make it flaky.
"""

from __future__ import annotations

import datetime
import json
import logging

from app.flow.writer import stable_text
from app.schemas.actions import ActionType, Check, summarize
from app.skills.base import SkillContext, info, skill

logger = logging.getLogger(__name__)

MAX_DETAIL_ITEMS = 8
ROLES = ("heading", "button", "link", "tab", "menuitem", "searchbox", "combobox", "checkbox",
         "radio", "switch", "textbox")

# Names of controls inside table body rows (data), and the table column headers (structure).
_TABLES_JS = r"""
() => {
  const text = el => (el.getAttribute('aria-label') || el.innerText || el.value || '').replace(/\s+/g, ' ').trim();
  const inRows = new Set(), columns = new Set();
  document.querySelectorAll('tr, [role="row"]').forEach(r => {
    const header = r.closest('thead') || [...r.children].every(c => c.tagName === 'TH' || c.getAttribute('role') === 'columnheader');
    if (header) { [...r.children].map(text).filter(Boolean).forEach(t => columns.add(t)); return; }
    r.querySelectorAll('a, button, input, select, [role]').forEach(el => { const n = text(el); if (n) inRows.add(n); });
  });
  return { inRows: [...inRows], columns: [...columns] };
}
"""


def structure(sc: SkillContext, ignore: tuple[str, ...] = ()) -> list[str]:
    """Sorted ``role: name`` items describing the page's UI, without data."""
    ob = sc.observe(fresh=True)
    tables = sc.evaluate(_TABLES_JS) or {"inRows": [], "columns": []}
    in_rows = set(tables["inRows"])
    items = {f"{n.role}: {n.name}" for n in ob.nodes
             if n.role in ROLES and n.name and n.name not in in_rows and stable_text(n.name)}
    items |= {f"field: {f.label} ({f.type})" for form in ob.forms for f in form.fields
              if f.label and stable_text(f.label)}
    items |= {f"column: {c}" for c in tables["columns"] if stable_text(c)}
    return sorted(i for i in items if not any(pat and pat.lower() in i.lower() for pat in ignore))


@skill(ActionType.SNAPSHOT_PAGE)
def snapshot_page(sc: SkillContext) -> list[Check]:
    name = sc.option("target") or sc.option("name")
    if not name:
        return [Check("snapshot name given", False, "error", 'usage: snapshot_page: "members_list"')]
    ignore = tuple(p.strip() for p in sc.option("ignore").split(",") if p.strip())
    current = structure(sc, ignore)
    path = sc.engine.baseline_path(name)

    existed = path.exists()
    if sc.flag("update") or not existed:
        path.write_text(json.dumps({
            "name": name, "profile": sc.profile, "url": sc.page.url,
            "saved": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
            "items": current,
        }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        why = "updated (update=true)" if existed else "saved (first run)"
        return [info("baseline", f"{why}: {len(current)} items → {path}")]

    try:
        baseline = json.loads(path.read_text(encoding="utf-8"))
        expected = [i for i in baseline["items"] if not any(p.lower() in i.lower() for p in ignore)]
    except (OSError, ValueError, KeyError) as exc:
        return [Check("baseline readable", False, "error", f"{path}: {exc}")]
    removed = sorted(set(expected) - set(current))
    added = sorted(set(current) - set(expected))
    severity = "error" if sc.flag("strict") else "warn"
    checks = [
        info("baseline", f"{len(expected)} items in {path} (saved {baseline.get('saved', '?')})"),
        Check.listing("nothing removed", removed, severity, limit=MAX_DETAIL_ITEMS),
    ]
    if added:
        checks.append(info("added since the baseline", summarize(added, MAX_DETAIL_ITEMS)))
    return checks
