"""explore_page — bounded, safe exploration that builds a page/action graph.

    - explore_page
    - explore_page: "depth=2" | "max_actions=20" | "max_pages=8" | "max_ai_calls=3"
    - explore_page: "destructive=true"        (only with a flow/env override that allows it)

From the current page, every safe control the observer reports (links on the
same site, buttons, tabs, menu items) is pressed once through the engine —
a ``click`` probe step — and the outcome recorded: navigates to a page (queued
for the next depth), opens a dialog (closed with Escape), changes the page in
place, or nothing observable. A press with no visible change is looked at
before it is reported: a new tab, a ``tel:``/``mailto:`` hand-off, a link to
the page already open, or a state change the page fingerprint misses (an
input's type, ``aria-expanded``/``pressed``/``checked``) is an outcome, not a
problem. Only what remains unexplained is reported — as *inconclusive*: the
agent cannot tell a broken control from one that needs data or a signed-in
user. A control the agent could not press is inconclusive too, with the cause
(covered by another element, not visible, timed out). Controls the safety policy blocks are listed,
never pressed; so are buttons that submit or confirm a form (``Save``,
``Submit``, ``Apply``… — form testing is ``test_form``'s job, and pressing
them here could change data). When an LLM provider is configured and
``max_ai_calls`` > 0, the planner only *orders* the observed controls
(primary features first); it cannot add targets the observer did not see.

Limits: ``depth`` (link hops from the start page, default 2), ``max_actions``
(presses, default 20, shared with the caller's budget), ``max_pages``
(distinct pages, default 8), ``max_ai_calls`` (default 3), ``timeout``.
Returning to a page (``back``, ``goto``, Escape) is cleanup. The graph is
stored in the run context as ``explore_graph``.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from app.agent.observer import Node, Observation
from app.agent.safety import CONFIRM_WORDS
from app.execution import oracle
from app.flow.writer import graph_to_markdown
from app.schemas.actions import ActionType, Check, summarize
from app.skills.base import SkillContext, info, skill
from app.skills.base import skipped as skipped_check
from app.utils.urls import origin, strip_fragment

logger = logging.getLogger(__name__)

DEFAULTS = {"depth": 2, "max_pages": 8}
MAX_ACTIONS = 20          # presses, unless max_actions= (read by the runtime's budget) says otherwise
CLICKABLE_ROLES = ("link", "button", "tab", "menuitem")
GOAL = ("Explore this page's safe features one control at a time: primary navigation, "
        "search and filters, opening details or forms. Order the controls by how much "
        "of the application each one is likely to reveal.")


@dataclass
class Edge:
    action: str            # control name
    outcome: str           # navigates | external | opens dialog | opens new tab | changes page | hands off |
                           # links to this page | no observable result | failed
    to: str = ""           # URL or dialog name


@dataclass
class PageNode:
    url: str
    title: str
    page_type: str
    depth: int
    edges: list[Edge] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def _submits_form(n: Node) -> bool:
    """A button that submits or confirms a form — left to test_form."""
    if n.role != "button":
        return False
    in_form = n.container.startswith("form:") and "search" not in n.container.lower()
    name = n.name.lower().strip()
    return in_form or name in CONFIRM_WORDS or any(name.startswith(w + " ") for w in CONFIRM_WORDS)


def _candidates(ob: Observation, sc: SkillContext, node: PageNode, left: list[str]) -> list[Node]:
    """Safe, pressable, once-per-name controls — deterministic order: nav first."""
    seen: set[str] = set()
    out: list[Node] = []
    for n in ob.nodes:
        if n.role not in CLICKABLE_ROLES or not n.name or n.nth or "disabled" in n.attrs:
            continue
        if n.name in seen:
            continue
        seen.add(n.name)
        verdict = sc.policy.verdict(n.name, role=n.role, container=n.container, url=ob.url)
        if not verdict.allowed:
            node.skipped.append(f"{n.name} — {verdict.reason}")
            sc.block(n.name, verdict.reason)
            continue
        if _submits_form(n):
            left.append(f"{n.name}" + (f" ({n.container})" if n.container else ""))
            continue
        out.append(n)
    rank = {"tab": 1, "menuitem": 1, "button": 2, "link": 3}          # navigation landmarks first (0)
    out.sort(key=lambda n: (0 if n.container.startswith("navigation") else rank.get(n.role, 4)))
    return out


def _ai_order(sc: SkillContext, ob: Observation, candidates: list[Node], done: list[str]) -> list[Node]:
    """Let the planner put the most revealing controls first; never adds targets."""
    plan = sc.planner.plan(ob, GOAL, sc.policy, history=done, max_steps=len(candidates))
    if not plan:
        return candidates
    wanted = [s.target for s in plan.steps if s.action in ("click", "click_link_text")]
    by_name = {n.name: n for n in candidates}
    first = [by_name[t] for t in wanted if t in by_name]
    return first + [n for n in candidates if n not in first]


# What a press can change that the accessibility fingerprint does not see.
_STATE_JS = r"""
() => [location.href,
  [...document.querySelectorAll('input')].map(i => i.type).join(','),
  [...document.querySelectorAll('[aria-expanded], [aria-pressed], [aria-checked], [aria-selected]')]
    .map(e => ['aria-expanded', 'aria-pressed', 'aria-checked', 'aria-selected']
      .map(a => e.getAttribute(a) || '').join('')).join(''),
  document.querySelectorAll('*').length].join('|')
