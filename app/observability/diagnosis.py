"""Failure diagnosis — a likely cause for a failed step, from evidence already collected.

Runs once per failed step inside ``FlowRunner.attach_evidence``, after the
evidence bundle is filled. It reads the step's error text, the console and
network entries of the step and of the earlier steps of its section (a 500
during a `goto` explains a missing text two steps later), the page address,
one render probe and one
observation of the page (for the closest control or text to a missing
target). No LLM. The verdict is a hint, never a result: the report labels
it "likely" and lists the signals behind it.

    application    the page or its backend misbehaved (5xx, JS error, blank page)
    timing         the page was still loading when the step ran
    test           the flow no longer matches the page (text changed, element covered, ambiguous)
    environment    network, browser or session problems
    framework      the flow or its setup, not the site (unset placeholder, missing sub-flow)
    unclassified   nothing conclusive — the signals are still listed

``triage`` is the cheap half, run by the engine *before* recovery: the same
signals (recorder deltas, one probe, the error text) reduced to one cause,
so the engine can retry a loading page once, skip the fuzzy and AI layers
when they cannot help, and never hide a server failure behind a retry.
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
_PLACEHOLDER_RE = re.compile(r"Variable '([A-Z_][A-Z0-9_]*)' is (not set|empty)")
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


# ── triage: one cause for a failed L1 attempt, before any recovery ──────────

# What the engine may still try for each cause. Anything not listed gets
# neither L2 nor L3: a fuzzier locator or an LLM cannot fix a blank page, a
# sign-in redirect, a covered control or a network that is down.
RETRY_AFTER_SETTLE = frozenset({"loading"})              # wait_stable once, then L1 again
L2_ONLY = frozenset({"server", "script"})                # fuzzy is cheap; an LLM call cannot help
FULL_CHAIN = frozenset({"not_found"})                    # the ordinary locator problem: L2 → L3

_COVERED_RE = re.compile(r"intercepts pointer events")
_AMBIGUOUS_RE = re.compile(r"strict mode violation")
_DISABLED_RE = re.compile(r"not enabled|element is disabled", re.IGNORECASE)
_BUSY_TYPES = frozenset({"document", "xhr", "fetch"})
_IN_FLIGHT_S = 15


def triage(error: str, action: Any, page: Any, recorder: Any = None, since_seq: int = 0,
           section_seq: int = 0, ignore: Any = None, prev_url: str = "") -> str:
    """The likely cause of an L1 failure, from what is already in memory plus
    one probe: ``network`` / ``closed`` (environment), ``server`` / ``script``
    / ``blank`` (application), ``loading`` (timing), ``session`` (the browser
    was sent from *prev_url* to a sign-in page), ``covered`` / ``ambiguous``
    / ``disabled`` (test), else ``not_found``. Never raises."""
    try:
        return _triage(error or "", action, page, recorder, since_seq, section_seq, ignore, prev_url)
    except Exception as exc:
        logger.debug("[triage] skipped: %s", exc)
        return "not_found"


def _triage(error: str, action: Any, page: Any, recorder: Any, since_seq: int,
            section_seq: int, ignore: Any, prev_url: str) -> str:
    if _NET_ENV_RE.search(error):
        return "network"
    if _CLOSED_RE.search(error):
        return "closed"
    if recorder is not None:
        if oracle.broken_requests(recorder, section_seq, ignore):
            return "server"
        if any(c.get("level") == "pageerror" for c in recorder.errors_since(since_seq, 50)):
            return "script"
    p = oracle.probe(page) or {}
    if p and not p.get("textLength"):
        return "blank"
    in_flight = bool(recorder is not None
                     and recorder.pending(_BUSY_TYPES, _IN_FLIGHT_S, tuple(getattr(ignore, "network", ()))))
    if p.get("spinner") or p.get("readyState") == "loading" or in_flight:
        return "loading"
    target = action.args[0] if getattr(action, "args", None) else ""
    try:
        url = page.url
    except Exception:
        url = ""
    # A sign-in page the flow was *sent to* (the step before ran elsewhere) —
    # not one it is working on, where a missing control is an ordinary locator problem.
    redirected = prev_url and not LOGIN_RE.search(prev_url)
    if redirected and url and LOGIN_RE.search(url) and not LOGIN_RE.search(target) and action.type != ActionType.GOTO:
        return "session"
    if _COVERED_RE.search(error):
        return "covered"
    if _AMBIGUOUS_RE.search(error):
        return "ambiguous"
    if _DISABLED_RE.search(error):
        return "disabled"
    return "not_found"


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
    """Render problems by name → detail: failed checks (blank page, overflow)
    and the notes the probe records only when seen (spinner, dialog)."""
    try:
        return {c.name: c.detail for c in oracle.probe_checks(page) if not c.passed or c.severity == "info"}
    except Exception:
        return {}


# What a step is meant to bring about, in the reader's words — the "Expected"
# line of a failure, derived from the action alone (never from a model).
_EXPECTED = {
    ActionType.GOTO: "the page at {t} opens and renders",
    ActionType.RELOAD: "the page reloads and renders",
    ActionType.BACK: "the previous page shows again",
    ActionType.CLICK: '"{t}" can be pressed and the page reacts',
    ActionType.CLICK_LINK_TEXT: 'the link "{t}" can be followed',
    ActionType.DOUBLE_CLICK: '"{t}" can be double-clicked and the page reacts',
    ActionType.TABLE_CLICK: 'the row "{t}" can be clicked',
    ActionType.FILL: '"{t}" accepts the value "{v}"',
    ActionType.TYPE: '"{t}" accepts the typed "{v}"',
    ActionType.SELECT: '"{v}" can be chosen in "{t}"',
    ActionType.CHECK: '"{t}" can be ticked',
    ActionType.UNCHECK: '"{t}" can be unticked',
    ActionType.ASSERT_TEXT: 'the text "{t}" is visible',
    ActionType.ASSERT_NOT_TEXT: 'the text "{t}" is not shown',
    ActionType.ASSERT_VISIBLE: '"{t}" is visible',
    ActionType.ASSERT_HIDDEN: '"{t}" is not visible',
    ActionType.ASSERT_URL: 'the address contains "{t}"',
    ActionType.ASSERT_ENABLED: '"{t}" is enabled',
    ActionType.ASSERT_DISABLED: '"{t}" is disabled',
    ActionType.ASSERT_CHECKED: '"{t}" is ticked',
    ActionType.WAIT_FOR_ELEMENT: '"{t}" appears',
    ActionType.WAIT_FOR_TEXT: 'the text "{t}" appears',
    ActionType.WAIT_FOR_URL: 'the address changes to contain "{t}"',
    ActionType.WAIT_STABLE: "the page settles",
}


def expected_of(action: Any) -> str:
    """The step's postcondition in plain words (``""`` for a skill or a sub-flow marker)."""
    args = list(getattr(action, "args", []) or [])
    t = args[0] if args else ""
    v = args[1] if len(args) > 1 else ""
    template = _EXPECTED.get(action.type)
    if template:
        return template.format(t=t, v=v)
    return f"{action.type.value.replace('_', ' ')}{' ' + repr(t) if t else ''} completes"


