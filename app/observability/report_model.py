"""Report model — collected results → the report's test and step records.

Pure data, no files: the report plugin's result dicts (one per pytest test,
with serialized flow steps and console / network captures) become the test
records the HTML report and JSON carry:

  sections            → one test per ``## section`` when steps have clocks
  run_flow / skills   → nested step groups (the engine's marker steps), each
                        step with a stable ``id`` ("2.1.3") and its ``parent``
  L2/L3 layer usage   → "healed locators" entries
  console / network   → routed to the section and step active when they started
  flagged checks      → the test's ``warnings`` (findings that did not fail it)

Step status: ``failed`` (fails the test), ``skipped``, ``passed``. A soft
skill step that failed is ``passed`` with its ``error`` kept: the skill turned
it into a check, which the test's ``warnings`` list. A group is failed when
it or a child failed.

``reporter.generate_report`` calls ``build_tests`` and writes the files.
"""

from __future__ import annotations

import bisect
import datetime
import re
from typing import Any

from app.schemas.actions import SKILL_ACTIONS, Check, section_runs

_RUN_FLOW_RE = re.compile(r"^\s*run_flow\b", re.IGNORECASE)
_SKILL_NAMES = {t.value for t in SKILL_ACTIONS}


# ── Helpers ──────────────────────────────────────────────────────────────────


def _outcome(c: dict) -> str:
    """A serialized check's outcome — ``Check.outcome``, the one rule."""
    return c.get("outcome") or Check(c.get("name", ""), c.get("passed", True), c.get("severity", "error")).outcome


def _fails(s: dict) -> bool:
    """``StepResult.fails_flow`` for a serialized step."""
    return not s.get("passed") and not s.get("skipped") and not s.get("soft")


def _step_status(s: dict) -> str:
    if s.get("skipped"):
        return "skipped"
    return "failed" if _fails(s) else "passed"


def _failure_screenshot(steps: list[dict]) -> str | None:
    """Screenshot of the last failed (non-skipped) step — the failure site.

    Skipped steps never carry screenshots; this is the single source for a
    test's failure screenshot in the payload.
    """
    return next((s["screenshot"] for s in reversed(steps) if _fails(s) and s.get("screenshot")), None)


def _failure_evidence(steps: list[dict]) -> dict | None:
    """Evidence bundle of the last failed (non-skipped) step, if any."""
    return next((s["evidence"] for s in reversed(steps) if _fails(s) and s.get("evidence")), None)


def _agent(steps: list[dict]) -> dict | None:
    """Facts of the outermost autonomous step (test_page / explore_page), if any."""
    return next((s["agent"] for s in steps if s.get("agent") and not s.get("sub_flow")), None) \
        or next((s["agent"] for s in steps if s.get("agent")), None)


def _artifacts(steps: list[dict]) -> dict:
    """``artifacts`` block: failure screenshot, every evidence shot, trace."""
    ev = _failure_evidence(steps) or {}
    shots = ev.get("screenshots") or {}
    return {
        "screenshot": _failure_screenshot(steps),
        "screenshots": [{"kind": k, "path": p} for k, p in shots.items() if p],
        "trace": ev.get("trace"),
    }


def _group_status(children: list[dict]) -> str:
    statuses = {c["status"] for c in children}
    if "failed" in statuses:
        return "failed"
    return "skipped" if statuses == {"skipped"} else "passed"


# ── Step tree ────────────────────────────────────────────────────────────────

