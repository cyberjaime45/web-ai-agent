"""inspect_page — describe the current page; no browser actions, no AI.

Every finding is an info check. The compact observation is also stored in
``RunContext.data`` (``page_type``, ``observation``) for later skills and
for the planner in Phase 3.
"""

from __future__ import annotations

from app.agent.observer import Observation
from app.schemas.actions import ActionType, Check
from app.skills.base import SkillContext, info, skill

MAX_NAMES = 8


def _names(ob: Observation, *roles: str) -> str:
    nodes = ob.by_role(*roles)
    names = [n.name or f"({n.role})" for n in nodes[:MAX_NAMES]]
    more = len(nodes) - len(names)
    return f"{len(nodes)}: " + ", ".join(names) + (f", +{more} more" if more > 0 else "") if nodes else "0"


@skill(ActionType.INSPECT_PAGE)
def inspect_page(sc: SkillContext) -> list[Check]:
    ob = sc.observe()
    sc.ctx.store("page_type", ob.page_type)
    sc.ctx.store("observation", ob.to_prompt())

    checks = [
        info("page type", ob.page_type),
        info("url", ob.url),
        info("title", ob.title),
        info("headings", _names(ob, "heading")),
        info("buttons", _names(ob, "button")),
        info("links", _names(ob, "link")),
        info("inputs", _names(ob, "textbox", "searchbox", "combobox", "checkbox", "radio", "switch")),
    ]
    for form in ob.forms:
        required = sum(1 for f in form.fields if f.required)
        kinds = ", ".join(f"{f.label} ({f.type}{', required' if f.required else ''})" for f in form.fields[:MAX_NAMES])
        checks.append(info(f"form: {form.name}",
                           f"{len(form.fields)} fields, {required} required; submit: "
                           f"{', '.join(form.submits) or '—'}; {kinds}"))
    if ob.tables:
        checks.append(info("tables", str(ob.tables)))
    if ob.dialogs:
        checks.append(info("dialogs", f"{ob.dialogs} open"))
    if ob.nav:
        checks.append(info("navigation", f"{ob.nav} landmark(s)"))
    checks.append(Check("page has a heading", bool(ob.headings), "warn",
                        "" if ob.headings else "no heading role in the accessibility tree"))
    if ob.truncated:
        checks.append(info("observation truncated", "the accessibility tree was cut for size"))
    return checks
