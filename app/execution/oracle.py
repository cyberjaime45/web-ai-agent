"""Oracle — automatic QA checks after a step, without an assertion in the flow.

Two sources, both cheap:
  recorder  — console errors / page errors / failed requests recorded since
              the step's sequence mark (in-memory, no browser call)
  probe     — one ``page.evaluate`` for render state: blank page, stuck
              spinner, blocking dialog, horizontal overflow

The engine runs it after successful navigation-class steps (goto, click…)
when ``ORACLE`` is ``warn`` (record only, the default) or ``strict`` (a
failed error-severity check fails the step). ``check_console_network`` and
``test_responsive`` reuse the same functions explicitly. Flow-level
``ignore_console`` / ``ignore_network`` patterns drop known noise.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from app.schemas.actions import ActionType, Check, FlowAction, summarize
from app.utils.urls import in_site

logger = logging.getLogger(__name__)

# Steps after which the page may have changed enough to be worth a look.
ORACLE_AFTER: frozenset[ActionType] = frozenset({
    ActionType.GOTO, ActionType.RELOAD, ActionType.BACK, ActionType.WAIT_LOAD,
    ActionType.CLICK, ActionType.CLICK_LINK_TEXT, ActionType.DOUBLE_CLICK,
    ActionType.TABLE_CLICK, ActionType.SELECT, ActionType.SWITCH_TAB,
    ActionType.WAIT_FOR_URL, ActionType.PRESS,
})


# The render probe's modal check. A skill's probe step drops it: opening a
# dialog is often exactly what the probe is for, and the skill judges that.
DIALOG_CHECK = "no blocking dialog"

# How far the page scrolls sideways — what a user can actually reach. The
# scrolling element's width, not body.scrollWidth (that counts content the
# viewport clips, e.g. a decorative image hanging off the edge), and nothing
# when the viewport clips (overflow-x hidden / clip on <html>, or on <body>
# when it propagates to the viewport). Shared with test_responsive.
H_OVERFLOW_JS = """(() => {
  const de = document.documentElement, se = document.scrollingElement || de;
  const clips = el => el && ['hidden', 'clip'].includes(getComputedStyle(el).overflowX);
  const viewportClips = clips(de) || (getComputedStyle(de).overflowX === 'visible' && clips(document.body));
  return viewportClips ? 0 : se.scrollWidth - de.clientWidth;
})()"""

# Visible loading indicators: the probe's "stuck spinner" and wait_stable's "busy".
BUSY_SELECTOR = '[class*="spinner" i], [class*="loading" i], [aria-busy="true"], [role="progressbar"]'


@dataclass
class IgnoreRules:
    console: list[str] = field(default_factory=list)   # substrings of console text
    network: list[str] = field(default_factory=list)   # substrings of request URLs

    def keeps_console(self, entry: dict) -> bool:
        """Drop console text matching a console pattern — and the browser's
        "Failed to load resource" echo of a request the network rules ignore
        (its ``location`` carries that URL)."""
        text = entry.get("text") or ""
        location = entry.get("location") or ""
        return not (any(p in text for p in self.console)
                    or any(p in location for p in self.network))

    def keeps_network(self, entry: dict) -> bool:
        url = entry.get("url") or ""
        return not any(p in url for p in self.network)


# ── recorder-based checks ────────────────────────────────────────────────────

# How each browser words a cancelled request: Chromium, Firefox, WebKit.  (report.js failedReq mirrors it)
_CANCELLED = ("ERR_ABORTED", "NS_BINDING_ABORTED", "cancelled")


def cancelled(entry: dict) -> bool:
    """A request the page or a navigation cancelled (``net::ERR_ABORTED``,
    ``NS_BINDING_ABORTED``, WebKit's "cancelled") — telemetry beacons, requests
    cut off by leaving the page. Not a failure."""
    failure = entry.get("failure") or ""
    return any(s in failure for s in _CANCELLED)


# What a failed request breaks, by what it was for.
_PAGE_OR_CODE = frozenset({"document", "script", "stylesheet"})     # the page itself
_API = frozenset({"xhr", "fetch", "eventsource", "websocket"})      # data the page asked for


def is_broken(entry: dict) -> bool:
    """A failed request that breaks the page: the document or its code did not
    load, or an API call failed on the server or never answered."""
    rt, status = entry.get("resource_type") or "", entry.get("status") or 0
    return rt in _PAGE_OR_CODE or (rt in _API and bool(entry.get("failure") or status >= 500))


def broken_requests(recorder: Any, since_seq: int, ignore: IgnoreRules | None = None) -> list[dict]:
    """Page-breaking failed requests since *since_seq* (``is_broken``, not cancelled)."""
    ignore = ignore or IgnoreRules()
    return [n for n in recorder.failures_since(since_seq, limit=200)
            if ignore.keeps_network(n) and not cancelled(n) and is_broken(n)]


def _location_url(entry: dict) -> str:
    """``https://x/app.js:12:5`` → ``https://x/app.js``."""
    loc = entry.get("location") or ""
    parts = loc.rsplit(":", 2)
    return parts[0] if len(parts) == 3 and parts[1].isdigit() else loc


def diagnostics_checks(recorder: Any, since_seq: int, ignore: IgnoreRules | None = None,
                       explicit: bool = False) -> list[Check]:
    """Page errors, console errors and failed requests since *since_seq*,
    judged in context — a log level or a status code alone is no impact:

      page errors (uncaught JS)                     error
      the page or its code failed (document /       error   "no failed requests"
      script / stylesheet 4xx-5xx, API 5xx or
      unreachable)
      API 401 / 403 (often: not signed in)          info    warn when explicit
      API 4xx (a lookup that found nothing…)        info    warn when explicit
      images, fonts, beacons that failed            info    warn when explicit
      console errors of the site's own scripts      info    warn when explicit
      console errors of other scripts               info
      cancelled requests                            info

    *explicit* is a flow that asked for the check (``check_console_network``,
    a form submission): a stated requirement, so the lower rows are warnings.
    The automatic checks after each step pass ``explicit=False``."""
    ignore = ignore or IgnoreRules()
    lesser = "warn" if explicit else "info"
    site = getattr(recorder, "site_domain", "")
    console = [c for c in recorder.errors_since(since_seq, limit=200) if ignore.keeps_console(c)]
    page_errors = [c["text"] for c in console if c["level"] == "pageerror"]
    own_errors, other_errors = [], []
    for c in (c for c in console if c["level"] == "error"):
        url = _location_url(c)
        (own_errors if not url or in_site(url, site) else other_errors).append(c["text"])
    recorded = [n for n in recorder.failures_since(since_seq, limit=200) if ignore.keeps_network(n)]
    dropped = [n for n in recorded if cancelled(n)]
    broken, auth, client, resources = [], [], [], []
    for n in (n for n in recorded if not cancelled(n)):
        rt, status = n.get("resource_type") or "", n.get("status") or 0
        if is_broken(n):
            broken.append(n)
        elif rt in _API:
            (auth if status in (401, 403) else client).append(n)
        else:
            resources.append(n)

    def req(n: dict) -> str:
        return f"{n['method']} {n['url']} → {n['failure'] or n['status']}"

    # Automatic mode lists the lesser rows only when they found something: an
    # empty info row after every step is noise, not a check.
    lesser_rows = [("no console errors", own_errors), ("no 401/403 responses", [req(n) for n in auth]),
                   ("no 4xx responses", [req(n) for n in client]),
                   ("no failed resources", [req(n) for n in resources])]
    checks = [
        Check.listing("no page errors", page_errors, "error"),
        Check.listing("no failed requests", [req(n) for n in broken], "error"),
        *(Check.listing(name, items, lesser) for name, items in lesser_rows
          if items or (explicit and name != "no failed resources")),
    ]
    if other_errors:
        checks.append(Check("console errors from other scripts", True, "info", summarize(other_errors, 3), len(other_errors)))
    if dropped:
        checks.append(Check("requests cancelled", True, "info",
                            summarize([req(n) for n in dropped], 3), len(dropped)))
    return checks


# ── render-state probe ───────────────────────────────────────────────────────

# One evaluate: render health (the checks) and the page's after-state (what a
# step brought up — heading, dialog, alert, focus, a hash of the visible text).
_PROBE_JS = r"""
() => {
  const vis = el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const words = el => (el && (el.innerText || el.textContent) || '').replace(/\s+/g, ' ').trim();
  const first = sel => [...document.querySelectorAll(sel)].find(vis);
  const spinners = [...document.querySelectorAll(__BUSY__)].filter(vis);
  const dialog = first('[role="dialog"], [role="alertdialog"], dialog[open]');
  const modal = dialog && (dialog.getAttribute('aria-modal') === 'true' || dialog.tagName === 'DIALOG');
  const alert = first('[role="alert"], [role="status"]');
  const text = (document.body && document.body.innerText || '').replace(/\s+/g, ' ').trim();
  let h = 5381;                                   // djb2 over the visible text: a cheap change detector
  for (let i = 0; i < text.length; i++) h = ((h << 5) + h + text.charCodeAt(i)) | 0;
  const ae = document.activeElement;
  return {
    readyState: document.readyState,
    textLength: text.length,
    hash: h,
    spinner: spinners.length,
    dialog: dialog ? (words(dialog.querySelector('h1, h2, h3, [role="heading"]')) || dialog.getAttribute('aria-label') || words(dialog).slice(0, 80)) : '',
    modal: !!modal,
    heading: words(first('main h1, h1') || first('main h2, h2')),
    alert: words(alert).slice(0, 200),
    active: ae && ae !== document.body ? (ae.tagName.toLowerCase() + (ae.id ? '#' + ae.id : '') + (ae.name ? '[' + ae.name + ']' : '')) : '',
    overflow: __OVERFLOW__,
  };
}
""".replace("__BUSY__", json.dumps(BUSY_SELECTOR)).replace("__OVERFLOW__", H_OVERFLOW_JS)

AFTER_KEYS = ("heading", "dialog", "alert", "hash", "active")


def probe(page: Any) -> dict | None:
    """The raw render probe, or ``None`` when the page cannot answer (navigating, closed)."""
    try:
        return page.evaluate(_PROBE_JS)
    except Exception as exc:
        logger.debug("[oracle] probe skipped: %s", exc)
        return None


def after_state(p: dict | None, url: str = "") -> dict:
    """What the page shows after a step (``StepResult.after``): the landmarks
    the writer turns into assertions, plus the hash and focus the effect check
    compares. Empty when there was no probe."""
    if not p:
        return {}
    state = {k: p.get(k, "" if k != "hash" else 0) for k in AFTER_KEYS}
    if url:
        state["url"] = url
    return state


def probe_checks(page: Any) -> list[Check]:
    """Blank page, stuck spinner, blocking dialog, horizontal overflow — one round-trip."""
    return checks_from_probe(probe(page))


def checks_from_probe(p: dict | None) -> list[Check]:
    if p is None:
        return []
    if not p.get("modal", True):        # a non-modal dialog does not block the page
        p = {**p, "dialog": ""}
    checks = [
        Check("page rendered", p["readyState"] != "loading" and p["textLength"] > 0, "error",
              "no visible text on the page" if not p["textLength"]
              else "the page was still loading" if p["readyState"] == "loading" else ""),
        Check("no horizontal overflow", p["overflow"] <= 1, "warn",
              f"content {p['overflow']}px wider than the viewport" if p["overflow"] > 1 else ""),
    ]
    # Recorded only when seen, as notes: one snapshot right after a step cannot
    # tell a stuck spinner from one still loading, and a dialog is often what
    # the step opened. A failed step's diagnosis still reads them.
    if p["spinner"]:
        checks.append(Check("no stuck spinner", True, "info",
                            f"{p['spinner']} loading indicator(s) visible right after the step", p["spinner"]))
    if p["dialog"]:
        checks.append(Check(DIALOG_CHECK, True, "info", f"modal dialog open: {p['dialog']}"))
    return checks


def run_checks(page: Any, recorder: Any | None, since_seq: int,
               ignore: IgnoreRules | None = None) -> list[Check]:
    """Everything the oracle knows how to check after a step."""
    return observe_after(page, recorder, since_seq, ignore)[1]


def observe_after(page: Any, recorder: Any | None, since_seq: int,
                  ignore: IgnoreRules | None = None) -> tuple[dict, list[Check]]:
    """``(after-state, checks)`` from one probe plus the recorder — what the
    engine keeps on a step after a navigation-class action."""
    checks = diagnostics_checks(recorder, since_seq, ignore) if recorder is not None else []
    p = probe(page)
    try:
        url = page.url
    except Exception:
        url = ""
    return after_state(p, url), checks + checks_from_probe(p)


# ── effect checks: did the action do anything? ──────────────────────────────
#
# Execution success only proves Playwright performed the action. These compare
# the page before and after (URL, visible text, dialog, alert, focus, requests)
# or read the control back. Warnings, never failures: a click that changes
# nothing can be legitimate (a tab already selected). Their value is as a
# signal — a later failure's diagnosis reads them.

# Presses whose effect should show on the page (a key press only for Enter).
EFFECT_AFTER: frozenset[ActionType] = frozenset({
    ActionType.CLICK, ActionType.CLICK_LINK_TEXT, ActionType.DOUBLE_CLICK, ActionType.TABLE_CLICK,
    ActionType.PRESS,
})
# Inputs whose value can be read back from the control.
READBACK: frozenset[ActionType] = frozenset({
    ActionType.FILL, ActionType.TYPE, ActionType.CHECK, ActionType.UNCHECK, ActionType.SELECT,
})
EFFECT_CHECK = "action changed the page"
READBACK_CHECK = "control holds the value"
_READ_TIMEOUT_MS = 1_000


# A press's effect is often asynchronous (a re-render after a request): give
# the page this long to differ from the state before the press before
# calling it a no-op. Returns the moment anything changes.
CHANGE_WAIT_MS = 1_500
_CHANGED_JS = """
([hash, href]) => {
  if (location.href !== href) return true;
  const text = (document.body && document.body.innerText || '').replace(/\\s+/g, ' ').trim();
  let h = 5381;
  for (let i = 0; i < text.length; i++) h = ((h << 5) + h + text.charCodeAt(i)) | 0;
  return h !== hash;
}
"""


def wait_for_change(page: Any, before: dict, timeout_ms: int = CHANGE_WAIT_MS) -> None:
    """Wait (bounded) until the page's URL or visible text differs from
    *before*; returns quietly either way."""
    if not before or "hash" not in before:
        return
    try:
        page.wait_for_function(_CHANGED_JS, arg=[before.get("hash", 0), before.get("url", "")],
                               polling=100, timeout=timeout_ms)
    except Exception:
        pass


def effect_check(action: FlowAction, before: dict, after: dict, requests: int) -> Check | None:
    """One warn check: the press changed something (URL, text, dialog, alert,
    focus) or made a request. ``None`` when there is nothing to compare or the
    action is not a press whose effect should show."""
    if action.type not in EFFECT_AFTER or not before or not after:
        return None
    if action.type == ActionType.PRESS and (action.args[0] if action.args else "Enter").lower() != "enter":
        return None
    changed = [k for k in ("url", *AFTER_KEYS) if before.get(k) != after.get(k)]
    if changed or requests:
        return Check(EFFECT_CHECK, True, "warn",
                     ", ".join(changed) + (f" and {requests} request(s)" if requests else "") if changed
                     else f"{requests} request(s)")
    target = action.args[0] if action.args else action.type.value
    return Check(EFFECT_CHECK, False, "warn",
                 f'"{target}" changed nothing visible: same URL and text, no dialog, alert, focus change or request')


def readback_check(action: FlowAction, locator: Any) -> Check | None:
    """One warn check: the control shows the value the step set. ``None`` when
    the control cannot be read (a custom widget) — never a failure."""
    target = action.args[0] if action.args else ""
    want = action.args[1] if len(action.args) > 1 else ""
    t = action.type
    try:
        if t in (ActionType.FILL, ActionType.TYPE):
            actual = locator.input_value(timeout=_READ_TIMEOUT_MS)
            ok = actual == want if t == ActionType.FILL else want in actual
            shown = actual if len(actual) <= 60 else actual[:57] + "…"
            return Check(READBACK_CHECK, ok, "warn", "" if ok else f'"{target}" reads {shown!r} after {t.value}')
        if t in (ActionType.CHECK, ActionType.UNCHECK):
            checked = locator.is_checked(timeout=_READ_TIMEOUT_MS)
            ok = checked == (t == ActionType.CHECK)
            return Check(READBACK_CHECK, ok, "warn",
                         "" if ok else f'"{target}" is {"checked" if checked else "unchecked"} after {t.value}')
        if t == ActionType.SELECT:
            chosen = locator.evaluate(
                "el => el.selectedOptions && el.selectedOptions[0]"
                " ? [el.selectedOptions[0].value, el.selectedOptions[0].text.trim()] : []",
                timeout=_READ_TIMEOUT_MS) or []
            ok = want in chosen
            return Check(READBACK_CHECK, ok, "warn",
                         "" if ok else f'"{target}" shows {chosen[1] if len(chosen) > 1 else "nothing"!r} after select')
    except Exception as exc:
        logger.debug("[oracle] read-back skipped: %s", exc)
    return None


def failed(checks: list[Check], severity: str = "error") -> list[Check]:
    return [c for c in checks if not c.passed and c.severity == severity]


def summary(checks: list[Check]) -> str:
    """``5 checks passed`` / ``1 of 5 checks failed, 2 warnings, 1 not verified``."""
    errors, warns = failed(checks), failed(checks, "warn")
    total = len([c for c in checks if c.severity in ("error", "warn")])
    unverified = sum(1 for c in checks if c.severity == "inconclusive")
    parts = []
    if errors:
        parts.append(f"{len(errors)} of {total} checks failed")
    elif not warns:
        parts.append(f"{total} check{'s' if total != 1 else ''} passed" if total else "no checks")
    if warns:
        parts.append(f"{len(warns)} warning{'s' if len(warns) > 1 else ''}")
    if unverified:
        parts.append(f"{unverified} not verified")
    return ", ".join(parts)