def _leaf(s: dict, started_at: str, depth: int) -> dict:
    rec: dict[str, Any] = {
        "name": s.get("name") or "",
        "status": _step_status(s),
        "started_at": started_at,
        "duration_ms": round((s.get("duration") or 0.0) * 1000, 1),
        "depth": depth,
    }
    if s.get("ts_start"):
        rec["ts"] = round(s["ts_start"] * 1000)
        rec["started_at"] = datetime.datetime.fromtimestamp(
            s["ts_start"]).astimezone().isoformat(timespec="milliseconds")
    if rec["status"] != "skipped" and not s.get("passed") and s.get("msg"):
        rec["error"] = s["msg"]
    if s.get("screenshot") and rec["status"] != "skipped":
        rec["attachment"] = s["screenshot"]
    if s.get("evidence") and rec["status"] != "skipped":
        rec["evidence"] = s["evidence"]          # failure bundle, or a skill's screenshots
    if s.get("checks"):
        rec["checks"] = s["checks"]
    if s.get("agent"):
        rec["agent"] = s["agent"]
    # Verb + argument text for the drawer. The argument comes from the raw
    # step text (already secret-masked by the engine), never from the
    # resolved action args.
    if action := s.get("action"):
        rec["action"] = action
        raw = rec["name"]
        if raw.lower().startswith(action.lower()):
            rec["args"] = raw[len(action):].lstrip(" :").strip()
    if (layer := s.get("layer")) and rec["status"] != "skipped":
        rec["layer"] = int(layer)
    if s.get("resolved"):
        rec["resolved"] = s["resolved"]          # L2: the element actually acted on, and why
    return rec


def _group(name: str, children: list[dict], started_at: str, depth: int,
           marker: dict | None = None) -> dict:
    """A group node. A skill marker contributes its own checks, evidence and
    verdict: its status is failed when the skill judged so, even if every
    child step passed."""
    rec = {
        "name": name,
        "status": _group_status(children),
        "started_at": started_at,
        "duration_ms": round(sum(c["duration_ms"] for c in children if c["depth"] == depth + 1), 1),
        "depth": depth,
    }
    if marker:
        leaf = _leaf(marker, started_at, depth)
        for key in ("action", "args", "checks", "evidence", "agent", "error", "ts", "started_at"):
            if key in leaf:
                rec[key] = leaf[key]
        if marker.get("duration"):          # the skill's own clock covers its evaluation time too
            rec["duration_ms"] = leaf["duration_ms"]
        rec["status"] = _group_status([leaf, *[c for c in children if c["depth"] == depth + 1]])
    return rec


def _nest_sub_flows(steps: list[dict], started_at: str, depth: int, prefix: str = "") -> list[dict]:
    """Turn markers + sub_flow-tagged steps into nested groups, any depth.

    A step *belongs to this level* when its ``sub_flow`` equals *prefix* (""
    at the top). A marker (``group``, or a legacy ``run_flow`` name) followed
    by steps of another level owns them until this level resumes; deeper
    steps without a marker get a synthesized group.
    """
    out: list[dict] = []
    i = 0

    def level(s: dict) -> str:
        return s.get("sub_flow") or ""

    while i < len(steps):
        s = steps[i]
        if level(s) == prefix:
            name = s.get("name") or ""
            is_marker = s.get("group") or _RUN_FLOW_RE.match(name)
            j = i + 1
            if is_marker:
                while j < len(steps) and level(steps[j]) != prefix:
                    j += 1
            if is_marker and j > i + 1:
                children = _nest_sub_flows(steps[i + 1:j], started_at, depth + 1, level(steps[i + 1]))
                out.append(_group(name, children, started_at, depth, marker=s))
                out.extend(children)
                i = j
                continue
            out.append(_leaf(s, started_at, depth))
            i += 1
            continue
        # Deeper steps with no marker at this level: synthesize the group.
        child = level(s)
        j = i
        while j < len(steps) and level(steps[j]) != prefix:
            j += 1
        children = _nest_sub_flows(steps[i:j], started_at, depth + 1, child)
        leaf_name = child.rsplit("/", 1)[-1]
        label = leaf_name if leaf_name in _SKILL_NAMES else f"run_flow: {leaf_name}"
        out.append(_group(label, children, started_at, depth))
        out.extend(children)
        i = j
    return out


def _section_runs(flow_steps: list[dict]) -> list[tuple[str, list[dict]]]:
    """``schemas.section_runs`` over serialized steps (the same rule RERUN_FAILED uses)."""
    return section_runs(flow_steps, section=lambda s: s.get("section") or "", sub_flow=lambda s: s.get("sub_flow"))


