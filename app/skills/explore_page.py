"""explore_page — bounded, safe exploration that builds a page/action graph.

    - explore_page
    - explore_page: "depth=2" | "max_actions=20" | "max_pages=8" | "max_ai_calls=3"
    - explore_page: "destructive=true"        (only with a flow/env override that allows it)

From the current page, every safe control the observer reports (links on the
same site, buttons, tabs, menu items) is pressed once through the engine —
a ``click`` child step — and the outcome recorded: navigates to a page (queued
for the next depth), opens a dialog (closed with Escape), changes the page in
place, or nothing observable. Controls the safety policy blocks are listed,
never pressed. When an LLM provider is configured and ``max_ai_calls`` > 0,
the planner only *orders* the observed controls (primary features first); it
cannot add targets the observer did not see.

Limits: ``depth`` (link hops from the start page, default 2), ``max_actions``
(clicks, default 20), ``max_pages`` (distinct pages, default 8),
``max_ai_calls`` (default 3). The graph is stored in the run context as
``explore_graph`` for the Markdown generator in Phase 4.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from urllib.parse import urlparse

from app.agent.observer import Node, Observation
from app.execution import oracle
from app.flow.writer import graph_to_markdown
from app.schemas.actions import ActionType, Check
from app.skills.base import SkillContext, info, skill

logger = logging.getLogger(__name__)

DEFAULTS = {"depth": 2, "max_actions": 20, "max_pages": 8, "max_ai_calls": 3}
CLICKABLE_ROLES = ("link", "button", "tab", "menuitem")
GOAL = ("Explore this page's safe features one control at a time: primary navigation, "
        "search and filters, opening details or forms. Order the controls by how much "
        "of the application each one is likely to reveal.")


@dataclass
class Edge:
    action: str            # control name
    outcome: str           # navigates | external | opens dialog | changes page | no observable result | failed
    to: str = ""           # URL or dialog name


@dataclass
class PageNode:
    url: str
    title: str
    page_type: str
    depth: int
    edges: list[Edge] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def _origin(url: str) -> str:
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}"


def _plain(url: str) -> str:
    return url.split("#", 1)[0]


def _candidates(ob: Observation, sc: SkillContext, node: PageNode, origin: str) -> list[Node]:
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
            continue
        out.append(n)
    rank = {"navigation": 0, "button": 2, "link": 3, "tab": 1, "menuitem": 1}
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


def _document_status(sc: SkillContext, url: str) -> int | None:
    if sc.recorder is None:
        return None
    for entry in reversed(sc.recorder.network):
        if entry.get("resource_type") == "document" and _plain(entry.get("url", "")) == _plain(url):
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
    limits = {k: int(sc.option(k, str(v)) or v) for k, v in DEFAULTS.items()}
    if sc.flag("destructive", False):
        sc.policy = sc.policy.with_destructive(True)
    sc.planner.max_calls = limits["max_ai_calls"]

    start = _plain(sc.page.url)
    origin = _origin(start)
    pages: dict[str, PageNode] = {}
    queue: list[tuple[str, int]] = [(start, 0)]
    actions = 0
    externals: list[str] = []
    broken: list[str] = []
    no_effect: list[str] = []
    failed: list[str] = []

    while queue and len(pages) < limits["max_pages"] and actions < limits["max_actions"]:
        url, depth = queue.pop(0)
        if url in pages:
            continue
        if _plain(sc.page.url) != url:
            if not sc.run(ActionType.GOTO, url).success:
                failed.append(f"open {url}")
                continue
        ob = sc.observe(fresh=True)
        node = PageNode(url=url, title=ob.title, page_type=ob.page_type, depth=depth)
        pages[url] = node
        status = _document_status(sc, url)
        if status and status >= 400:
            broken.append(f"{url} → HTTP {status}")
        before = ob.fingerprint()
        candidates = _candidates(ob, sc, node, origin)
        if sc.planner.available:
            candidates = _ai_order(sc, ob, candidates, [e.action for e in node.edges])

        for cand in candidates:
            if actions >= limits["max_actions"]:
                break
            actions += 1
            sr = sc.run(ActionType.CLICK, cand.name)
            if not sr.success:
                failed.append(f"{cand.name} on {url}")
                node.edges.append(Edge(cand.name, "failed"))
                continue
            after = sc.observe(fresh=True)
            now = _plain(sc.page.url)
            if now != url:
                if now.startswith("chrome-error://"):          # navigation itself failed
                    node.edges.append(Edge(cand.name, "broken", now))
                    broken.append(f"'{cand.name}' on {url} led to an error page")
                elif _origin(now) != origin:
                    node.edges.append(Edge(cand.name, "external", now))
                    externals.append(now)
                else:
                    node.edges.append(Edge(cand.name, "navigates", now))
                    if depth + 1 <= limits["depth"] and now not in pages:
                        queue.append((now, depth + 1))
                sc.run(ActionType.BACK)
                if _plain(sc.page.url) != url:
                    sc.run(ActionType.GOTO, url)
            elif after.dialogs > ob.dialogs:
                title = next((n.container.partition(":")[2] for n in after.nodes
                              if n.container.startswith(("dialog:", "alertdialog:"))), "")
                node.edges.append(Edge(cand.name, "opens dialog", title))
                sc.run(ActionType.PRESS, "Escape")
            elif after.fingerprint() != before:
                node.edges.append(Edge(cand.name, "changes page"))
                before = after.fingerprint()
            else:
                node.edges.append(Edge(cand.name, "no observable result"))
                no_effect.append(f"{cand.name} on {url}")
            for c in oracle.failed(sr.checks):
                broken.append(f"after '{cand.name}' on {url}: {c.name}" + (f" — {c.detail}" if c.detail else ""))

    graph = {u: {"title": p.title, "type": p.page_type, "depth": p.depth,
                 "edges": [e.__dict__ for e in p.edges], "skipped": p.skipped} for u, p in pages.items()}
    sc.ctx.store("explore_graph", json.dumps(graph))
    skipped = [s for p in pages.values() for s in p.skipped]
    unexplored = len(queue)
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
        info("controls pressed", f"{actions} of max {limits['max_actions']}"),
        info("planning", f"AI ordered candidates ({sc.planner.calls} call(s))" if sc.planner.calls
             else "deterministic order (navigation, tabs, buttons, links)"),
        info("graph", _tree(pages, start) if pages else "nothing explored"),
        Check("no broken pages", not broken, "error", "; ".join(broken[:5])),
        Check("controls respond", not no_effect, "warn",
              ("no observable result: " + ", ".join(no_effect[:5])) if no_effect else ""),
        Check("controls pressable", not failed, "error", "; ".join(failed[:5])),
    ]
    if skipped:
        checks.append(info("skipped by safety", "; ".join(skipped[:8])))
    if externals:
        checks.append(info("external links", ", ".join(dict.fromkeys(externals))[:300]))
    if unexplored:
        checks.append(info("not explored (limits)", f"{unexplored} page(s) still queued"))
    if "generated" in sc.agent:
        checks.append(info("generated flow", sc.agent["generated"]))
    return checks
