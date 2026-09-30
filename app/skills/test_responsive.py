"""test_responsive — layout checks at several viewport widths.

    - test_responsive                              current viewport + 390x664 + 768x1024
    - test_responsive: "viewports=390x664,1024x768"

Per viewport (one ``page.evaluate`` each): horizontal overflow, controls
pushed off-screen (not the ones inside an off-canvas panel or carousel, nor
skip links), form fields clipped, dialog fits, and on narrow widths
tap-target and text sizes. Tap targets follow WCAG 2.5.8: the area is the
control's box with its content, and a target under 24×24 still passes when
it sits inline in text or has 24px of room around it.

The mobile menu is judged only where navigation is expected: a navigation
landmark with links to other pages, visible on a wide viewport, hidden on a
narrow one (a sign-in page whose nav holds a phone number is not). Its toggle
— a button, anything with ``aria-expanded``/``aria-controls``, or an element
named or classed like a menu — is clicked through the engine (``click`` probe
step), then Escape is pressed (cleanup). A toggle that is not a button
(a ``div`` with no role or tabindex) is a warning: keyboard and screen-reader
users cannot open the menu. A finding repeated at several widths is reported
once, with the widths. A screenshot per viewport is kept on the step. The
original viewport is restored at the end; failing to restore it is an
inconclusive "page restored after the skill".

Viewport switching is layout-only (no user-agent or touch emulation); for
real device emulation run the flow under the ``mobile`` profile.
"""

from __future__ import annotations

import logging

from app.execution import oracle
from app.schemas.actions import ActionType, Check, summarize
from app.skills.base import SkillContext, inconclusive, info, skill, skipped

logger = logging.getLogger(__name__)

DEFAULT_VIEWPORTS = ("390x664", "768x1024")
NARROW = 768            # below this, mobile rules apply (tap targets, text size, menu)
MIN_TAP = 24
MIN_FONT = 12