def _healings(steps: list[dict]) -> list[dict]:
    """Steps that L1 could not resolve and L2/L3 recovered."""
    return [
        {
            "description": s.get("name") or "",
            "original": None,
            "healed_by": "L3 (AI)" if s.get("layer") == 3 else "L2 (fallback locator)",
            "resolved": s.get("resolved") or s.get("msg") or "resolved at runtime",
            "layer": s.get("layer"),
        }
        for s in steps if (s.get("layer") or 1) > 1 and s.get("passed")
    ]


def _build_steps(flow_steps: list[dict], started_at: str,
                 sections: list[tuple[str, list[dict]]] | None = None) -> list[dict]:
    """Serialized StepResults → flat depth-annotated step records (Astra tree)."""
    if not flow_steps:
        return []

    if sections is None:
        sections = _section_runs(flow_steps)
    # Group by section only when the test holds several; a test that *is* one
    # section is already named after it — a wrapper would repeat it as step 1.
    show_sections = len({name for name, _ in sections if name}) > 1

    out: list[dict] = []
    for name, group_steps in sections:
        if show_sections and name:
            children = _nest_sub_flows(group_steps, started_at, 1)
            out.append(_group(name, children, started_at, 0))
            out.extend(children)
        else:
            out.extend(_nest_sub_flows(group_steps, started_at, 0))
    _number(out)
    return out


def _number(steps: list[dict]) -> None:
    """``id`` = the step's position path ("2", "2.1", "2.1.3"), ``parent`` = the
    enclosing group's id — stable while the flow's structure is unchanged."""
    path: list[int] = []
    for s in steps:
        depth = s["depth"]
        del path[depth + 1:]
        if len(path) <= depth:
            path.extend([0] * (depth + 1 - len(path)))
        path[depth] += 1
        s["id"] = ".".join(map(str, path[:depth + 1]))
        s["parent"] = ".".join(map(str, path[:depth])) or None


def _findings(steps: list[dict]) -> tuple[list[dict], list[dict]]:
    """``(warnings, unverified)`` in one pass. Warnings: findings that did not
    fail the test (warn checks; error checks on a passed step, ORACLE=warn).
    Unverified: inconclusive checks — coverage, not application findings.
    The same check and detail on several steps is one entry: ``step`` plus
    the others in ``also``."""
    warnings: list[dict] = []
    unverified: list[dict] = []
    seen: dict[tuple, dict] = {}
    for s in steps:
        for c in s.get("checks") or []:
            kind = _outcome(c)
            if kind == "warning" or (kind == "failed" and s["status"] != "failed"):
                into = warnings
            elif kind == "inconclusive":
                into = unverified
            else:
                continue
            key = (id(into), c.get("name", ""), c.get("detail", ""), c.get("severity", "warn"))
            if (entry := seen.get(key)) is not None:
                if s["id"] != entry["step"] and s["id"] not in entry.setdefault("also", []):
                    entry["also"].append(s["id"])
                continue
            seen[key] = entry = {"step": s["id"], "step_name": s["name"], "check": c.get("name", ""),
                                 "detail": c.get("detail", ""), "severity": c.get("severity", "warn")}
            into.append(entry)
    return warnings, unverified


# ── Section splitting & event routing ────────────────────────────────────────

def _splittable(runs: list[tuple[str, list[dict]]]) -> bool:
    """Split when ≥2 distinct named sections and executed steps have clocks."""
    distinct = {name for name, _ in runs if name}
    if len(distinct) < 2:
        return False
    return all(s.get("ts_start")
               for _, steps in runs for s in steps if not s.get("skipped"))


def _attribute_steps(entries: list[dict], steps: list[dict]) -> None:
    """Best-effort: label each entry with the step active at its start.

    Steps run sequentially, so their windows are ordered and disjoint: one
    bisect per entry instead of a scan over every step (entries × steps).
    """
    windows = sorted((round(s["ts_start"] * 1000), round(s["ts_end"] * 1000),
                      s.get("name") or "")
                     for s in steps if s.get("ts_start"))
    if not windows:
        return
    starts = [lo for lo, _, _ in windows]
    for e in entries:
        ts = e.get("ts")
        if ts is None:
            continue
        i = bisect.bisect_right(starts, ts) - 1
        if i >= 0 and ts <= windows[i][1]:
            e["step"] = windows[i][2]


