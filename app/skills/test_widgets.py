"""test_widgets — do tabs, disclosures and dialogs behave as their ARIA roles promise?

    - test_widgets
    - test_widgets: "max=3"                     widgets of each kind exercised (default 5)
    - test_widgets: "dialog=Edit profile"       also treat this button as a dialog opener

Through ordinary child steps (``click``, ``press Escape``, ``wait_stable``):

    tabs          every tab that is not selected: after a click it is
                  ``aria-selected`` and the panel it controls is visible;
                  the originally selected tab is clicked again at the end
    disclosures   buttons with ``aria-expanded`` (accordions, "show more",
                  menus): a click flips the state and shows / hides the region
                  it controls; a second click restores it
    dialogs       buttons with ``aria-haspopup="dialog"`` or a Bootstrap
                  ``data-(bs-)toggle="modal"``: the dialog opens, holds focus,
                  Escape closes it, and focus returns to the button

Disabled controls (``disabled``, ``aria-disabled``, a ``disabled`` class)
are left alone. Every finding is a warning. Custom widgets without ARIA give nothing to
check and are reported as not found, never as failures. Controls the safety
policy blocks are never pressed.
"""

from __future__ import annotations

from app.schemas.actions import ActionType, Check
from app.skills.base import SkillContext, info, skill

DEFAULT_MAX = 5
MAX_DETAIL_ITEMS = 5

_HELPERS = r"""
  const vis = el => { if (!el) return false; const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const nameOf = el => (el.getAttribute('aria-label') || el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
  const byName = (sel, name) => [...document.querySelectorAll(sel)].find(el => vis(el) && nameOf(el) === name);
  const region = el => { const id = el && el.getAttribute('aria-controls'); const r = id && document.getElementById(id); return r ? vis(r) : null; };
"""

_FIND_JS = "() => {" + _HELPERS + r"""
  const enabled = el => !el.disabled && el.getAttribute('aria-disabled') !== 'true' && !el.classList.contains('disabled');
  const all = sel => [...document.querySelectorAll(sel)].filter(el => vis(el) && enabled(el));
  return {
    tabs: all('[role="tab"]').map(t => ({ name: nameOf(t), selected: t.getAttribute('aria-selected') === 'true' })),
    disclosures: all('button[aria-expanded], [role="button"][aria-expanded]')
      .filter(b => b.getAttribute('role') !== 'tab' && b.getAttribute('aria-haspopup') !== 'dialog').map(nameOf),
    dialogs: all('[aria-haspopup="dialog"], [data-bs-toggle="modal"], [data-toggle="modal"]').map(nameOf),
  };
}"""

_TAB_JS = "(name) => {" + _HELPERS + r"""
  const t = byName('[role="tab"]', name);
  return t ? { selected: t.getAttribute('aria-selected') === 'true', panel: region(t) } : null;
}"""

_DISCLOSURE_JS = "(name) => {" + _HELPERS + r"""
  const b = byName('button[aria-expanded], [role="button"][aria-expanded]', name);
  return b ? { expanded: b.getAttribute('aria-expanded') === 'true', region: region(b) } : null;
}"""

_DIALOG_JS = "(opener) => {" + _HELPERS + r"""
  const d = [...document.querySelectorAll('[role="dialog"], [role="alertdialog"], dialog[open]')].find(vis);
  const close = d && [...d.querySelectorAll('button, [role="button"]')].find(b => vis(b) && /^(close|cancel|×|x|dismiss)$/i.test(nameOf(b)));
  const active = document.activeElement;
  return { open: !!d, focusInside: !!(d && d.contains(active)), focusOnOpener: !!active && nameOf(active) === opener,
           close: close ? nameOf(close) : '' };
}"""


def _detail(items: list[str]) -> str:
    shown = items[:MAX_DETAIL_ITEMS]
    more = len(items) - len(shown)
    return "; ".join(shown) + (f" (+{more} more)" if more > 0 else "")


def _listed(name: str, problems: list[str], tried: int) -> Check:
    return Check(name, not problems, "warn", _detail(problems) or f"{tried} checked", len(problems))


