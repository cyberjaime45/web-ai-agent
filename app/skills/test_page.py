"""test_page — give the agent a page and let it decide what to test.

    - test_page
    - test_page: "depth=1" | "max_actions=12" | "max_ai_calls=3" | "submit=false"

    OBSERVE → CLASSIFY → PLAN (by page type; the LLM only adds validated
    steps when a provider is configured) → EXECUTE through the other skills
    and the engine → judge with checks → GENERATE a deterministic Markdown
    flow from what ran.

Plan by type (deterministic, no provider needed):

    every page      check_console_network, test_responsive
    LOGIN           test_form (never submits), password field masked
    FORM / WIZARD   test_form (submit only with submit=true)
    TABLE / LIST /  search field exercised, pagination pressed once,
    SEARCH / …      then explore_page (depth, max_actions)
    SETTINGS        no toggles pressed (they change data); explore skipped

With a provider, ``max_ai_calls`` bounds two uses: a classification tie-break
when the deterministic type is CONTENT / UNKNOWN, and an adaptive plan of
extra steps — each validated against the observation and the safety policy
before it runs. Nested skills appear as groups under this step; the
generated flow is linked from it.
"""

from __future__ import annotations

import logging

from app.agent.observer import Observation
from app.flow.writer import steps_to_markdown
from app.planner_bridge import run_planned_steps
from app.schemas.actions import ActionType, Check
from app.skills.base import SkillContext, info, skill

logger = logging.getLogger(__name__)

DEFAULTS = {"depth": 1, "max_actions": 12, "max_ai_calls": 3}
LISTY = ("TABLE", "LIST", "SEARCH", "DASHBOARD", "DETAIL", "CONTENT", "UNKNOWN")
NEXT_NAMES = ("next", "next page", "›", "»", ">", "load more", "show more")
GOAL = ("Test this {kind} page beyond what was already done: exercise one or two more "
        "primary features (filters, sorting, opening details, tabs) and add assertions "
        "that prove the page works. Never change or delete data.")


def _components(ob: Observation) -> list[str]:
    out = []
    if ob.headings:
        out.append("headings: " + ", ".join(n.name for n in ob.headings[:5]))
    for role, label in (("button", "buttons"), ("link", "links"), ("textbox", "inputs"),
                        ("searchbox", "search"), ("combobox", "selects")):
        nodes = ob.by_role(role)
        if nodes:
            out.append(f"{label}: {len(nodes)}" + (" (" + ", ".join(n.name for n in nodes[:4] if n.name) + ")"
                                                   if role in ("button", "searchbox") else ""))
    for form in ob.forms:
        out.append(f"form '{form.name}': {len(form.fields)} fields")
    if ob.tables:
        out.append(f"tables: {ob.tables}")
    if ob.nav:
        out.append(f"navigation landmarks: {ob.nav}")
    if ob.dialogs:
        out.append(f"open dialogs: {ob.dialogs}")
    return out


def _search_box(ob: Observation):
    boxes = ob.by_role("searchbox") or [n for n in ob.by_role("textbox") if "search" in n.name.lower()]
    return boxes[0] if boxes else None


def _next_control(ob: Observation):
    for n in ob.by_role("button", "link"):
        if n.name.strip().lower() in NEXT_NAMES and "disabled" not in n.attrs:
            return n
    return None


def _listy_checks(sc: SkillContext, ob: Observation, start_url: str, plan: list[str]) -> list[Check]:
    checks: list[Check] = []
    box = _search_box(ob)
    if box is not None and box.name:
        plan.append(f"search for 'test' in '{box.name}'")
        before = ob.fingerprint()
        sc.run(ActionType.FILL, box.name, "test")
        sc.run(ActionType.PRESS, "Enter")
        after = sc.observe(fresh=True)
        checks.append(Check("search responds", after.fingerprint() != before, "warn",
                            "" if after.fingerprint() != before else "nothing changed after searching"))
        if after.url.split("#", 1)[0] != start_url.split("#", 1)[0]:
            sc.run(ActionType.GOTO, start_url)
    nxt = _next_control(sc.observe())
    if nxt is not None:
        plan.append(f"press '{nxt.name}' (pagination)")
        before = sc.observe().fingerprint()
        sc.run(ActionType.CLICK, nxt.name)
        after = sc.observe(fresh=True)
        checks.append(Check("pagination works", after.fingerprint() != before, "warn",
                            "" if after.fingerprint() != before else f"'{nxt.name}' changed nothing"))
        if after.url.split("#", 1)[0] != start_url.split("#", 1)[0]:
            sc.run(ActionType.GOTO, start_url)
    return checks