_LAYOUT_JS = r"""
() => {
  const vw = window.innerWidth, vh = window.innerHeight;
  const vis = el => { const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden'; };
  // accessible-name order: aria-label wins over content (an icon button reads as its label)
  const nameOf = el => (el.getAttribute('aria-label') || el.innerText || el.value || el.title || '').trim().replace(/\s+/g, ' ').slice(0, 40);
  const de = document.documentElement, body = document.body;
  const controls = [...document.querySelectorAll('a[href], button, input:not([type=hidden]), select, textarea, [role=button], [role=link]')].filter(vis);
  const out = r => r.right <= 0 || r.left >= vw;
  // Off-canvas panels, carousel slides: an ancestor is off-screen too. Skip links: #anchors placed off-screen until focused.
  const offCanvas = el => { for (let a = el.parentElement; a && a !== body; a = a.parentElement) {
    const r = a.getBoundingClientRect(); if (r.width > 0 && out(r)) return true; } return false; };
  const skipLink = el => el.tagName === 'A' && (el.getAttribute('href') || '').startsWith('#')
    && ['absolute', 'fixed'].includes(getComputedStyle(el).position);
  const offscreen = controls.filter(el => out(el.getBoundingClientRect()) && !offCanvas(el) && !skipLink(el))
    .map(nameOf).filter(Boolean);
  // WCAG 2.5.8 target size: the box with its content; exceptions for inline targets and spacing.
  const isTap = el => el.tagName === 'A' || el.tagName === 'BUTTON' || el.getAttribute('role') === 'button';
  const area = el => { let r = el.getBoundingClientRect(), [l, t, rt, b] = [r.left, r.top, r.right, r.bottom];
    for (const c of [...el.querySelectorAll('*')].slice(0, 10)) { const q = c.getBoundingClientRect();
      if (q.width && q.height) { l = Math.min(l, q.left); t = Math.min(t, q.top); rt = Math.max(rt, q.right); b = Math.max(b, q.bottom); } }
    return {l, t, r: rt, b, w: rt - l, h: b - t}; };
  const inline = el => { const p = el.parentElement; return !!p && getComputedStyle(el).display.startsWith('inline')
    && (p.innerText || '').trim().length > (el.innerText || '').trim().length + 10; };
  const taps = controls.filter(isTap).map(el => ({el, a: area(el)}));
  const circle = a => { const cx = (a.l + a.r) / 2, cy = (a.t + a.b) / 2, h = %(tap)d / 2;
    return {l: cx - h, t: cy - h, r: cx + h, b: cy + h}; };
  const hits = (x, y) => x.l < y.r && y.l < x.r && x.t < y.b && y.t < x.b;
  const smallTap = taps.filter(({el, a}) => (a.w < %(tap)d || a.h < %(tap)d) && !inline(el)
      && taps.some(o => o.el !== el && !o.el.contains(el) && !el.contains(o.el) && hits(circle(a), o.a)))
    .map(({el, a}) => `"${nameOf(el) || el.tagName.toLowerCase()}" ${Math.round(a.w)}×${Math.round(a.h)}`);
  let smallText = 0, sampled = 0;
  for (const el of document.querySelectorAll('p, span, a, li, td, th, label, button, h1, h2, h3, h4, h5, h6, div')) {
    if (sampled >= 400) break;
    if (![...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim())) continue;
    if (!vis(el)) continue;
    sampled++;
    if (parseFloat(getComputedStyle(el).fontSize) < %(font)d) smallText++;
  }
  const dialog = [...document.querySelectorAll('[role=dialog], dialog[open]')].filter(vis)[0];
  const dr = dialog ? dialog.getBoundingClientRect() : null;
  const navs = [...document.querySelectorAll('nav, [role=navigation]')];
  // Links to other pages — not the toggle, a phone number or an anchor on this page.
  const pageLinks = [...navs.flatMap(n => [...n.querySelectorAll('a[href]')])].filter(a =>
    /^https?:/.test(a.href) && new URL(a.href).pathname !== location.pathname);
  const navLinksVisible = pageLinks.some(vis);
  const MENU = /menu|hamburger|burger|nav-?toggle|navbar-toggle|offcanvas|drawer/;
  const toggle = [...document.querySelectorAll('button, [role=button], a, [aria-expanded], [aria-controls], div, span')]
    .filter(vis).find(el => {
      if (el.hasAttribute('aria-expanded') || el.hasAttribute('aria-controls')) return true;
      const t = `${el.getAttribute('aria-label') || ''} ${el.id} ${typeof el.className === 'string' ? el.className : ''}`
        + (['BUTTON', 'A'].includes(el.tagName) ? ' ' + (el.innerText || '') : '');
      return MENU.test(t.toLowerCase()) && (el.tagName !== 'DIV' && el.tagName !== 'SPAN'
        || getComputedStyle(el).cursor === 'pointer');
    });
  const isButton = el => ['BUTTON', 'A'].includes(el.tagName) || ['button', 'link'].includes(el.getAttribute('role'));
  const selectorOf = el => el.id ? '#' + CSS.escape(el.id) : el.tagName.toLowerCase()
    + (typeof el.className === 'string' && el.className.trim() ? '.' + el.className.trim().split(/\s+/).map(CSS.escape).join('.') : '');
  const fields = [...document.querySelectorAll('input:not([type=hidden]), select, textarea')].filter(vis);
  const clipped = fields.filter(el => { const r = el.getBoundingClientRect(); return r.right > vw + 1 || r.left < -1; }).length;
  return { vw, vh, overflow: __OVERFLOW__,
           controls: controls.length, offscreen, smallTap, smallText, sampled,
           dialog: !!dialog, dialogFits: dr ? (dr.left >= -1 && dr.right <= vw + 1 && dr.height <= vh + 1) : true,
           navLinks: pageLinks.length, navLinksVisible,
           menuToggle: toggle ? (isButton(toggle) && nameOf(toggle) ? nameOf(toggle) : selectorOf(toggle)) : '',
           toggleIsButton: toggle ? isButton(toggle) : true,
           toggleUnique: toggle ? (isButton(toggle) && nameOf(toggle)
             ? true : document.querySelectorAll(selectorOf(toggle)).length === 1) : false,
           fields: fields.length, clipped };
}
""" % {"tap": MIN_TAP, "font": MIN_FONT}
_LAYOUT_JS = _LAYOUT_JS.replace("__OVERFLOW__", oracle.H_OVERFLOW_JS)   # after %-formatting: its % would break it

_NAV_VISIBLE_JS = """
() => [...document.querySelectorAll('nav, [role=navigation]')].some(n =>
  [...n.querySelectorAll('a[href]')].some(el => { const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && /^https?:/.test(el.href) && new URL(el.href).pathname !== location.pathname; }))
"""


def parse_viewports(spec: str) -> list[dict]:
    sizes = []
    for part in spec.split(","):
        w, _, h = part.strip().lower().partition("x")
        if w.isdigit() and h.isdigit():
            sizes.append({"width": int(w), "height": int(h)})
    return sizes


def _label(vp: dict) -> str:
    return f"{vp['width']}x{vp['height']}"


def _checks_for(label: str, r: dict) -> list[Check]:
    p = f"[{label}] "
    checks = [
        Check(p + "no horizontal overflow", r["overflow"] <= 1, "error",
              f"content {r['overflow']}px wider than the viewport" if r["overflow"] > 1 else ""),
        Check(p + "controls on screen", not r["offscreen"], "error",
              f"off-screen: {summarize(r['offscreen'])}" if r["offscreen"] else f"{r['controls']} controls visible"),
    ]
    if r["fields"]:
        checks.append(Check(p + "form fields fit", r["clipped"] == 0, "error",
                            f"{r['clipped']} of {r['fields']} fields clipped" if r["clipped"] else ""))
    if r["dialog"]:
        checks.append(Check(p + "dialog fits viewport", r["dialogFits"], "error"))
    if r["vw"] < NARROW:
        checks.append(Check(p + f"tap targets ≥ {MIN_TAP}px", not r["smallTap"], "warn",
                            f"small: {summarize(r['smallTap'])}" if r["smallTap"] else ""))
        checks.append(Check(p + f"text ≥ {MIN_FONT}px", r["smallText"] == 0, "warn",
                            f"{r['smallText']} of {r['sampled']} text elements smaller" if r["smallText"] else ""))
    return checks