"""
_LINK_JS = r"""
el => { const a = el.closest('a[href]'); if (!a) return null;
  const here = new URL(location.href), to = new URL(a.href, location.href);
  return {href: a.getAttribute('href'), scheme: to.protocol, blank: a.target === '_blank',
          same: to.origin === here.origin && to.pathname === here.pathname}; }
"""
_HANDOFF = {"tel:": "phone", "mailto:": "email", "sms:": "messages"}


def _tabs(page) -> int:
    try:
        return len(page.context.pages)
    except Exception:
        return 0


def _new_tab(page) -> bool:
    """A ``target=_blank`` link's tab opens asynchronously: wait briefly for it."""
    try:
        page.context.wait_for_event("page", timeout=3000)
        return True
    except Exception:
        return False


def _explain(sc: SkillContext, cand: Node, state_before: str | None, tabs_before: int) -> tuple[str, str]:
    """Why a press changed nothing the observer sees: (outcome, detail)."""
    try:
        link = cand.locator(sc.page).evaluate(_LINK_JS, timeout=1000)
    except Exception:
        link = None
    if _tabs(sc.page) > tabs_before or (link and link["blank"] and _new_tab(sc.page)):
        popup = sc.page.context.pages[-1]
        url = popup.url
        try:
            popup.close()       # housekeeping of the agent's own probe, not an interaction with the app
        except Exception:
            pass
        return "opens new tab", url
    if link and link["scheme"] in _HANDOFF:
        return "hands off", f"{_HANDOFF[link['scheme']]} app ({link['href']})"
    reload = link and link["same"] and not link["href"].startswith("#")    # reloading resets the state
    if not reload and state_before is not None and sc.evaluate(_STATE_JS) not in (None, state_before):
        return "changes page", "state"
    if link and link["same"]:
        return "links to this page", link["href"]
    return "no observable result", ""


def _press_problem(message: str) -> str:
    """Why the agent could not press a control — the cause, not the call log."""
    m = message.lower()
    if "intercepts pointer events" in m:
        return "covered by another element"
    if "not visible" in m or "outside of the viewport" in m:
        return "not visible"
    if "timeout" in m:
        return "timed out"
    return (message.splitlines() or [""])[0][:80]


def _document_status(sc: SkillContext, url: str) -> int | None:
    if sc.recorder is None:
        return None
    for entry in reversed(sc.recorder.network):
        if entry.get("resource_type") == "document" and strip_fragment(entry.get("url", "")) == strip_fragment(url):
            return entry.get("status")
    return None


