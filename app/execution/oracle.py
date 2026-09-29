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

from app.schemas.actions import ActionType, Check, summarize

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


def diagnostics_checks(recorder: Any, since_seq: int, ignore: IgnoreRules | None = None) -> list[Check]:
    """Page errors, console errors and failed requests since *since_seq*;
    cancelled requests are an observation."""
    ignore = ignore or IgnoreRules()
    console = [c for c in recorder.errors_since(since_seq, limit=200) if ignore.keeps_console(c)]
    page_errors = [c["text"] for c in console if c["level"] == "pageerror"]
    errors = [c["text"] for c in console if c["level"] == "error"]
    recorded = [n for n in recorder.failures_since(since_seq, limit=200) if ignore.keeps_network(n)]
    dropped = [n for n in recorded if cancelled(n)]
    network = [n for n in recorded if not cancelled(n)]
    server = [n for n in network if n.get("failure") or (n.get("status") or 0) >= 500]
    auth = [n for n in network if n.get("status") in (401, 403)]
    client = [n for n in network if n not in server and n not in auth]

    def req(n: dict) -> str:
        return f"{n['method']} {n['url']} → {n['failure'] or n['status']}"

    checks = [
        Check.listing("no page errors", page_errors, "error"),
        Check.listing("no console errors", errors, "warn"),
        Check.listing("no failed requests", [req(n) for n in server], "error"),
        Check.listing("no 401/403 responses", [req(n) for n in auth], "error"),
        Check.listing("no 4xx responses", [req(n) for n in client], "warn"),
    ]
    if dropped:
        checks.append(Check("requests cancelled", True, "info",
                            summarize([req(n) for n in dropped], 3), len(dropped)))
    return checks


# ── render-state probe ───────────────────────────────────────────────────────

_PROBE_JS = r"""
() => {
  const vis = el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const spinners = [...document.querySelectorAll(__BUSY__)].filter(vis);
  const dialogs = [...document.querySelectorAll('[role="dialog"][aria-modal="true"], dialog[open]')].filter(vis);
  const de = document.documentElement;
  return {
    readyState: document.readyState,
    textLength: (document.body && document.body.innerText || '').trim().length,
    spinner: spinners.length,
    dialog: dialogs.length ? (dialogs[0].getAttribute('aria-label') || (dialogs[0].innerText || '').trim().slice(0, 80)) : '',
    overflow: __OVERFLOW__,
  };
}
""".replace("__BUSY__", json.dumps(BUSY_SELECTOR)).replace("__OVERFLOW__", H_OVERFLOW_JS)


def probe_checks(page: Any) -> list[Check]:
    """Blank page, stuck spinner, blocking dialog, horizontal overflow — one round-trip."""
    try:
        p = page.evaluate(_PROBE_JS)
    except Exception as exc:
        logger.debug("[oracle] probe skipped: %s", exc)
        return []
    return [
        Check("page rendered", p["readyState"] != "loading" and p["textLength"] > 0, "error",
              "no visible text on the page" if not p["textLength"]
              else "the page was still loading" if p["readyState"] == "loading" else ""),
        Check("no stuck spinner", not p["spinner"], "warn",
              f"{p['spinner']} loading indicator(s) visible" if p["spinner"] else "", p["spinner"]),
        Check(DIALOG_CHECK, not p["dialog"], "warn",
              f"modal dialog open: {p['dialog']}" if p["dialog"] else ""),
        Check("no horizontal overflow", p["overflow"] <= 1, "warn",
              f"content {p['overflow']}px wider than the viewport" if p["overflow"] > 1 else ""),
    ]


def run_checks(page: Any, recorder: Any | None, since_seq: int,
               ignore: IgnoreRules | None = None) -> list[Check]:
    """Everything the oracle knows how to check after a step."""
    checks = diagnostics_checks(recorder, since_seq, ignore) if recorder is not None else []
    return checks + probe_checks(page)


def failed(checks: list[Check], severity: str = "error") -> list[Check]:
    return [c for c in checks if not c.passed and c.severity == severity]


def summary(checks: list[Check]) -> str:
    """``5 checks passed`` / ``1 of 5 checks failed, 2 warnings``."""
    errors, warns = failed(checks), failed(checks, "warn")
    total = len([c for c in checks if c.severity in ("error", "warn")])
    if not errors and not warns:
        return f"{total} check{'s' if total != 1 else ''} passed" if total else "no checks"
    parts = []
    if errors:
        parts.append(f"{len(errors)} of {total} checks failed")
    if warns:
        parts.append(f"{len(warns)} warning{'s' if len(warns) > 1 else ''}")
    return ", ".join(parts)