def _menu_check(sc: SkillContext, label: str, r: dict, wide_nav: bool | None) -> list[Check]:
    """Narrow width, site navigation hidden here but shown wide: try the menu toggle.
    *wide_nav* is whether a wide viewport showed the navigation links (None: not measured)."""
    p = f"[{label}] "
    if not r["navLinks"] or r["navLinksVisible"] or r["vw"] >= NARROW or wide_nav is False:
        return []           # no navigation to other pages, or it is not a narrow-width change
    toggle = r["menuToggle"]
    if not toggle:
        return [Check(p + "mobile menu opens", False, "warn",
                      "navigation links shown on a wide viewport are hidden here, and no menu toggle was found")]
    checks = [] if r["toggleIsButton"] else [Check(p + "menu toggle is a button", False, "warn",
                                                   f"'{toggle}' has no button role or tabindex: keyboard and "
                                                   "screen-reader users cannot open the menu")]
    if not r["toggleUnique"]:
        return [*checks, inconclusive(p + "mobile menu opens", f"'{toggle}' matches several elements; not pressed")]
    if not sc.allowed(toggle, role="button"):
        return [*checks, skipped(p + "mobile menu opens", f"toggle '{toggle}' not pressed (safety policy)")]
    pressed = sc.run(ActionType.CLICK, toggle, kind="probe")
    if not pressed.success:
        return [*checks, skipped(p + "mobile menu opens", pressed.message) if pressed.skipped else
                inconclusive(p + "mobile menu opens", f"the agent could not press the toggle '{toggle}'")]
    opened = bool(sc.evaluate(_NAV_VISIBLE_JS))
    sc.run(ActionType.PRESS, "Escape", kind="cleanup")
    return [*checks, Check(p + "mobile menu opens", opened, "error",
                           f"pressed '{toggle}'" + ("" if opened else " but navigation links stayed hidden"))]


def _merge_viewports(checks: list[Check]) -> list[Check]:
    """One check per finding: the same name, result and detail at several widths
    become one ``[390x664, 440x956] name`` check."""
    groups: dict[tuple, list[Check]] = {}
    for c in checks:
        label, sep, name = c.name.partition("] ")
        key = (name, c.passed, c.severity, c.detail) if sep and label.startswith("[") else (c.name, id(c))
        groups.setdefault(key, []).append(c)
    out = []
    for key, same in groups.items():
        first = same[0]
        if len(same) > 1:
            labels = ", ".join(c.name.partition("] ")[0][1:] for c in same)
            first = Check(f"[{labels}] {key[0]}", first.passed, first.severity, first.detail, first.count)
        out.append(first)
    return out


@skill(ActionType.TEST_RESPONSIVE)
def test_responsive(sc: SkillContext) -> list[Check]:
    original = sc.page.viewport_size
    wanted = parse_viewports(sc.option("viewports", ",".join(DEFAULT_VIEWPORTS)))
    sizes: list[dict] = []
    for vp in ([original] if original else []) + wanted:
        if vp not in sizes:
            sizes.append(vp)
    checks: list[Check] = [info("viewports", ", ".join(_label(v) for v in sizes))]
    wide_nav: bool | None = None
    try:
        for vp in sorted(sizes, key=lambda v: -v["width"]):      # wide first: the menu rule needs it
            label = _label(vp)
            try:
                if vp != sc.page.viewport_size:
                    sc.page.set_viewport_size(vp)   # layout only; not a flow action
            except Exception as exc:
                checks.append(inconclusive(f"[{label}] layout probed", f"viewport not set: {exc}"[:200]))
                continue
            r = sc.evaluate(_LAYOUT_JS)
            if not r:
                checks.append(inconclusive(f"[{label}] layout probed", "page did not answer"))
                continue
            if r["vw"] >= NARROW and r["navLinks"]:
                wide_nav = wide_nav or r["navLinksVisible"]
            checks += _checks_for(label, r)
            checks += _menu_check(sc, label, r, wide_nav)
            sc.screenshot(label)
            if sc.out_of_time():
                break
    finally:
        if original and sc.page.viewport_size != original:
            try:
                sc.page.set_viewport_size(original)
            except Exception as exc:
                logger.debug("[test_responsive] viewport not restored: %s", exc)
                sc.cleanup_failed.append(f"viewport {_label(original)} not restored: {exc}")
    return _merge_viewports(checks)