def _tabs(sc: SkillContext, tabs: list[dict], limit: int) -> list[Check]:
    targets = [t["name"] for t in tabs if t["name"] and not t["selected"]
               and sc.policy.allows(t["name"], role="tab")][:limit]
    if not targets:
        return []
    original = next((t["name"] for t in tabs if t["selected"]), "")
    problems: list[str] = []
    for name in targets:
        if not sc.run(ActionType.CLICK, name).success:
            problems.append(f"could not press '{name}'")
            continue
        sc.run(ActionType.WAIT_STABLE)
        state = sc.evaluate(_TAB_JS, name)
        if state is None:
            continue
        if not state["selected"]:
            problems.append(f"'{name}' not selected after a click")
        elif state["panel"] is False:
            problems.append(f"the panel of '{name}' stays hidden")
    if original:
        sc.run(ActionType.CLICK, original)
    return [_listed("tabs select their panel", problems, len(targets))]


def _disclosures(sc: SkillContext, names: list[str], limit: int) -> list[Check]:
    targets = [n for n in dict.fromkeys(names) if n and sc.policy.allows(n, role="button")][:limit]
    problems: list[str] = []
    for name in targets:
        before = sc.evaluate(_DISCLOSURE_JS, name)
        if before is None:
            continue
        if not sc.run(ActionType.CLICK, name).success:
            problems.append(f"could not press '{name}'")
            continue
        sc.run(ActionType.WAIT_STABLE)
        after = sc.evaluate(_DISCLOSURE_JS, name)
        if after is None:
            continue
        if after["expanded"] == before["expanded"]:
            problems.append(f"'{name}' aria-expanded stayed {str(before['expanded']).lower()}")
        elif after["region"] is not None and after["region"] != after["expanded"]:
            problems.append(f"the region of '{name}' is {'hidden' if after['expanded'] else 'still visible'}")
        sc.run(ActionType.CLICK, name)                                   # restore
        sc.run(ActionType.WAIT_STABLE)
    return [_listed("disclosures toggle", problems, len(targets))] if targets else []


def _dialogs(sc: SkillContext, names: list[str], limit: int) -> list[Check]:
    targets = [n for n in dict.fromkeys(names) if n and sc.policy.allows(n, role="button")][:limit]
    opened, focus, escape, restored = [], [], [], []
    for name in targets:
        if not sc.run(ActionType.CLICK, name).success:
            opened.append(f"could not press '{name}'")
            continue
        sc.run(ActionType.WAIT_STABLE)
        state = sc.evaluate(_DIALOG_JS, name) or {}
        if not state.get("open"):
            opened.append(f"'{name}' opened no dialog")
            continue
        if not state.get("focusInside"):
            focus.append(f"focus stays outside the dialog of '{name}'")
        sc.run(ActionType.PRESS, "Escape")
        sc.run(ActionType.WAIT_STABLE)
        after = sc.evaluate(_DIALOG_JS, name) or {}
        if after.get("open"):
            escape.append(f"Escape leaves the dialog of '{name}' open")
            if after.get("close"):
                sc.run(ActionType.CLICK, after["close"])
        elif not after.get("focusOnOpener"):
            restored.append(f"focus does not return to '{name}'")
    if not targets:
        return []
    n = len(targets)
    return [_listed("dialogs open", opened, n), _listed("dialog takes focus", focus, n),
            _listed("Escape closes the dialog", escape, n), _listed("focus returns to the opener", restored, n)]


@skill(ActionType.TEST_WIDGETS)
def test_widgets(sc: SkillContext) -> list[Check]:
    limit = int(sc.option("max", str(DEFAULT_MAX)) or DEFAULT_MAX)
    found = sc.evaluate(_FIND_JS) or {"tabs": [], "disclosures": [], "dialogs": []}
    dialogs = found["dialogs"] + ([sc.option("dialog")] if sc.option("dialog") else [])
    checks = [info("widgets", f"{len(found['tabs'])} tab(s), {len(found['disclosures'])} disclosure(s), "
                              f"{len(dialogs)} dialog trigger(s)")]
    checks += _tabs(sc, found["tabs"], limit)
    checks += _disclosures(sc, found["disclosures"], limit)
    checks += _dialogs(sc, dialogs, limit)
    if len(checks) == 1:
        checks.append(info("nothing to exercise", "no ARIA tabs, disclosures or dialog triggers on the page"))
    return checks
