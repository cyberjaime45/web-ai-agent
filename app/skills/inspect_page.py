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


def structured(ob: Observation, max_names: int = 40) -> dict:
    """The observation as plain data, for the report and for clients that build
    flows from it (the Web Agent MCP's ``exploration``): controls by role, and
    every form with its fields' labels, types and targets a step can use."""
    def names(*roles: str) -> list[str]:
        return [n.name or f"({n.role})" for n in ob.by_role(*roles)[:max_names]]
    return {
        "url": ob.url, "title": ob.title, "page_type": ob.page_type,
        "headings": names("heading"), "buttons": names("button"), "links": names("link"),
        "inputs": names("textbox", "searchbox", "combobox", "checkbox", "radio", "switch"),
        "forms": [{
            "name": form.name, "submits": list(form.submits),
            "fields": [{"label": f.label, "type": f.type, "target": f.target, "required": f.required,
                        "placeholder": f.placeholder} for f in form.fields[:max_names]],
        } for form in ob.forms],
        "tables": ob.tables, "dialogs": ob.dialogs, "truncated": ob.truncated,
    }


@skill(ActionType.INSPECT_PAGE)
def inspect_page(sc: SkillContext) -> list[Check]:
    ob = sc.observe()
    sc.ctx.store("page_type", ob.page_type)
    sc.ctx.store("observation", ob.to_prompt())
    sc.agent["observation"] = structured(ob)

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
    if ob.truncated:
        checks.append(info("observation truncated", "the accessibility tree was cut for size"))
    return checks