def _tree(pages: dict[str, PageNode], start: str) -> str:
    lines: list[str] = []

    def walk(url: str, prefix: str, seen: set[str]) -> None:
        node = pages.get(url)
        if node is None or url in seen:
            return
        seen.add(url)
        items = [(e, e.outcome == "navigates" and e.to in pages and e.to not in seen) for e in node.edges]
        for i, (e, descend) in enumerate(items):
            last = i == len(items) - 1 and not node.skipped
            branch = "└── " if last else "├── "
            target = f" → {e.to}" if e.to and e.outcome in ("navigates", "external") else (f' "{e.to}"' if e.to else "")
            lines.append(f"{prefix}{branch}{e.action} [{e.outcome}{target}]")
            if descend:
                walk(e.to, prefix + ("    " if last else "│   "), seen)
        if node.skipped:
            lines.append(f"{prefix}└── skipped by safety: " + ", ".join(s.split(' — ')[0] for s in node.skipped))

    root = pages[start]
    lines.append(f"{root.title or root.url} ({root.page_type}) {root.url}")
    walk(start, "", set())
    return "\n".join(lines)


@skill(ActionType.EXPLORE_PAGE)
def explore_page(sc: SkillContext) -> list[Check]:
    limits = {k: sc.count(k, v) for k, v in DEFAULTS.items()}
    if sc.budget.limit is None:
        sc.budget.limit = MAX_ACTIONS
    if sc.flag("destructive", False):
        sc.policy = sc.policy.with_destructive(True)

    start = strip_fragment(sc.page.url)
    site = origin(start)
    pages: dict[str, PageNode] = {}
    queue: list[tuple[str, int]] = [(start, 0)]
    actions = 0
    externals: list[str] = []
    broken: list[str] = []      # broken pages no step can be blamed for (the start page)
    judged: list[str] = []      # broken pages failed on the step that led to them
    no_effect: list[str] = []
    explained: list[str] = []   # presses whose outcome the fingerprint missed (new tab, tel:, same page, state)
    failed: list[str] = []
    unreachable: list[str] = []
    left: list[str] = []

    while queue and len(pages) < limits["max_pages"] and not sc.stopped:
        url, depth = queue.pop(0)
        if url in pages:
            continue
        opened, since = None, sc.mark()
        if strip_fragment(sc.page.url) != url:
            opened = sc.run(ActionType.GOTO, url, kind="probe")
            if not opened.success:
                if not opened.skipped:
                    unreachable.append(url)
                continue
        ob = sc.observe(fresh=True)
        node = PageNode(url=url, title=ob.title, page_type=ob.page_type, depth=depth)
        pages[url] = node
        status = _document_status(sc, url)
        if status and status >= 400:
            if opened is None:
                broken.append(f"{url} → HTTP {status}")
            else:
                judged.append(f"{url} → HTTP {status}")
                sc.fail_step(opened, f"broken page: {url} → HTTP {status}", since)
        before = ob.fingerprint()
        candidates = _candidates(ob, sc, node, left)
        if sc.planner.available:
            candidates = _ai_order(sc, ob, candidates, [e.action for e in node.edges])

        for cand in candidates:
            since, tabs, state = sc.mark(), _tabs(sc.page), sc.evaluate(_STATE_JS)
            sr = sc.run(ActionType.CLICK, cand.name, kind="probe")
            if sr.skipped:
                if sc.stopped:
                    break
                continue                                   # refused by the safety policy
            actions += 1
            # ORACLE=strict fails a click whose page broke: that is a broken page, not an unpressable control
            problems = [] if sr.success else [c.detail or f"expected {c.name}" for c in oracle.failed(sr.checks)]
            if not sr.success and not problems:
                failed.append(f"{cand.name} on {url} ({_press_problem(sr.message or sr.error or '')})")
                node.edges.append(Edge(cand.name, "failed"))
                continue
            after = sc.observe(fresh=True)
            now = strip_fragment(sc.page.url)
            # A broken page — whatever ORACLE says — is an error page, the new
            # page's own 4xx/5xx, or a page that did not render. It is judged on
            # the click that led to it: that step fails, with a screenshot taken
            # before going back. Other signals (a failed XHR) stay the oracle's.
            if now.startswith("chrome-error://"):
                problems.append("the browser showed an error page")
            elif now != url and origin(now) == site and (code := _document_status(sc, now)) and code >= 400:
                problems.append(f"{now} → HTTP {code}")
            if origin(now) == site:            # another site's page is not this site's defect
                problems += [c.detail or f"expected {c.name}" for c in sr.checks
                             if c.name == "page rendered" and not c.passed and sr.success]
            if problems:
                judged += [f"after '{cand.name}' on {url}: {p}" for p in problems]
                sc.fail_step(sr, "broken page: " + "; ".join(problems), since)
            if now != url:
                if now.startswith("chrome-error://"):          # navigation itself failed
                    node.edges.append(Edge(cand.name, "broken", now))
                elif origin(now) != site:
                    node.edges.append(Edge(cand.name, "external", now))
                    externals.append(now)
                else:
                    node.edges.append(Edge(cand.name, "navigates", now))
                    if depth + 1 <= limits["depth"] and now not in pages:
                        queue.append((now, depth + 1))
                sc.run(ActionType.BACK, kind="cleanup")
                if strip_fragment(sc.page.url) != url:
                    sc.run(ActionType.GOTO, url, kind="cleanup")
            elif after.dialogs > ob.dialogs:
                title = next((n.container.partition(":")[2] for n in after.nodes
                              if n.container.startswith(("dialog:", "alertdialog:"))), "")
                node.edges.append(Edge(cand.name, "opens dialog", title))
                sc.run(ActionType.PRESS, "Escape", kind="cleanup")
            elif after.fingerprint() != before:
                node.edges.append(Edge(cand.name, "changes page"))
                before = after.fingerprint()
            else:
                outcome, to = _explain(sc, cand, state, tabs)
                node.edges.append(Edge(cand.name, outcome, "" if to == "state" else to))
                if outcome == "no observable result":
                    no_effect.append(f"{cand.name} on {url}")
                else:
                    explained.append(f"{cand.name} → {outcome}" + (f" {to}" if to and to != "state" else ""))
                    if outcome == "changes page":
                        before = after.fingerprint()

    graph = {u: {"title": p.title, "type": p.page_type, "depth": p.depth,
                 "edges": [e.__dict__ for e in p.edges], "skipped": p.skipped} for u, p in pages.items()}
    sc.ctx.store("explore_graph", json.dumps(graph))
    skipped = list(dict.fromkeys(s for p in pages.values() for s in p.skipped))
    unexplored = len({u for u, _ in queue if u not in pages})
    sc.agent.update({
        "page_type": pages[start].page_type if start in pages else "UNKNOWN",
        "skipped": skipped, "graph": graph,
        "actions": [f"{e.action} → {e.outcome}" for p in pages.values() for e in p.edges],
    })
    if pages and sc.flag("generate", True):
        path = sc.engine.generated_path("explore")
        path.write_text(graph_to_markdown(f"Explore {pages[start].title or start}", graph, start), encoding="utf-8")
        sc.files["generated flow"] = str(path)
        sc.agent["generated"] = str(path)
    checks = [
        info("pages visited", f"{len(pages)} (depth ≤ {limits['depth']}, max {limits['max_pages']})"),
        info("controls pressed", f"{actions} (max_actions {sc.budget.limit})"),
        info("planning", f"AI ordered candidates ({sc.planner.calls} call(s))" if sc.planner.calls
             else "deterministic order (navigation, tabs, buttons, links)"),
        info("graph", _tree(pages, start) if pages else "nothing explored"),
        Check.listing("no broken pages", broken, "error"),      # the rest failed at their own step
        # Unexplained after checking tabs, links and state: the agent cannot tell
        # a broken control from one that needs data or a signed-in user.
        Check("controls respond", True, "inconclusive" if no_effect else "info",
              ("no observable result: " + summarize(no_effect, 5)) if no_effect else "", len(no_effect)),
        *([Check.listing("controls pressable", failed, "inconclusive")] if failed else []),
        Check.listing("linked pages open", unreachable, "warn"),
    ]
    if judged:
        checks.append(info("broken pages found", summarize(judged, 8)))
    if explained:
        checks.append(info("outcomes found on a closer look", summarize(list(dict.fromkeys(explained)), 8)))
    if left:
        checks.append(skipped_check("form buttons not pressed",
                                    "submitting or confirming a form is test_form's job: " + summarize(left, 8)))
    if externals:
        checks.append(info("external links", ", ".join(dict.fromkeys(externals))[:300]))
    if unexplored:
        checks.append(skipped_check("pages not explored", f"{unexplored} page(s) still queued when a limit was reached"))
    if "generated" in sc.agent:
        checks.append(info("generated flow", sc.agent["generated"]))
    return checks
