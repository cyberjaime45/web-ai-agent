"""L2 click target — the one control a click by name means, or a clear refusal.

Playwright's loose matches are substring matches: ``get_by_role("button",
name="Book")`` finds a share button named "Facebook", ``get_by_text("Book")``
finds "flights booked". L2 used to click the first such hit. Here a target is
chosen deterministically, and only when it is the one plausible control:

1. Candidates are **controls** — buttons, links, inputs of type button/submit,
   ``summary``, the interactive ARIA roles, ``[onclick]`` — then, only when no
   control matches, other elements the page styles as clickable
   (``cursor: pointer``). Plain text and containers never qualify.
2. Their name (``aria-labelledby``, ``aria-label``, visible text line by line,
   ``value``, image ``alt``, ``title``) is matched in tiers, strongest first:
   *exact* (the whole name or one visible line, case- and space-insensitive),
   *whole word* ("Book" in "Book now", never in "Facebook" or "booked"), then
   *word similarity* (the words of the two names, not their characters).
3. The first tier with a match decides. Its candidates must be visible and
   enabled; one left is clicked, several are ambiguous and fail the step with
   the list, none (all hidden or disabled) fails with that reason — a looser
   tier is never used to get past a stronger match that cannot be clicked.

``Resolution.summary`` records what was selected and why, for the report.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from difflib import SequenceMatcher

from playwright.sync_api import Locator, Page

CONTROLS = ("button, a[href], input[type=button], input[type=submit], input[type=reset], input[type=image], "
            "summary, [onclick], [role=button], [role=link], [role=menuitem], [role=menuitemcheckbox], "
            "[role=menuitemradio], [role=tab], [role=option], [role=switch], [role=checkbox], [role=radio], "
            "[role=treeitem]")
WORD_SIMILARITY = 0.6      # SequenceMatcher ratio over the two names' word lists
_MAX_LISTED = 5

# Each element against the target: {tier: 1 exact | 2 whole word | 0, name, words, usable, why, sig, role}.
# pointerOnly: keep only elements styled clickable that are not inside a control (the second pass).
_SCAN_JS = r"""(els, [target, pointerOnly, controls]) => {
  const norm = s => (s || '').replace(/\s+/g, ' ').trim().toLowerCase();
  const want = norm(target);
  const esc = want.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const word = new RegExp('(^|[^\\p{L}\\p{N}_])' + esc + '($|[^\\p{L}\\p{N}_])', 'u');
  const text = el => {
    const by = (el.getAttribute('aria-labelledby') || '').split(/\s+/).map(id => document.getElementById(id)).filter(Boolean);
    if (by.length) return by.map(e => e.innerText || e.textContent).join(' ');
    if (el.getAttribute('aria-label')) return el.getAttribute('aria-label');
    if (el.tagName === 'INPUT') return el.value || el.getAttribute('alt') || el.title || '';
    const shown = (el.innerText || '').trim();
    if (shown) return el.innerText;
    const alts = [...el.querySelectorAll('img[alt], svg title')].map(x => x.getAttribute('alt') || x.textContent).filter(Boolean);
    return alts.join(' ') || el.title || '';
  };
  return els.map((el, i) => {
    if (pointerOnly && (el.closest(controls) || getComputedStyle(el).cursor !== 'pointer')) return null;
    const raw = text(el), name = norm(raw);
    const lines = raw.split('\n').map(norm).filter(Boolean);
    const tier = name === want || lines.includes(want) ? 1 : word.test(name) || lines.some(l => word.test(l)) ? 2 : 0;
    const style = getComputedStyle(el);
    const hidden = !el.getClientRects().length || style.visibility === 'hidden' || style.opacity === '0';
    const disabled = el.disabled || !!el.closest('[aria-disabled="true"], fieldset[disabled]');
    const sig = el.tagName.toLowerCase() + (el.id ? '#' + el.id : '')
      + (el.getAttribute('data-testid') ? `[data-testid="${el.getAttribute('data-testid')}"]` : '')
      + (el.getAttribute('role') ? `[role="${el.getAttribute('role')}"]` : '');
    return {i, tier, name: raw.replace(/\s+/g, ' ').trim().slice(0, 80), words: name.match(/[\p{L}\p{N}]+/gu) || [],
            usable: !hidden && !disabled, why: hidden ? 'hidden' : disabled ? 'disabled' : '', sig,
            role: el.getAttribute('role') || (el.tagName === 'A' ? 'link' : el.tagName === 'BUTTON' || el.tagName === 'INPUT' ? 'button' : el.tagName.toLowerCase())};
  }).filter(Boolean);
}"""


@dataclass(frozen=True)
class Resolution:
    """The control L2 chose: where it is and why it is the one the step means."""
    locator: Locator
    role: str
    name: str
    selector: str          # a short signature: tag#id[data-testid][role]
    reason: str

    @property
    def summary(self) -> str:
        return f'{self.role} "{self.name}" ({self.selector}) — {self.reason}'


def _label(c: dict) -> str:
    return f'{c["role"]} "{c["name"]}"' + (f' ({c["why"]})' if c.get("why") else "")


def _decide(found: list[dict], locator: Locator, tier: str, target: str) -> Resolution | None:
    """The one usable candidate of a tier; raises when several are, None when none is (yet)."""
    usable = [c for c in found if c["usable"]]
    if len(usable) == 1:
        c = usable[0]
        others = len(found) - 1
        return Resolution(locator.nth(c["i"]), c["role"], c["name"], c["sig"],
                          f'{tier} for "{target}"' + (f"; {others} hidden or disabled match(es) ignored" if others else ""))
    if len(usable) > 1:
        listed = ", ".join(_label(c) for c in usable[:_MAX_LISTED]) + (" …" if len(usable) > _MAX_LISTED else "")
        raise RuntimeError(f'L2: "{target}" is ambiguous — {len(usable)} visible, enabled controls match '
                           f"({tier}): {listed}. Use a more specific name or a selector.")
    return None


def _word_similar(found: list[dict], target_words: list[str]) -> list[dict]:
    """Usable candidates whose words are most like the target's (ratio ≥ WORD_SIMILARITY), best first."""
    scored = [(SequenceMatcher(None, target_words, c["words"]).ratio(), c) for c in found if c["usable"] and c["words"]]
    best = max((s for s, _ in scored), default=0.0)
    return [c for s, c in scored if s >= WORD_SIMILARITY and s == best]


