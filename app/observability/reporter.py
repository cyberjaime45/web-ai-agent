"""HTML report writer — Astra-style modular report under reports/<environment>/.

Output layout (report.html is the entry point; everything is relative, so
the whole environment folder is portable):

    reports/<env>/
    ├── report.html         static shell
    ├── report_<build>.json this run's full payload as plain JSON; <build> is the
    │                       BUILD_NAME slug — one JSON per folder, stale ones removed
    ├── assets/report.css   static styles
    ├── assets/report.js    static rendering code
    ├── assets/data.js      slim payload (window.__WEBAGENT_DATA__): run meta +
    │                       per-test steps/errors/artifacts + detail counts
    ├── assets/data/t-<i>.js   per-test console/network detail, loaded lazily
    │                       (window.__WEBAGENT_DETAIL__(i, {...}) callback)
    └── images/             screenshots per run

The shell, CSS, and JS are copied from the packaged ``observability/assets/``
files and overwritten on every run so the report always matches the installed
framework version; only the data files change between runs. Payloads ship as
script files rather than inline JSON or fetch() because browsers load
<script src> over file:// but block local fetch — the UI lazy-loads a test's
detail shard by injecting its <script> tag when the drawer or an
execution-level Console/Network tab first needs it.

WebAgent-specific data maps onto the shared report schema:
  sections            → collapsible step groups (depth tree)
  run_flow sub-flows  → nested step groups (the engine's marker step)
  L2/L3 layer usage   → "healed locators" events
"""

from __future__ import annotations

import datetime
import importlib.metadata
import json
import os
import platform
import re
import shutil
import time
from pathlib import Path
from typing import Any

from app.config.settings import settings
from app.utils.build import build_slug, get_build_name

# packaged asset name → (folder under the report root, target name)
_ASSETS = {
    "report.html": ("", "report.html"),
    "report.css": ("assets", "report.css"),
    "report.js": ("assets", "report.js"),
}

_RUN_FLOW_RE = re.compile(r"^\s*run_flow\b", re.IGNORECASE)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _screenshot_rel_path(path: str | None, report_dir: Path) -> str | None:
    """Return a report-relative URL for a screenshot (e.g. images/<uuid>.png)."""
    if not path:
        return None
    try:
        return str(Path(path).relative_to(report_dir)).replace("\\", "/")
    except ValueError:
        return None


def _pkg_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except Exception:
        return "unknown"


def _step_status(s: dict) -> str:
    if s.get("skipped"):
        return "skipped"
    return "passed" if s.get("passed") else "failed"


def _failure_screenshot(steps: list[dict]) -> str | None:
    """Screenshot of the last failed (non-skipped) step — the failure site.

    Skipped steps never carry screenshots; this is the single source for a
    test's failure screenshot in the payload.
    """
    return next((s["screenshot"] for s in reversed(steps)
                 if not s.get("passed") and not s.get("skipped")
                 and s.get("screenshot")), None)


def _group_status(children: list[dict]) -> str:
    statuses = {c["status"] for c in children}
    if "failed" in statuses:
        return "failed"
    if statuses == {"skipped"}:
        return "skipped"
    return "passed"


# ── Step tree ────────────────────────────────────────────────────────────────

def _leaf(s: dict, started_at: str, depth: int) -> dict:
    rec: dict[str, Any] = {
        "name": s.get("name") or s.get("label", ""),
        "status": _step_status(s),
        "started_at": started_at,
        "duration_ms": round((s.get("duration") or 0.0) * 1000, 1),
        "depth": depth,
    }
    if s.get("ts_start"):
        rec["ts"] = round(s["ts_start"] * 1000)
        rec["started_at"] = datetime.datetime.fromtimestamp(
            s["ts_start"]).astimezone().isoformat(timespec="milliseconds")
    if rec["status"] == "failed" and s.get("msg"):
        rec["error"] = s["msg"]
    if s.get("screenshot") and rec["status"] != "skipped":
        rec["attachment"] = s["screenshot"]
    return rec


def _group(name: str, children: list[dict], started_at: str, depth: int) -> dict:
    return {
        "name": name,
        "status": _group_status(children),
        "started_at": started_at,
        "duration_ms": round(sum(c["duration_ms"] for c in children if c["depth"] == depth + 1), 1),
        "depth": depth,
    }


def _nest_sub_flows(steps: list[dict], started_at: str, depth: int) -> list[dict]:
    """Turn run_flow markers + sub_flow-tagged steps into nested groups."""
    out: list[dict] = []
    i = 0
    while i < len(steps):
        s = steps[i]
        sub = s.get("sub_flow") or ""
        if not sub:
            is_marker = _RUN_FLOW_RE.match(s.get("name") or s.get("label", ""))
            next_sub = steps[i + 1].get("sub_flow") if i + 1 < len(steps) else ""
            if is_marker and next_sub:
                # The engine's marker step becomes the group node.
                children = []
                j = i + 1
                while j < len(steps) and steps[j].get("sub_flow") == next_sub:
                    children.append(_leaf(steps[j], started_at, depth + 1))
                    j += 1
                out.append(_group(s.get("name") or s.get("label", ""),
                                  children, started_at, depth))
                out.extend(children)
                i = j
                continue
            out.append(_leaf(s, started_at, depth))
            i += 1
            continue
        # Sub-flow steps without a preceding marker: synthesize the group.
        children = []
        j = i
        while j < len(steps) and steps[j].get("sub_flow") == sub:
            children.append(_leaf(steps[j], started_at, depth + 1))
            j += 1
        out.append(_group(f"run_flow: {sub}", children, started_at, depth))
        out.extend(children)
        i = j
    return out


