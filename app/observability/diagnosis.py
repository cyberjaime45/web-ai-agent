"""Failure diagnosis — a likely cause for a failed step, from evidence already collected.

Runs once per failed step inside ``FlowRunner.attach_evidence``, after the
evidence bundle is filled. It reads the step's error text, the console and
network entries of the step and of the earlier steps of its section (a 500
during a `goto` explains a missing text two steps later), the page address,
one render probe and one
observation of the page (for the closest control or text to a missing
target). No LLM. The verdict is a hint, never a result: the report labels
it "likely" and lists the signals behind it.

    application    the page or its backend misbehaved (5xx, JS error, blank page, stuck loading)
    test           the flow no longer matches the page (text changed, element covered, ambiguous)
    environment    network, browser, configuration or session problems
    unclassified   nothing conclusive — the signals are still listed
"""

from __future__ import annotations

import difflib
import logging
import re
from typing import Any

from app.execution import oracle
from app.schemas.actions import ActionType, StepResult
from app.utils.urls import LOGIN_RE

logger = logging.getLogger(__name__)

NEAR_MATCH = 0.7                # similarity for "the text probably changed"
MAX_SIGNALS = 6

_NET_ENV_RE = re.compile(r"net::(ERR_NAME_NOT_RESOLVED|ERR_CONNECTION_REFUSED|ERR_CONNECTION_RESET|"
                         r"ERR_CONNECTION_TIMED_OUT|ERR_INTERNET_DISCONNECTED|ERR_ADDRESS_UNREACHABLE|"
                         r"ERR_CERT_[A-Z_]+|ERR_SSL_[A-Z_]+|ERR_PROXY_[A-Z_]+)")
_CLOSED_RE = re.compile(r"(Target page, context or browser has been closed|Browser has been closed|"
                        r"browser has disconnected)", re.IGNORECASE)
_PLACEHOLDER_RE = re.compile(r"Environment variable '([A-Z_][A-Z0-9_]*)' is not set")
_NOT_FOUND_RE = re.compile(r"Timeout \d+ms exceeded|could not resolve|not found|No table row", re.IGNORECASE)

_TEXT_TARGETS = frozenset({
    ActionType.ASSERT_TEXT, ActionType.WAIT_FOR_TEXT, ActionType.ASSERT_VISIBLE,
    ActionType.WAIT_FOR_ELEMENT,
})
_ELEMENT_TARGETS = frozenset({
    ActionType.CLICK, ActionType.CLICK_LINK_TEXT, ActionType.DOUBLE_CLICK, ActionType.RIGHT_CLICK,
    ActionType.HOVER, ActionType.FILL, ActionType.TYPE, ActionType.CLEAR, ActionType.FOCUS,
    ActionType.SELECT, ActionType.CHECK, ActionType.UNCHECK, ActionType.ASSERT_ENABLED,
    ActionType.ASSERT_DISABLED, ActionType.ASSERT_CHECKED,
})


def _names(page: Any) -> list[str]:
    """Headings, controls and form field labels on the page, for near matches."""
    from app.agent.observer import observe  # imported lazily: only failures pay for it
    try:
        ob = observe(page)
    except Exception as exc:
        logger.debug("[diagnosis] observation skipped: %s", exc)
        return []
    names = [n.name for n in ob.nodes if n.name]
    names += [f.label for form in ob.forms for f in form.fields if f.label]
    return list(dict.fromkeys(names))


def closest(target: str, names: list[str]) -> tuple[str, float]:
    """The name most similar to *target* (case-insensitive) and its ratio."""
    best, score = "", 0.0
    t = target.lower().strip()
    for name in names:
        ratio = difflib.SequenceMatcher(None, t, name.lower().strip()).ratio()
        if ratio > score:
            best, score = name, ratio
    return best, score


def _probe(page: Any) -> dict[str, str]:
    """Failed render checks by name → detail (blank page, spinner, dialog)."""
    try:
        return {c.name: c.detail for c in oracle.probe_checks(page) if not c.passed}
    except Exception:
        return {}


def diagnose(sr: StepResult, page: Any, section: tuple[list, list] = ([], [])) -> dict:
    """``{"verdict", "summary", "signals"}`` for a failed step. Never raises.
    *section* is ``(console, network)`` recorded since the step's section began."""
    try:
        return _diagnose(sr, page, section)
    except Exception as exc:
        logger.debug("[diagnosis] skipped: %s", exc)
        return {"verdict": "unclassified", "summary": "No diagnosis could be made.", "signals": []}


