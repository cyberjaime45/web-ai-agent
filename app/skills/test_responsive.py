"""test_responsive — layout checks at several viewport widths.

    - test_responsive                              current viewport + 390x664 + 768x1024
    - test_responsive: "viewports=390x664,1024x768"

Per viewport (one ``page.evaluate`` each): horizontal overflow, controls
pushed off-screen, form fields clipped, dialog fits, and on narrow widths
tap-target and text sizes. When a navigation landmark hides its links on a
narrow width and a menu toggle exists, the toggle is clicked through the
engine (``click`` child step) to check the mobile menu opens, then Escape
is pressed. A screenshot per viewport is kept on the step. The original
viewport is restored at the end.

Viewport switching is layout-only (no user-agent or touch emulation); for
real device emulation run the flow under the ``mobile`` profile.
"""

from __future__ import annotations

import logging

from app.schemas.actions import ActionType, Check, summarize
from app.skills.base import SkillContext, info, skill

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
  const offscreen = controls.filter(el => { const r = el.getBoundingClientRect(); return r.right <= 0 || r.left >= vw; }).map(nameOf).filter(Boolean);
  const isTap = el => el.tagName === 'A' || el.tagName === 'BUTTON' || el.getAttribute('role') === 'button';
  const smallTap = controls.filter(el => { const r = el.getBoundingClientRect(); return isTap(el) && (r.width < %(tap)d || r.height < %(tap)d); }).map(nameOf).filter(Boolean);
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
  const navLinksVisible = navs.some(n => [...n.querySelectorAll('a')].some(vis));   // links, not the toggle
  const toggle = [...document.querySelectorAll('button, [role=button], a')].filter(vis).find(el => {
    const t = (el.getAttribute('aria-label') || el.innerText || el.className || '').toLowerCase();
    return el.hasAttribute('aria-expanded') || /menu|hamburger|navbar-toggle|burger/.test(t);
  });
  const fields = [...document.querySelectorAll('input:not([type=hidden]), select, textarea')].filter(vis);
  const clipped = fields.filter(el => { const r = el.getBoundingClientRect(); return r.right > vw + 1 || r.left < -1; }).length;
  return { vw, vh, overflow: Math.max(de.scrollWidth, body ? body.scrollWidth : 0) - de.clientWidth,
           controls: controls.length, offscreen, smallTap, smallText, sampled,
           dialog: !!dialog, dialogFits: dr ? (dr.left >= -1 && dr.right <= vw + 1 && dr.height <= vh + 1) : true,
           navPresent: navs.length > 0, navLinksVisible,
           menuToggle: toggle ? (nameOf(toggle) || toggle.getAttribute('aria-label') || '') : '',
           fields: fields.length, clipped };
}
""" % {"tap": MIN_TAP, "font": MIN_FONT}

_NAV_VISIBLE_JS = """
() => [...document.querySelectorAll('nav, [role=navigation]')].some(n =>
  [...n.querySelectorAll('a')].some(el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; }))
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


def _menu_check(sc: SkillContext, label: str, r: dict) -> list[Check]:
    """Narrow width, nav present but its links hidden: try the menu toggle."""
    p = f"[{label}] "
    if not r["navPresent"] or r["navLinksVisible"] or r["vw"] >= NARROW:
        return []
    toggle = r["menuToggle"]
    if not toggle:
        return [Check(p + "mobile menu opens", False, "warn", "navigation hidden and no menu toggle found")]
    verdict = sc.policy.verdict(toggle, role="button", url=sc.page.url)
    if not verdict.allowed:
        return [Check(p + "mobile menu opens", False, "warn", f"toggle '{toggle}' not pressed — {verdict.reason}")]
    sc.run(ActionType.CLICK, toggle)
    opened = bool(sc.evaluate(_NAV_VISIBLE_JS))
    sc.run(ActionType.PRESS, "Escape")
    return [Check(p + "mobile menu opens", opened, "error",
                  f"pressed '{toggle}'" + ("" if opened else " but navigation links stayed hidden"))]


@skill(ActionType.TEST_RESPONSIVE)
def test_responsive(sc: SkillContext) -> list[Check]:
    original = sc.page.viewport_size
    wanted = parse_viewports(sc.option("viewports", ",".join(DEFAULT_VIEWPORTS)))
    sizes: list[dict] = []
    for vp in ([original] if original else []) + wanted:
        if vp not in sizes:
            sizes.append(vp)
    checks: list[Check] = [info("viewports", ", ".join(_label(v) for v in sizes))]
    try:
        for vp in sizes:
            if vp != sc.page.viewport_size:
                sc.page.set_viewport_size(vp)   # layout only; not a flow action
            label = _label(vp)
            r = sc.evaluate(_LAYOUT_JS)
            if not r:
                checks.append(Check(f"[{label}] layout probed", False, "warn", "page did not answer"))
                continue
            checks += _checks_for(label, r)
            checks += _menu_check(sc, label, r)
            sc.screenshot(label)
            if sc.child_failed:
                break
    finally:
        if original and sc.page.viewport_size != original:
            try:
                sc.page.set_viewport_size(original)
            except Exception as exc:
                logger.debug("[test_responsive] viewport not restored: %s", exc)
    return checks