def _observed(ev: Any, probe: dict[str, str], error: str) -> str:
    """What the page showed at the failure, one line: where it was, render
    notes (blank, loading, a dialog), then the failure's first line."""
    parts: list[str] = []
    if ev and (ev.title or ev.url):
        parts.append(f"the page {ev.title!r} at {ev.url}" if ev.title else f"the page at {ev.url}")
    notes = [probe[k] for k in ("page rendered", "no stuck spinner", "no blocking dialog") if k in probe]
    parts += notes
    first = next((ln.strip() for ln in error.splitlines() if ln.strip()), "")
    if first:
        parts.append(first[:200])
    return "; ".join(parts)


def diagnose(sr: StepResult, page: Any, section: tuple[list, list] = ([], []),
             notes: list[str] | None = None) -> dict:
    """``{"verdict", "summary", "signals", "expected", "observed"}`` for a
    failed step. Never raises. *section* is ``(console, network)`` recorded
    since the step's section began; *notes* are facts the engine kept from
    earlier steps (a press that changed nothing)."""
    try:
        return _diagnose(sr, page, section, list(notes or []))
    except Exception as exc:
        logger.debug("[diagnosis] skipped: %s", exc)
        return {"verdict": "unclassified", "summary": "No diagnosis could be made.", "signals": [],
                "expected": expected_of(sr.action), "observed": ""}


def _diagnose(sr: StepResult, page: Any, section: tuple[list, list], notes: list[str]) -> dict:
    action, ev = sr.action, sr.evidence
    error = f"{sr.error or ''}\n{sr.message or ''}"
    target = action.args[0] if action.args else ""
    signals: list[str] = list(notes)
    verdict, summary = "", ""

    def conclude(v: str, s: str) -> None:
        nonlocal verdict, summary
        if not verdict:
            verdict, summary = v, s

    # ── what the engine's triage and recovery found before giving up ──
    layers = ev.layers if ev else {}
    cause = layers.get("triage", "")
    if recovery := layers.get("recovery"):
        signals.append(recovery)
    if cause.endswith("loading"):
        signals.append("the page was still loading when the step ran")
        conclude("timing", "The page was still loading: the content the step needed had not appeared yet"
                           + (", and it did not settle in time." if "did not settle" in recovery else "."))

    # ── framework: the flow or its setup, not the site ──
    if m := _PLACEHOLDER_RE.search(error):
        signals.append(f"placeholder {{{m.group(1)}}} has no value")
        conclude("framework", f"{m.group(1)} is {m.group(2)} in the environment (.env or CI variables).")
    if re.search(r"sub-flow|nesting depth|Circular flow", error):
        signals.append("the flow could not be assembled")
        conclude("framework", "The flow references a sub-flow that could not be loaded.")

    # ── environment: network, browser ──
    if m := _NET_ENV_RE.search(error):
        signals.append(f"network error {m.group(1)}")
        conclude("environment", f"The site could not be reached ({m.group(1)}).")
    if _CLOSED_RE.search(error):
        signals.append("the browser or page closed during the step")
        conclude("environment", "The browser or page closed while the step ran.")

    # ── application: what the browser recorded during the step ──
    def server_failures(network: list[dict]) -> list[dict]:
        return [n for n in network if (n.get("status") or 0) >= 500
                or (n.get("failure") and not oracle.cancelled(n))]

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
        conclude("timing", "The page was still loading — a slow or failing backend call.")

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
    return {"verdict": verdict, "summary": summary, "signals": signals[:MAX_SIGNALS],
            "expected": expected_of(action), "observed": _observed(ev, probe, sr.error or sr.message or "")}
