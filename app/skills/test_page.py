"""test_page — give the agent a page and let it decide what to test.

    - test_page
    - test_page: "depth=1" | "max_actions=12" | "max_ai_calls=3" | "submit=false"

    OBSERVE → CLASSIFY → PLAN (by page type; the LLM only adds validated
    steps when a provider is configured) → EXECUTE through the other skills
    and the engine → judge with checks → GENERATE a deterministic Markdown
    flow from what ran.

Plan by type (deterministic, no provider needed):

    every page      check_console_network, check_accessibility, test_responsive
    LOGIN           test_form (never submits), password field masked
    FORM / WIZARD   test_form (submit only with submit=true)
    TABLE / LIST /  test_table when there is a table (else pagination pressed
    SEARCH / …      once), test_search when there is a search field, then
                    explore_page (depth, max_actions)
    SETTINGS        no toggles pressed (they change data); explore skipped

The generated flow asserts the headings, dialog titles and alerts the run
brought up (``writer.suggested_assertions``); the report's Agent panel lists
them.

With a provider, ``max_ai_calls`` bounds two uses: a classification tie-break
when the deterministic type is CONTENT / UNKNOWN, and an adaptive plan of
extra steps — each validated against the observation and the safety policy
before it runs. Nested skills appear as groups under this step; the
generated flow is linked from it.
"""

from __future__ import annotations

import logging

from app.agent.observer import Observation
from app.flow.writer import steps_to_markdown, suggested_assertions
from app.schemas.actions import ActionType, Check
from app.skills.base import SkillContext, info, skill
from app.utils.urls import same_page

logger = logging.getLogger(__name__)

DEFAULTS = {"depth": 1, "max_actions": 12, "max_ai_calls": 3}
LISTY = ("TABLE", "LIST", "SEARCH", "DASHBOARD", "DETAIL", "CONTENT", "UNKNOWN")
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


def _listy_checks(sc: SkillContext, ob: Observation, start_url: str, plan: list[str]) -> list[Check]:
    """test_table / test_search as nested skills; a bare pager when there is no table."""
    checks: list[Check] = []
    if ob.tables:
        plan.append("test the table: sorting, pagination, row details")
        sc.run_skill(ActionType.TEST_TABLE)
        if not same_page(sc.page.url, start_url):
            sc.run(ActionType.GOTO, start_url)
    box = ob.search_box()
    if box is not None and box.name:
        plan.append(f"search '{box.name}' for a value the page shows")
        sc.run_skill(ActionType.TEST_SEARCH)
    if ob.tables:
        return checks
    nxt = sc.observe(fresh=True).paging_control()
    if nxt is not None:
        plan.append(f"press '{nxt.name}' (pagination)")
        before = sc.observe().fingerprint()
        sc.run(ActionType.CLICK, nxt.name)
        after = sc.observe(fresh=True)
        checks.append(Check("pagination works", after.fingerprint() != before, "warn",
                            "" if after.fingerprint() != before else f"'{nxt.name}' changed nothing"))
        if not same_page(after.url, start_url):
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
    plan.append("check accessibility basics")
    sc.run_skill(ActionType.CHECK_ACCESSIBILITY)

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
            if not same_page(sc.page.url, start_url):
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
            executed = sc.run_planned(ai_plan.steps, limits["max_actions"])
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
        sc.agent["assertions"] = suggested_assertions(replayable)
        path = sc.engine.generated_path("test_page")
        path.write_text(steps_to_markdown(f"{ob.title or kind} — agent test", replayable, start_url),
                        encoding="utf-8")
        sc.files["generated flow"] = str(path)
        sc.agent["generated"] = str(path)
        checks.append(info("generated flow", str(path)))
    return checks