def _diagnose(sr: StepResult, page: Any, section: tuple[list, list]) -> dict:
    action, ev = sr.action, sr.evidence
    error = f"{sr.error or ''}\n{sr.message or ''}"
    target = action.args[0] if action.args else ""
    signals: list[str] = []
    verdict, summary = "", ""

    def conclude(v: str, s: str) -> None:
        nonlocal verdict, summary
        if not verdict:
            verdict, summary = v, s

    # ── environment: configuration, network, browser ──
    if m := _PLACEHOLDER_RE.search(error):
        signals.append(f"placeholder <{m.group(1)}> has no value")
        conclude("environment", f"<{m.group(1)}> is not set in the environment (.env or CI variables).")
    if m := _NET_ENV_RE.search(error):
        signals.append(f"network error {m.group(1)}")
        conclude("environment", f"The site could not be reached ({m.group(1)}).")
    if _CLOSED_RE.search(error):
        signals.append("the browser or page closed during the step")
        conclude("environment", "The browser or page closed while the step ran.")

    # ── application: what the browser recorded during the step ──
    def server_failures(network: list[dict]) -> list[dict]:
        return [n for n in network if (n.get("status") or 0) >= 500
                or (n.get("failure") and "ERR_ABORTED" not in n.get("failure", ""))]

    def page_errors(console: list[dict]) -> list[str]:
        return [c.get("text", "") for c in console if c.get("level") == "pageerror"]

    step_console, step_network = (ev.console, ev.network) if ev else ([], [])
    for when, console, network in (("during this step", step_console, step_network),
                                   ("earlier in this section", *section)):
        if server := server_failures(network):
            n = server[0]
            signals.append(f"{len(server)} failed request(s) {when}, e.g. {n.get('method')} "
                           f"{n.get('url')} → {n.get('failure') or n.get('status')}")
            conclude("application", f"A request the page made failed on the server {when}.")
        if errors := page_errors(console):
            signals.append(f"JavaScript error {when}: {errors[0][:120]}")
            if when == "during this step":      # earlier ones are often unrelated third-party noise
                conclude("application", f"The page threw a JavaScript error {when}.")
        if verdict:
            break
    auth = [n for n in (step_network or section[1]) if n.get("status") in (401, 403)]

    probe = _probe(page)
    if "page rendered" in probe:
        signals.append("the page shows no visible text")
        conclude("application", "The page did not render.")
    if "no stuck spinner" in probe:
        signals.append(probe["no stuck spinner"])
        conclude("application", "The page was still loading — a slow or failing backend call.")

    # ── session ──
    url = ev.url if ev else ""
    if url and LOGIN_RE.search(url) and not LOGIN_RE.search(target) and action.type != ActionType.GOTO:
        signals.append(f"the browser is on a sign-in page: {url}")
        conclude("environment", "The browser ended up on a sign-in page: the session expired or the user was signed out.")
    if auth:
        signals.append(f"{len(auth)} request(s) refused with {auth[0].get('status')}")
        conclude("environment", "The server refused a request (401/403): missing session or permissions.")

    # ── test: the flow no longer matches the page ──
    if re.search(r"intercepts pointer events", error):
        signals.append("another element covered the target")
        if "no blocking dialog" in probe:
            signals.append(probe["no blocking dialog"])
        conclude("test", f'"{target}" was covered by another element (a banner, modal or overlay).')
    if re.search(r"strict mode violation", error):
        signals.append("more than one element matched the target")
        conclude("test", f'"{target}" matches several elements; the step needs a more specific target.')
    if re.search(r"not enabled|element is disabled", error, re.IGNORECASE):
        signals.append("the target was disabled")
        conclude("test", f'"{target}" was disabled: an earlier step or a required field may be missing.')

    missing = target and _NOT_FOUND_RE.search(error) and (
        action.type in _TEXT_TARGETS or action.type in _ELEMENT_TARGETS)
    if missing and not verdict:
        near, score = closest(target, _names(page))
        if near and score >= NEAR_MATCH and near.lower() != target.lower():
            signals.append(f'closest on the page: "{near}" ({score:.0%} similar)')
            conclude("test", f'"{target}" is not on the page, but "{near}" is — the text probably changed.')
        elif action.type in _TEXT_TARGETS:
            signals.append("nothing similar is on the page")
            conclude("unclassified", f'"{target}" is not on the page and nothing similar is: '
                                     "the content changed or did not load.")
        else:
            signals.append("no control with a similar name is on the page")
            conclude("unclassified", f'No control named "{target}" is on the page.')

    if url and not any(s.startswith("the browser is on") for s in signals):
        signals.append(f"page at the failure: {url}")
    conclude("unclassified", "The signals collected do not point to a single cause.")
    return {"verdict": verdict, "summary": summary, "signals": signals[:MAX_SIGNALS]}