def _section_runs(flow_steps: list[dict]) -> list[tuple[str, list[dict]]]:
    """Group steps into consecutive (section, steps) runs.

    Sub-flow steps inherit the current section — their own section comes
    from the sub-flow's markdown and would cause false section breaks.
    """
    runs: list[tuple[str, list[dict]]] = []
    current: str | None = None
    for s in flow_steps:
        sec = current if s.get("sub_flow") else (s.get("section") or "")
        if sec != current or not runs:
            runs.append((sec or "", []))
            current = sec or ""
        runs[-1][1].append(s)
    return runs


def _build_steps(flow_steps: list[dict], started_at: str) -> list[dict]:
    """Serialized StepResults → flat depth-annotated step records (Astra tree)."""
    if not flow_steps:
        return []

    sections = _section_runs(flow_steps)
    distinct = {name for name, _ in sections if name}
    show_sections = len(distinct) > 1 or (len(distinct) == 1 and "Steps" not in distinct)

    out: list[dict] = []
    for name, group_steps in sections:
        if show_sections and name:
            children = _nest_sub_flows(group_steps, started_at, 1)
            out.append(_group(name, children, started_at, 0))
            out.extend(children)
        else:
            out.extend(_nest_sub_flows(group_steps, started_at, 0))
    return out


# ── Section splitting & event routing ────────────────────────────────────────

def _splittable(runs: list[tuple[str, list[dict]]]) -> bool:
    """Split when ≥2 distinct named sections and executed steps have clocks."""
    distinct = {name for name, _ in runs if name}
    if len(distinct) < 2:
        return False
    return all(s.get("ts_start")
               for _, steps in runs for s in steps if not s.get("skipped"))


def _attribute_steps(entries: list[dict], steps: list[dict]) -> None:
    """Best-effort: label each entry with the step active at its start."""
    windows = [(round(s["ts_start"] * 1000), round(s["ts_end"] * 1000),
                s.get("name") or s.get("label", ""))
               for s in steps if s.get("ts_start")]
    for e in entries:
        ts = e.get("ts")
        if ts is None:
            continue
        for lo, hi, name in windows:
            if lo <= ts <= hi:
                e["step"] = name
                break


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


def _build_test(r: dict) -> dict:
    nodeid = r.get("nodeid", "")
    file = nodeid.split("::")[0] if "::" in nodeid else nodeid
    name = r.get("name") or (nodeid.split("::")[-1] if nodeid else "")
    status = _STATUS_MAP.get(r.get("outcome", ""), "failed")
    started_at = r.get("started_at") or ""
    flow_steps = r.get("flow_steps") or []

    test: dict[str, Any] = {
        "id": nodeid,
        "name": name,
        "title": name,
        "file": file,
        "markers": [],
        "status": status,
        "started_at": started_at,
        "duration_ms": round((r.get("duration") or 0.0) * 1000, 1),
        "retries": 0,
        "steps": _build_steps(flow_steps, started_at),
        "console": r.get("console") or [],
        "network": r.get("network") or [],
        "artifacts": {
            "screenshot": _failure_screenshot(flow_steps),
            "screenshots": [],
        },
        "healings": [
            {
                "description": s.get("name") or s.get("label", ""),
                "original": None,
                "healed_by": "L3 (AI)" if s.get("layer") == 3 else "L2 (fuzzy match)",
                "resolved": s.get("msg") or "resolved at runtime",
                "layer": s.get("layer"),
            }
            for s in flow_steps
            if (s.get("layer") or 1) > 1 and s.get("passed")
        ],
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
    failed = [s for s in steps if not s.get("passed") and not s.get("skipped")]
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
        "id": f"{file}::s{idx}",   # ordinal id — stable even with duplicate names
        "name": name,
        "title": name,
        "file": file,
        "flow": r.get("name") or "",
        "markers": [],
        "status": status,
        "started_at": started_iso,
        "t0": t0,
        "duration_ms": float(t_end - t0) if t0 is not None else 0.0,
        "retries": 0,
        "steps": _nest_sub_flows(steps, started_iso, 0),
        "console": [],
        "network": [],
        "artifacts": {"screenshot": None, "screenshots": []},
        "healings": [
            {
                "description": s.get("name") or s.get("label", ""),
                "original": None,
                "healed_by": "L3 (AI)" if s.get("layer") == 3 else "L2 (fuzzy match)",
                "resolved": s.get("msg") or "resolved at runtime",
                "layer": s.get("layer"),
            }
            for s in steps if (s.get("layer") or 1) > 1 and s.get("passed")
        ],
    }
    if failed:
        test["error"] = {
            "message": failed[-1].get("msg") or r.get("error") or "Section failed",
            "kind": "FlowError",
            "traceback": r.get("longrepr") or None,
        }
        test["artifacts"]["screenshot"] = _failure_screenshot(steps)
    return test


