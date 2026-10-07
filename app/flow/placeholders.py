"""Flow-level facts derived from a flow's steps before they run.

``resolve_env_placeholders`` fills ``{NAME}`` placeholders in a step's
arguments from the environment (``.env`` and CI variables, loaded by
``settings``) — anywhere in an argument, so ``"{APP_URL}/members?tab=1"``
keeps its path and query. The legacy ``<NAME>`` spelling is still read.
Sensitive values are masked in the step text the report shows.
``flow_site_domain`` names the site under test from the first ``goto``.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable

from app.schemas.actions import ActionType, FlowAction
from app.utils.urls import site_domain

# ── Environment variable placeholder resolution ─────────────────────────────
# ``{NAME}`` (canonical) or ``<NAME>`` (legacy): upper-case letters, digits, underscores.
PLACEHOLDER_RE = re.compile(r"\{([A-Z_][A-Z0-9_]*)\}|<([A-Z_][A-Z0-9_]*)>")
_SENSITIVE_KEYWORDS = {"PASSWORD", "SECRET", "KEY", "TOKEN"}
_MASK = "******"


class PlaceholderError(RuntimeError):
    """A step references a variable that is not set or is empty."""


def is_sensitive(var_name: str) -> bool:
    """Return True if the env var name contains a sensitive keyword."""
    upper = var_name.upper()
    return any(kw in upper for kw in _SENSITIVE_KEYWORDS)


def placeholder_names(text: str) -> list[str]:
    """The variable names *text* references, in order, without repeats."""
    return list(dict.fromkeys(m.group(1) or m.group(2) for m in PLACEHOLDER_RE.finditer(text)))


def substitute(text: str, lookup: Callable[[str], str | None]) -> tuple[str, list[str]]:
    """``(text with every placeholder filled by lookup(name), names left unfilled)``.

    A name whose value is missing or blank is left as written and reported.
    A value ending in ``/`` followed by ``/`` in the text loses its own slash,
    so ``{APP_URL}/path`` works whether or not ``APP_URL`` ends in one.
    """
    unfilled: list[str] = []

    def fill(m: re.Match) -> str:
        name = m.group(1) or m.group(2)
        value = lookup(name)
        if value is None or not value.strip():
            if name not in unfilled:
                unfilled.append(name)
            return m.group(0)
        if value.endswith("/") and text.startswith("/", m.end()):
            value = value[:-1]
        return value

    return PLACEHOLDER_RE.sub(fill, text), unfilled


def resolve_env_placeholders(action: FlowAction) -> FlowAction:
    """Return a copy of *action* with ``{NAME}`` / ``<NAME>`` placeholders resolved.

    - Every argument is resolved the same way; the rest of the text is kept.
    - ``action.raw`` is rewritten with sensitive values masked as ``******``.
    - A variable that is not set or is empty raises ``PlaceholderError`` naming
      it and the step, so the step fails before anything runs.
    """
    if not any(PLACEHOLDER_RE.search(arg) for arg in action.args):
        return action  # nothing to resolve — return original (no copy needed)

    resolved_args: list[str] = []
    unfilled: list[str] = []
    for arg in action.args:
        value, missing = substitute(arg, os.environ.get)
        resolved_args.append(value)
        unfilled += [n for n in missing if n not in unfilled]
    if unfilled:
        raise PlaceholderError(_unfilled_message(unfilled, action))

    masked_raw, _ = substitute(
        action.raw, lambda name: _MASK if is_sensitive(name) else os.environ.get(name))
    return FlowAction(
        type=action.type,
        args=resolved_args,
        raw=masked_raw,
        step_num=action.step_num,
        section=action.section,
    )


def _unfilled_message(names: list[str], action: FlowAction) -> str:
    problems = "; ".join(
        f"Variable '{n}' is {'empty' if n in os.environ else 'not set'}" for n in names)
    where = f"step {action.step_num}" + (f" in section '{action.section}'" if action.section else "")
    return f"{problems} — set it in .env or the CI variables (referenced in {where}: {action.raw!r})"


def flow_site_domain(flow) -> str:
    """The site under test, whose requests are recorded: the flow's
    ``site_domain:`` override, else the registrable domain of its first
    ``goto`` step (placeholders resolved). ``""`` when the flow
    opens its first page some other way (a ``run_flow`` component) — the
    recorder then takes the domain of the first page load."""
    if getattr(flow, "site_domain", ""):
        return flow.site_domain
    first = next((a for a in flow.actions if a.type == ActionType.GOTO and a.args), None)
    if first is None:
        return ""
    try:
        return site_domain(resolve_env_placeholders(first).args[0])
    except PlaceholderError:                   # placeholder not set: the step itself will say so
        return ""