@skill(ActionType.TEST_PAGE)
def test_page(sc: SkillContext) -> list[Check]:
    limits = {k: int(sc.option(k, str(v)) or v) for k, v in DEFAULTS.items()}
    if sc.flag("destructive", False):
        sc.policy = sc.policy.with_destructive(True)
    sc.planner.max_calls = limits["max_ai_calls"]
    submit = "submit=true" if sc.flag("submit", False) else "submit=false"

    start_url = sc.page.url
    ob = sc.observe()
    kind, source = ob.page_type, "deterministic"
    if kind in ("CONTENT", "UNKNOWN") and sc.planner.available:
        if ai_kind := sc.planner.classify(ob):
            kind, source = ai_kind, "ai tie-break"
    components = _components(ob)
    plan: list[str] = ["check console and network"]
    checks: list[Check] = [
        info("page type", f"{kind} ({source})"),
        info("components", "; ".join(components) or "nothing interactive found"),
        Check("page has a heading", bool(ob.headings), "warn",
              "" if ob.headings else "no heading role in the accessibility tree"),
    ]
    if sc.option("profiles"):
        checks.append(info("profiles", "this step ran under the current profile; "
                                       "list profiles under `## Config` to run the flow on each"))

    sc.run_skill(ActionType.CHECK_CONSOLE_NETWORK)

    if kind == "LOGIN":
        plan += ["validate the login form without submitting", "check the password field is masked"]
        sc.run_skill(ActionType.TEST_FORM, "submit=false")
        pw = [f for form in ob.forms for f in form.fields if f.type == "password"]
        checks.append(Check("password field masked", bool(pw), "error",
                            "" if pw else "a field looks like a password but is not type=password"))
        checks.append(info("credentials", "sign-in not attempted (no account configured for test_page)"))
    elif kind in ("FORM", "WIZARD"):
        plan.append(f"validate the form ({submit})")
        sc.run_skill(ActionType.TEST_FORM, submit)
    elif kind == "SETTINGS":
        plan.append("leave toggles untouched (they change data)")
        checks.append(info("settings", "toggles and save buttons not pressed; explore skipped"))
    elif kind in LISTY:
        checks += _listy_checks(sc, ob, start_url, plan)
        if not sc.child_failed:
            remaining = max(sc.planner.max_calls - sc.planner.calls, 0)
            plan.append(f"explore safe controls (depth {limits['depth']}, max {limits['max_actions']} clicks)")
            sc.run_skill(ActionType.EXPLORE_PAGE, f"depth={limits['depth']}",
                         f"max_actions={limits['max_actions']}", f"max_ai_calls={remaining}", "generate=false")
            if sc.page.url.split("#", 1)[0] != start_url.split("#", 1)[0]:
                sc.run(ActionType.GOTO, start_url)

    plan.append("check the layout at narrow widths")
    sc.run_skill(ActionType.TEST_RESPONSIVE)

    rejected: list[str] = []
    if sc.planner.available and not sc.child_failed:
        current = sc.observe(fresh=True)
        done = [s.action.raw for s in sc.leaf_steps][-12:]
        ai_plan = sc.planner.plan(current, GOAL.format(kind=kind), sc.policy, history=done, max_steps=6)
        if ai_plan is not None:
            rejected = ai_plan.rejected
            executed = run_planned_steps(sc, ai_plan.steps, limits["max_actions"])
            plan += [f"[ai] {s.action} {s.target or s.value}".strip() for s in executed]
            checks.append(info("adaptive plan", f"{len(executed)} AI-planned step(s) executed, "
                                                f"{len(rejected)} rejected"))

    skipped = [s for st in sc.steps if st.agent for s in st.agent.get("skipped", [])]
    sc.agent.update({
        "page_type": kind, "classification": source, "components": components,
        "plan": plan, "plan_rejected": rejected, "skipped": skipped,
        "actions": [s.action.raw for s in sc.leaf_steps],
    })
    if sc.flag("generate", True):
        # test_responsive's clicks (menu toggle…) only make sense at the viewport
        # it set, so they stay out of the replayable flow.
        replayable = [s for s in sc.leaf_steps if "test_responsive" not in s.sub_flow]
        path = sc.engine.generated_path("test_page")
        path.write_text(steps_to_markdown(f"{ob.title or kind} — agent test", replayable, start_url),
                        encoding="utf-8")
        sc.files["generated flow"] = str(path)
        sc.agent["generated"] = str(path)
        checks.append(info("generated flow", str(path)))
    return checks
