"""check_accessibility — a basic, deterministic accessibility pass.

One ``page.evaluate``; nothing is clicked. The rules are the ones that also
make a page hard to automate: a control without a name is a control L1
cannot target.

    - check_accessibility                   findings are warnings
    - check_accessibility: "level=strict"   findings fail the step

    images without alt text        visible <img> with no alt attribute (alt="" is decorative, fine)
    fields without a label         no <label>, aria-label, aria-labelledby or title (a placeholder is not a label)
    controls without a name        buttons and links with no text, aria-label, title or image alt
    page language                  <html lang> missing
    heading structure              no <h1>, or a level skipped (h2 → h4)
    duplicate ids                  ids used more than once that a label or aria reference points to
    positive tabindex              tabindex > 0 reorders keyboard focus
    focus in dialog                an open modal dialog that does not hold keyboard focus

Not a full WCAG audit: colour contrast and the rest need a dedicated tool.
"""

from __future__ import annotations

from app.schemas.actions import ActionType, Check
from app.skills.base import SkillContext, skill

_AUDIT_JS = r"""
() => {
  const vis = el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const text = el => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
  const describe = el => {
    const tag = el.tagName.toLowerCase();
    const hint = el.id ? '#' + el.id : el.getAttribute('name') ? `[name=${el.getAttribute('name')}]`
      : el.getAttribute('src') ? `src=${el.getAttribute('src').split('?')[0].slice(-40)}`
      : el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\s+/)[0] : '';
    return tag + hint;
  };
  const byIdText = ids => ids.split(/\s+/).map(i => document.getElementById(i)).filter(Boolean).map(text).join(' ');
  const named = el => !!(el.getAttribute('aria-label') || '').trim()
    || (el.getAttribute('aria-labelledby') && byIdText(el.getAttribute('aria-labelledby')))
    || !!(el.getAttribute('title') || '').trim();

  const images = [...document.images].filter(i => vis(i) && !i.hasAttribute('alt')).map(describe);

  const fields = [...document.querySelectorAll('input, select, textarea')]
    .filter(el => vis(el) && !['hidden', 'submit', 'button', 'reset', 'image'].includes(el.type))
    .filter(el => !(el.labels && el.labels.length && [...el.labels].some(l => text(l))) && !named(el))
    .map(el => describe(el) + (el.placeholder ? ` (placeholder "${el.placeholder}" only)` : ''));

  const controls = [...document.querySelectorAll('button, a[href], [role="button"], [role="link"]')]
    .filter(vis)
    .filter(el => !text(el) && !named(el)
      && ![...el.querySelectorAll('img[alt], svg title')].some(x => (x.getAttribute('alt') || x.textContent || '').trim()))
    .map(describe);

  const levels = [...document.querySelectorAll('h1, h2, h3, h4, h5, h6')].filter(vis)
    .map(h => ({level: +h.tagName[1], text: text(h).slice(0, 40)}));
  const skipped = [];
  levels.forEach((h, i) => { if (i && h.level > levels[i - 1].level + 1)
    skipped.push(`h${levels[i - 1].level} → h${h.level} "${h.text}"`); });

  const counts = {};
  document.querySelectorAll('[id]').forEach(el => { counts[el.id] = (counts[el.id] || 0) + 1; });
  const referenced = new Set([...document.querySelectorAll('label[for]')].map(l => l.htmlFor));
  document.querySelectorAll('[aria-labelledby], [aria-describedby], [aria-controls]').forEach(el =>
    ['aria-labelledby', 'aria-describedby', 'aria-controls'].forEach(a =>
      (el.getAttribute(a) || '').split(/\s+/).filter(Boolean).forEach(i => referenced.add(i))));
  const duplicates = Object.keys(counts).filter(i => counts[i] > 1 && referenced.has(i)).map(i => '#' + i);

  const tabindex = [...document.querySelectorAll('[tabindex]')]
    .filter(el => vis(el) && parseInt(el.getAttribute('tabindex'), 10) > 0).map(describe);

  const dialog = [...document.querySelectorAll('[role="dialog"][aria-modal="true"], dialog[open]')].find(vis);
  return {
    lang: (document.documentElement.getAttribute('lang') || '').trim(),
    images, fields, controls, h1: levels.some(h => h.level === 1), skipped, duplicates, tabindex,
    dialog: dialog ? (dialog.getAttribute('aria-label') || text(dialog).slice(0, 40)) : '',
    dialogFocus: dialog ? dialog.contains(document.activeElement) : true,
  };
}
"""


@skill(ActionType.CHECK_ACCESSIBILITY)
def check_accessibility(sc: SkillContext) -> list[Check]:
    audit = sc.evaluate(_AUDIT_JS)
    if audit is None:
        return [Check("accessibility audit ran", False, "warn", "the page could not be evaluated")]
    severity = "error" if sc.option("level") == "strict" else "warn"

    def listed(name: str, items: list[str]) -> Check:
        return Check.listing(name, items, severity)

    return [
        listed("images have alt text", audit["images"]),
        listed("fields have labels", audit["fields"]),
        listed("controls have names", audit["controls"]),
        Check("page language set", bool(audit["lang"]), severity,
              "" if audit["lang"] else "<html> has no lang attribute"),
        Check("page has an h1", audit["h1"], severity, "" if audit["h1"] else "no visible <h1>"),
        listed("heading levels in order", audit["skipped"]),
        listed("referenced ids are unique", audit["duplicates"]),
        listed("no positive tabindex", audit["tabindex"]),
        Check("dialog holds focus", audit["dialogFocus"], severity,
              "" if audit["dialogFocus"] else f"focus is outside the open dialog '{audit['dialog']}'"),
    ]