def _route_events(entries: list[dict], starts: list[tuple[int, int]],
                  n: int) -> list[list[dict]]:
    """Route entries to section index by start time.

    ``starts`` is [(window_start_ms, section_index)] sorted ascending —
    skipped sections have no window and receive nothing. An entry belongs to
    the last section that started before it; earlier events go to the first
    windowed section (spec: activity stays with the test where it started).
    """
    buckets: list[list[dict]] = [[] for _ in range(n)]
    if not starts:
        return buckets
    for e in entries:
        ts = e.get("ts")
        idx = starts[0][1]
        if ts is not None:
            for ms, i in starts:
                if ts >= ms:
                    idx = i
                else:
                    break
        buckets[idx].append(e)
    return buckets


# ── Test records ─────────────────────────────────────────────────────────────

_STATUS_MAP = {"passed": "passed", "failed": "failed", "error": "error", "skipped": "skipped"}


def _markers(r: dict, section: str | None) -> list[str]:
    """File-wide markers plus the ones declared under *section*, de-duplicated."""
    names = list(r.get("flow_markers") or [])
    for name in (r.get("section_markers") or {}).get(section or "", []):
        if name not in names:
            names.append(name)
    return names


def _build_test(r: dict, runs: list[tuple[str, list[dict]]] | None = None) -> dict:
    nodeid = r.get("nodeid", "")
    file = nodeid.split("::")[0] if "::" in nodeid else nodeid
    name = r.get("name") or (nodeid.split("::")[-1] if nodeid else "")
    status = _STATUS_MAP.get(r.get("outcome", ""), "failed")
    started_at = r.get("started_at") or ""
    flow_steps = r.get("flow_steps") or []
    if runs is None:
        runs = _section_runs(flow_steps)
    # A file with a single named ## section is one test: the heading is the
    # test, the # title is the suite — so the two never repeat each other.
    # The generic "Steps" heading carries no meaning; keep the flow name.
    sections = {sec for sec, _ in runs if sec}
    section = next(iter(sections)) if len(sections) == 1 else None
    if section and section.lower() != "steps":
        name = section

    test: dict[str, Any] = {
        "id": nodeid,
        "name": name,
        "title": name,
        "file": file,
        "file_title": r.get("flow_title") or None,
        "markers": _markers(r, section), "expected": list(r.get("flow_expected") or []),
        "profile": r.get("profile") or None,
        "status": status,
        "started_at": started_at,
        "duration_ms": round((r.get("duration") or 0.0) * 1000, 1),
        "retries": 1 if r.get("retried") else 0,
        "steps": (steps := _build_steps(flow_steps, started_at, runs)),
        **dict(zip(("warnings", "unverified"), _findings(steps))),
        "console": r.get("console") or [],
        "network": r.get("network") or [],
        "artifacts": _artifacts(flow_steps),
        "healings": _healings(flow_steps),
        "agent": _agent(flow_steps),
    }

    stamped = [s for s in flow_steps if s.get("ts_start")]
    test["t0"] = round(stamped[0]["ts_start"] * 1000) if stamped else None
    _attribute_steps(test["console"], flow_steps)
    _attribute_steps(test["network"], flow_steps)
    dropped = r.get("capture_dropped") or {}
    if dropped.get("console"):
        test["console_dropped"] = dropped["console"]
    if dropped.get("network"):
        test["network_dropped"] = dropped["network"]
    if any((dropped.get("untracked") or {}).values()):
        test["network_untracked"] = dropped["untracked"]   # prefetches, other sites: never recorded

    if r.get("retried"):
        test["retry_error"] = next(iter(r["retried"].values()))
        test["retry_verdict"] = next(iter((r.get("retried_verdicts") or {}).values()), "")
    if status in ("failed", "error"):
        message = r.get("error") or (r.get("longrepr") or "").split("\n")[0] or "Flow failed"
        test["error"] = {
            "message": message,
            "kind": "FlowError",
            "traceback": r.get("longrepr") or None,
        }
    return test