def resolve(page: Page, target: str, timeout_s: float = 5.0, poll_ms: int = 200) -> Resolution:
    """The control *target* names, polled while the page may still render it.

    Raises RuntimeError with the reason when the target is ambiguous, or when
    nothing plausible (or only hidden / disabled matches) is found in time."""
    controls, texts = page.locator(CONTROLS), page.get_by_text(target)
    target_words = "".join(ch if ch.isalnum() else " " for ch in target.lower()).split()
    deadline = time.monotonic() + timeout_s
    blocked: list[dict] = []
    while True:
        scan = controls.evaluate_all(_SCAN_JS, [target, False, CONTROLS])
        pointer = None   # scanned only when no control matches a tier
        for tier, label in ((1, "exact name"), (2, "whole-word match")):
            found = [c for c in scan if c["tier"] == tier]
            if found:
                chosen = _decide(found, controls, f"{label} of a control", target)
                if chosen:
                    return chosen
                blocked = found
                break
            pointer = pointer if pointer is not None else texts.evaluate_all(_SCAN_JS, [target, True, CONTROLS])
            found = [c for c in pointer if c["tier"] == tier]
            if found:
                chosen = _decide(found, texts, f"{label} of an element styled as clickable", target)
                if chosen:
                    return chosen
                blocked = found
                break
        else:
            similar = _word_similar(scan, target_words)
            chosen = _decide(similar, controls, "closest wording of a control", target) if similar else None
            if chosen:
                return chosen
        if time.monotonic() >= deadline:
            break
        page.wait_for_timeout(poll_ms)
    if blocked:
        raise RuntimeError(f'L2: found {", ".join(_label(c) for c in blocked[:_MAX_LISTED])} for "{target}", '
                           f"but none can be clicked.")
    raise RuntimeError(f'L2: no visible control is named "{target}" — no button, link or other control has that name '
                       f"or that whole word in it; text that only contains it (\"booked\" for \"Book\") is not a target.")
