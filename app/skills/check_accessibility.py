"""check_accessibility — a basic, deterministic accessibility pass.

One ``page.evaluate``; nothing is clicked. The rules are the ones that also
make a page hard to automate: a control without a name is a control L1
cannot target.

    - check_accessibility                   findings are warnings
    - check_accessibility: "level=strict"   findings fail the step

    images without alt text        a content <img> with no alt attribute (alt="" marks it decorative).
                                   Images that look decorative — positioned behind the content, tiny,
                                   hidden from assistive tech — are listed as info; an image inside a
                                   link or button is judged with that control
    fields without a label         no accessible name: <label>, aria-label, aria-labelledby or title
                                   (a placeholder is not a label)
    controls without a name        buttons and links with no text, aria-label, title or image alt
    page language                  <html lang> missing
    headings marked up             text styled as a heading (large, not in a heading) on a page with no
                                   heading at all; a page with headings but no <h1> is info
    heading structure              a level skipped (h2 → h4)
    duplicate ids                  ids used more than once that a label or aria reference points to
    positive tabindex              tabindex > 0 reorders keyboard focus
    focus in dialog                an open modal dialog that does not hold keyboard focus

Not a full WCAG audit: colour contrast and the rest need a dedicated tool.
"""

from __future__ import annotations

from app.schemas.actions import ActionType, Check
from app.skills.base import SkillContext, inconclusive, info, skill

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

  const CONTROL = 'a[href], button, [role="button"], [role="link"]';
  const hiddenFromAT = el => !!el.closest('[aria-hidden="true"], [role="presentation"], [role="none"]');
  const images = [], decorative = [];
  [...document.images].filter(i => vis(i) && !i.hasAttribute('alt') && !hiddenFromAT(i) && !i.closest(CONTROL))
    .forEach(i => {
      const cs = getComputedStyle(i), r = i.getBoundingClientRect();
      const why = ['absolute', 'fixed'].includes(cs.position) ? 'positioned behind the content'
        : r.width <= 4 || r.height <= 4 ? 'spacer-sized'
        : cs.pointerEvents === 'none' ? 'not interactive, pointer-events: none' : '';
      (why ? decorative : images).push(describe(i) + (why ? ` (${why})` : ''));
    });

  const fields = [...document.querySelectorAll('input, select, textarea')]
    .filter(el => vis(el) && !['hidden', 'submit', 'button', 'reset', 'image'].includes(el.type))
    .filter(el => !(el.labels && el.labels.length && [...el.labels].some(l => text(l))) && !named(el))
    .map(el => {
      // The text a sighted user reads as its label, when the code does not say so.
      let near = '';
      for (let a = el.parentElement, i = 0; a && i < 3 && !near; a = a.parentElement, i++)
        near = text(a).split(/\n| {2,}/)[0].slice(0, 30);
      return describe(el) + (el.placeholder ? ` (placeholder "${el.placeholder}" only)`
        : near ? ` (shows "${near}", not linked as its label)` : '');
    });

  const controls = [...document.querySelectorAll(CONTROL)]
    .filter(vis)
    .filter(el => !text(el) && !named(el)
      && ![...el.querySelectorAll('img[alt], svg title')].some(x => (x.getAttribute('alt') || x.textContent || '').trim()))
    .map(describe);

  const HEADING = 'h1, h2, h3, h4, h5, h6, [role="heading"]';
  const levels = [...document.querySelectorAll(HEADING)].filter(vis).map(h => ({
    level: /^H\d$/.test(h.tagName) ? +h.tagName[1] : +(h.getAttribute('aria-level') || 2),
    text: text(h).slice(0, 40)}));
  // Only on a page with no heading at all: text styled as one (large, own text)
  // is a visual heading that assistive tech cannot find.
  const visual = [];
  if (!levels.length && document.body) {
    const base = parseFloat(getComputedStyle(document.body).fontSize) || 16;
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    const seen = new Set();
    for (let n = walker.nextNode(), i = 0; n && i < 3000 && visual.length < 3; n = walker.nextNode(), i++) {
      const el = n.parentElement, own = n.textContent.replace(/\s+/g, ' ').trim();
      if (!el || seen.has(el) || own.length < 2 || own.length > 80) continue;
      seen.add(el);
      if (el.closest(CONTROL + ', label, script, style, noscript') || !vis(el)) continue;
      const size = parseFloat(getComputedStyle(el).fontSize);
      if (size >= Math.max(24, base * 1.4))
        visual.push(`"${own.slice(0, 40)}" (${el.tagName.toLowerCase()}, ${Math.round(size)}px)`);
    }
  }
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
    images, decorative, fields, controls, skipped, duplicates, tabindex, visual,
    headings: levels.length, h1: levels.some(h => h.level === 1),
    top: levels.length ? `h${levels[0].level} "${levels[0].text}"` : '',
    dialog: dialog ? (dialog.getAttribute('aria-label') || text(dialog).slice(0, 40)) : '',
    dialogFocus: dialog ? dialog.contains(document.activeElement) : true,
  };
}
"""


@skill(ActionType.CHECK_ACCESSIBILITY)
def check_accessibility(sc: SkillContext) -> list[Check]:
    audit = sc.evaluate(_AUDIT_JS)
    if audit is None:
        return [inconclusive("accessibility audit ran", "the page could not be evaluated")]
    severity = "error" if sc.option("level") == "strict" else "warn"

    def listed(name: str, items: list[str]) -> Check:
        return Check.listing(name, items, severity)

    checks = [listed("images have alt text", audit["images"])]
    if audit["decorative"]:
        checks.append(Check.listing("decorative images without alt=\"\"", audit["decorative"], "info"))
    checks += [
        listed("fields have labels", audit["fields"]),
        listed("controls have names", audit["controls"]),
        Check("page language set", bool(audit["lang"]), severity,
              "" if audit["lang"] else "<html> has no lang attribute"),
        _headings(audit, severity),
        listed("heading levels in order", audit["skipped"]),
        listed("referenced ids are unique", audit["duplicates"]),
        listed("no positive tabindex", audit["tabindex"]),
        Check("dialog holds focus", audit["dialogFocus"], severity,
              "" if audit["dialogFocus"] else f"focus is outside the open dialog '{audit['dialog']}'"),
    ]
    return checks


def _headings(audit: dict, severity: str) -> Check:
    """A missing <h1> is best practice, not a defect; a visual heading that is
    not marked up is (WCAG 1.3.1) — reported with the text that looks like one."""
    if audit["h1"]:
        return Check("page has an h1", True, severity)
    if audit["headings"]:
        return info("page has an h1", f"no <h1>; the first heading is {audit['top']}")
    if audit["visual"]:
        return Check.listing("visual headings marked up", audit["visual"], severity)
    return info("page has an h1", "the page has no headings and no text styled as one")