def _build_tests(r: dict) -> list[dict]:
    """One test per section when splittable, else the single flow test."""
    flow_steps = r.get("flow_steps") or []
    runs = _section_runs(flow_steps)
    if not _splittable(runs):
        return [_build_test(r)]

    tests = [_build_section_test(r, i + 1, name or "Steps", steps)
             for i, (name, steps) in enumerate(runs)]

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
    return tests


# ── generate_report ──────────────────────────────────────────────────────────

def _js_json(obj: Any) -> str:
    """JSON serialized for embedding in a JS source file.

    U+2028/U+2029 are valid in JSON but not in JS source — escape them.
    """
    data = json.dumps(obj, ensure_ascii=False)
    return data.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def json_report_name(build_name: str | None = None) -> str:
    """``report_<build slug>.json`` — e.g. ``report_web_test_report.json``."""
    return f"report_{build_slug(build_name)}.json"


def generate_report(
    results: list[dict],
    session_start: float,
    output_path: Path,   # e.g. reports/staging/report.html
    environment: str = "staging",
) -> Path:
    """Write report.html, report_<build>.json, assets/{report.css,report.js,data.js}.

    Returns the path of the JSON report.
    """
    report_dir = output_path.parent
    report_dir.mkdir(parents=True, exist_ok=True)

    tests = []
    for r in results:
        r = dict(r)
        for s in r.get("flow_steps") or []:
            s["screenshot"] = _screenshot_rel_path(s.get("screenshot"), report_dir) or ""
        tests.extend(_build_tests(r))

    total = len(tests)
    passed = sum(1 for t in tests if t["status"] == "passed")
    failed = sum(1 for t in tests if t["status"] == "failed")
    errors = sum(1 for t in tests if t["status"] == "error")
    skipped = sum(1 for t in tests if t["status"] == "skipped")
    executed = total - skipped
    now = datetime.datetime.now().astimezone()

    payload = {
        "tool": "web-agent",
        "run_id": now.strftime("%Y%m%d_%H%M%S"),
        "created_at": now.isoformat(timespec="milliseconds"),
        "environment": {
            "browser": settings.browser,
            "headless": settings.headless,
            "env": environment,
            "build_name": get_build_name(),
            "os": f"{platform.system()} {platform.release()}",
            "python": platform.python_version(),
            "playwright": _pkg_version("playwright"),
            "framework": "1.0.0",
            "ci": bool(os.getenv("CI")),
        },
        "totals": {
            "total": total,
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "errors": errors,
            "pass_rate": round(passed / executed * 100, 1) if executed else 0.0,
            "duration_ms": round((time.time() - session_start) * 1000, 1),
        },
        "tests": tests,
    }

    # Static shell + assets, overwritten every run.
    packaged = Path(__file__).parent / "assets"
    for source_name, (subdir, target_name) in _ASSETS.items():
        target_dir = report_dir / subdir if subdir else report_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / target_name).write_text(
            (packaged / source_name).read_text(encoding="utf-8"), encoding="utf-8"
        )

    # Per-test detail shards: console/network stay out of the upfront payload
    # and load lazily via <script> injection (fetch() is blocked on file://).
    detail_dir = report_dir / "assets" / "data"
    shutil.rmtree(detail_dir, ignore_errors=True)
    detail_dir.mkdir(parents=True)
    slim_tests = []
    for i, t in enumerate(tests):
        console = t.get("console") or []
        network = t.get("network") or []
        (detail_dir / f"t-{i}.js").write_text(
            f"window.__WEBAGENT_DETAIL__({i}, "
            f"{_js_json({'console': console, 'network': network})});\n",
            encoding="utf-8",
        )
        slim = {k: v for k, v in t.items() if k not in ("console", "network")}
        slim["counts"] = {
            "console": len(console),
            "con_err": sum(1 for c in console
                           if c.get("level") in ("error", "pageerror")),
            "con_warn": sum(1 for c in console if c.get("level") == "warning"),
            "network": len(network),
            "net_bad": sum(1 for n in network if not n.get("ok")),
        }
        slim_tests.append(slim)

    (report_dir / "assets" / "data.js").write_text(
        f"window.__WEBAGENT_DATA__ = {_js_json(dict(payload, tests=slim_tests))};\n",
        encoding="utf-8",
    )
    # One JSON per environment folder, named for the build. report.html is
    # overwritten every run, so a JSON from a previous build name would be
    # orphaned — remove it (and the legacy unsuffixed report.json).
    json_path = report_dir / json_report_name(payload["environment"]["build_name"])
    for stale in report_dir.glob("report*.json"):
        if stale != json_path:
            stale.unlink()
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return json_path
