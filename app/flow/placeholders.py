"""Flow-level facts derived from a flow's steps before they run.

``resolve_env_placeholders`` fills ``<ENV_VAR>`` arguments from the
environment (sensitive values masked in the step text the report shows);
``flow_site_domain`` names the site under test from the first ``goto``.
"""

from __future__ import annotations

import os
import re

from app.schemas.actions import ActionType, FlowAction
from app.utils.urls import site_domain

# ── Environment variable placeholder resolution ─────────────────────────────
_ENV_PLACEHOLDER_RE = re.compile(r"^<([A-Z_][A-Z0-9_]*)>$")
_SENSITIVE_KEYWORDS = {"PASSWORD", "SECRET", "KEY", "TOKEN"}
_MASK = "******"


def is_sensitive(var_name: str) -> bool:
    """Return True if the env var name contains a sensitive keyword."""
    upper = var_name.upper()
    return any(kw in upper for kw in _SENSITIVE_KEYWORDS)


def resolve_env_placeholders(action: FlowAction) -> FlowAction:
    """Return a copy of *action* with ``<ENV_VAR>`` placeholders resolved.

    - Resolved args contain real values (for execution).
    - ``action.raw`` is rewritten with sensitive values masked as ``******``.
    - Non-sensitive placeholders (e.g. ``<FMS_EMAIL>``) show the resolved value.
    - If the env var is not set, raises ``RuntimeError`` with a helpful message.
    """
    has_placeholder = False
    for arg in action.args:
        if _ENV_PLACEHOLDER_RE.match(arg):
            has_placeholder = True
            break

    if not has_placeholder:
        return action  # nothing to resolve — return original (no copy needed)

    resolved_args: list[str] = []
    masked_raw = action.raw

    for arg in action.args:
        m = _ENV_PLACEHOLDER_RE.match(arg)
        if not m:
            resolved_args.append(arg)
            continue

        var_name = m.group(1)
        value = os.environ.get(var_name)
        if value is None:
            raise RuntimeError(
                f"Environment variable '{var_name}' is not set "
                f"(referenced in step {action.step_num}: {action.raw!r})"
            )

        resolved_args.append(value)
        display = _MASK if is_sensitive(var_name) else value
        masked_raw = masked_raw.replace(f"<{var_name}>", display)

    return FlowAction(
        type=action.type,
        args=resolved_args,
        raw=masked_raw,
        step_num=action.step_num,
        section=action.section,
    )


def flow_site_domain(flow) -> str:
    """The site under test, whose requests are recorded: the flow's
    ``site_domain:`` override, else the registrable domain of its first
    ``goto`` step (``<ENV_VAR>`` placeholders resolved). ``""`` when the flow
    opens its first page some other way (a ``run_flow`` component) — the
    recorder then takes the domain of the first page load."""
    if getattr(flow, "site_domain", ""):
        return flow.site_domain
    first = next((a for a in flow.actions if a.type == ActionType.GOTO and a.args), None)
    if first is None:
        return ""
    try:
        return site_domain(resolve_env_placeholders(first).args[0])
    except RuntimeError:                       # placeholder not set: the step itself will say so
        return ""
