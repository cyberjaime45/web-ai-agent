"""Page stability — the ``wait_stable`` action.

A page is settled when three things hold together:

  network   no document / XHR / fetch request in flight (the flow's
            PageRecorder tracks them; skipped when a run has no recorder).
            Requests older than LONG_LIVED_S count as polling or streaming,
            and ``ignore_network`` patterns never block.
  busy      no visible loading indicator (``oracle.BUSY_SELECTOR``)
  quiet     no DOM change (child list or text) for QUIET_MS

Everything waits through Playwright (``wait_for_timeout`` between recorder
polls, ``wait_for_function`` in the page) inside one time budget.
"""

from __future__ import annotations

import time
from typing import Any

from app.execution.oracle import BUSY_SELECTOR
from app.schemas.actions import Check

DEFAULT_TIMEOUT_MS = 10_000
QUIET_MS = 300
POLL_MS = 100
LONG_LIVED_S = 15
REQUEST_TYPES = frozenset({"document", "xhr", "fetch"})

_SETTLED_JS = """
([quiet, busySelector]) => {
  const w = window;
  if (!w.__webAgentStable) {
    w.__webAgentStable = { last: Date.now() };
    new MutationObserver(() => { w.__webAgentStable.last = Date.now(); })
      .observe(document, { childList: true, subtree: true, characterData: true });
  }
  const vis = el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const busy = [...document.querySelectorAll(busySelector)].filter(vis).length;
  return busy === 0 && Date.now() - w.__webAgentStable.last >= quiet;
}
"""

_STATE_JS = """
(busySelector) => {
  const vis = el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const s = window.__webAgentStable;
  return { busy: [...document.querySelectorAll(busySelector)].filter(vis).length,
           idle: s ? Date.now() - s.last : 0 };
}
"""


def _describe(urls: list[str]) -> str:
    more = f" (+{len(urls) - 3} more)" if len(urls) > 3 else ""
    return f"{len(urls)} request(s) still in flight: {', '.join(urls[:3])}{more}"


def wait_stable(page: Any, recorder: Any, ignore_network: tuple[str, ...],
                budget_ms: int = DEFAULT_TIMEOUT_MS) -> str:
    """Wait until the page is settled; ``""`` when it is, else why it is not."""
    deadline = time.monotonic() + budget_ms / 1000

    if recorder is not None:
        while pending := recorder.pending(REQUEST_TYPES, LONG_LIVED_S, ignore_network):
            if time.monotonic() >= deadline:
                return _describe(pending)
            page.wait_for_timeout(POLL_MS)

    remaining_ms = max(int((deadline - time.monotonic()) * 1000), 1)
    try:
        page.wait_for_function(_SETTLED_JS, arg=[QUIET_MS, BUSY_SELECTOR],
                               polling=POLL_MS, timeout=remaining_ms)
        return ""
    except Exception:
        try:
            state = page.evaluate(_STATE_JS, BUSY_SELECTOR)
        except Exception:
            return "page did not settle"
        if state["busy"]:
            return f"{state['busy']} loading indicator(s) still visible"
        return f"page content still changing (last change {state['idle']} ms ago)"


def run(page: Any, recorder: Any, ignore_network: tuple[str, ...],
        args: list[str]) -> tuple[str, list[Check]]:
    """The ``wait_stable`` step: ``(message, checks)``. Never fails — a page
    still busy after the budget passes with a ``page settled`` warning."""
    arg = args[0].strip() if args else ""
    if arg and not arg.isdigit():
        raise ValueError(f"wait_stable takes a timeout in milliseconds, got {arg!r}")
    t0 = time.monotonic()
    unsettled = wait_stable(page, recorder, ignore_network, int(arg) if arg else DEFAULT_TIMEOUT_MS)
    elapsed = round((time.monotonic() - t0) * 1000)
    if unsettled:
        return (f"Page not settled after {elapsed} ms: {unsettled}",
                [Check("page settled", False, "warn", unsettled)])
    return f"Page settled in {elapsed} ms", []
