"""Safety policy — which controls an autonomous skill must not press.

Deterministic, and consulted before every click a skill chose by itself
(explore_page, a planner suggestion, a submit button). Three signals:

  name       the control's accessible name carries a destructive verb
             ("Delete", "Pay now", "Unsubscribe")
  container  a neutral confirm button ("OK", "Yes", "Continue") inside a
             dialog or form whose own name is destructive ("Delete member?")
             or about money ("Payment details")
  url        a confirm button on a page whose path says delete / checkout /
             payment / unsubscribe

Overrides are configuration, never AI: ``allow_destructive: true`` in a flow's
``## Config`` (or ALLOW_DESTRUCTIVE=true for an environment) lifts the block,
and ``allow_actions: "Send message" | "Publish"`` whitelists named controls.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from urllib.parse import urlparse

DESTRUCTIVE_WORDS: tuple[str, ...] = (
    "delete", "remove", "deactivate", "cancel", "publish", "approve", "reject",
    "send", "pay", "purchase", "buy", "book", "refund", "terminate", "reset",
    "erase", "destroy", "unsubscribe", "disable", "archive", "checkout",
    "submit payment", "place order", "confirm order",
)
# Neutral names that only mean something through their context.
CONFIRM_WORDS: tuple[str, ...] = (
    "ok", "yes", "confirm", "continue", "proceed", "submit", "save", "apply", "done", "accept",
)
MONEY_WORDS: tuple[str, ...] = ("payment", "checkout", "billing", "card", "purchase", "order")
DESTRUCTIVE_PATHS: tuple[str, ...] = (
    "delete", "remove", "checkout", "payment", "unsubscribe", "cancel", "terminate", "deactivate",
)

_WORD_RE = re.compile(r"[a-z]+(?: [a-z]+)?")


def _words(text: str) -> set[str]:
    lower = (text or "").lower()
    singles = set(re.findall(r"[a-z]+", lower))
    pairs = {f"{a} {b}" for a, b in zip(lower.split(), lower.split()[1:])}
    return singles | pairs


def destructive_word(name: str) -> str | None:
    """The destructive verb in *name* (whole word), or None."""
    words = _words(name)
    return next((w for w in DESTRUCTIVE_WORDS if w in words), None)


def is_destructive(name: str) -> bool:
    """True when the control's name alone carries a destructive verb."""
    return destructive_word(name) is not None


@dataclass(frozen=True)
class Verdict:
    allowed: bool
    reason: str = ""


@dataclass(frozen=True)
class SafetyPolicy:
    destructive_allowed: bool = False
    allow: tuple[str, ...] = ()          # control names explicitly permitted (case-insensitive substring)

    def with_destructive(self, allowed: bool) -> SafetyPolicy:
        return replace(self, destructive_allowed=allowed)

    def verdict(self, name: str, *, role: str = "", container: str = "", url: str = "") -> Verdict:
        """Judge pressing *name*. ``container`` is the enclosing dialog / form /
        region label as the observer reports it (``dialog:Delete member?``)."""
        lower = (name or "").lower().strip()
        if self.destructive_allowed:
            return Verdict(True, "destructive actions allowed by configuration")
        if any(a and a.lower() in lower for a in self.allow):
            return Verdict(True, "allowed by allow_actions")
        if word := destructive_word(name):
            return Verdict(False, f"name contains '{word}'")
        confirmish = lower in CONFIRM_WORDS or any(lower.startswith(w + " ") for w in CONFIRM_WORDS)
        if confirmish:
            kind, _, label = (container or "").partition(":")
            if word := destructive_word(label):
                return Verdict(False, f"confirms {kind or 'a container'} '{label}' ({word})")
            if any(m in label.lower() for m in MONEY_WORDS):
                return Verdict(False, f"confirms {kind or 'a container'} '{label}' (payment context)")
            path = urlparse(url or "").path.lower()
            if hit := next((p for p in DESTRUCTIVE_PATHS if p in path), None):
                return Verdict(False, f"confirm button on a '{hit}' page")
        return Verdict(True)

    def allows(self, name: str, **context: str) -> bool:
        return self.verdict(name, **context).allowed