def _build_section_test(r: dict, idx: int, name: str, steps: list[dict]) -> dict:
    nodeid = r.get("nodeid", "")
    file = nodeid.split("::")[0] if "::" in nodeid else nodeid
    executed = [s for s in steps if not s.get("skipped")]
    failed = [s for s in steps if _fails(s)]
    if failed:
        status = "failed"
    elif not executed:
        status = "skipped"
    else:
        status = "passed"
    t0 = round(executed[0]["ts_start"] * 1000) if executed else None
    t_end = round(max(s["ts_end"] for s in executed) * 1000) if executed else None
    started_iso = (datetime.datetime.fromtimestamp(executed[0]["ts_start"])
                   .astimezone().isoformat(timespec="milliseconds")
                   if executed else r.get("started_at") or "")

    test: dict[str, Any] = {
        "id": f"{nodeid}::s{idx}",   # ordinal, per profile — stable even with duplicate names
        "name": name,
        "title": name,
        "file": file,
        "file_title": r.get("flow_title") or None,
        "markers": _markers(r, name), "expected": list(r.get("flow_expected") or []),
        "profile": r.get("profile") or None,
        "status": status,
        "started_at": started_iso,
        "t0": t0,
        "duration_ms": float(t_end - t0) if t0 is not None else 0.0,
        "retries": 1 if str(idx - 1) in (r.get("retried") or {}) else 0,
        "steps": (records := _nest_sub_flows(steps, started_iso, 0)),
        "warnings": [], "unverified": [], "console": [], "network": [],
        "artifacts": {"screenshot": None, "screenshots": [], "trace": None},
        "healings": _healings(steps),
        "agent": _agent(steps),
    }
    _number(records)
    test["warnings"], test["unverified"] = _findings(records)
    if test["retries"]:
        test["retry_error"] = r["retried"][str(idx - 1)]
        test["retry_verdict"] = (r.get("retried_verdicts") or {}).get(str(idx - 1), "")
    if failed:
        test["error"] = {
            "message": failed[-1].get("msg") or r.get("error") or "Section failed",
            "kind": "FlowError",
            "traceback": r.get("longrepr") or None,
        }
        test["artifacts"] = _artifacts(steps)
    return test


def build_tests(r: dict) -> list[dict]:
    """One test per section when splittable, else the single flow test."""
    flow_steps = r.get("flow_steps") or []
    runs = _section_runs(flow_steps)
    if not _splittable(runs):
        return [_build_test(r, runs)]

    tests = [_build_section_test(r, i + 1, name or "Steps", steps)
             for i, (name, steps) in enumerate(runs)]
    # pytest failed the item although no section did (teardown, trace or grid
    # status raised): the last section that ran carries it, so no report says passed
    if r.get("outcome") in ("failed", "error") and not any(t["status"] in ("failed", "error") for t in tests):
        last = next((t for t in reversed(tests) if t["status"] != "skipped"), tests[-1])
        last["status"] = "error" if r["outcome"] == "error" else "failed"
        last["error"] = {"message": r.get("error") or (r.get("longrepr") or "").split("\n")[0] or "Flow failed",
                         "kind": "FlowError", "traceback": r.get("longrepr") or None}

    starts = sorted((t["t0"], i) for i, t in enumerate(tests)
                    if t["t0"] is not None)
    for entries_key in ("console", "network"):
        buckets = _route_events(r.get(entries_key) or [], starts, len(tests))
        for i, t in enumerate(tests):
            t[entries_key] = buckets[i]
            _attribute_steps(t[entries_key], runs[i][1])

    dropped = r.get("capture_dropped") or {}
    if dropped.get("console"):
        tests[-1]["console_dropped"] = dropped["console"]
    if dropped.get("network"):
        tests[-1]["network_dropped"] = dropped["network"]
    if any((dropped.get("untracked") or {}).values()):
        for t in tests:                     # a flow-wide count: every section shows it
            t["network_untracked"] = dropped["untracked"]
    return tests
