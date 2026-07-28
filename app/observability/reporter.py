"""HTML report writer — Astra-style modular report under reports/<environment>/.

Output layout (report.html is the entry point; everything is relative, so
the whole environment folder is portable):

    reports/<env>/
    ├── report.html         static shell
    ├── report.json         this run's payload as plain JSON
    ├── assets/report.css   static styles
    ├── assets/report.js    static rendering code
    ├── assets/data.js      this run's payload (window.__WEBAGENT_DATA__)
    └── images/             screenshots per run

The shell, CSS, and JS are copied from the packaged ``observability/assets/``
files and overwritten on every run so the report always matches the installed
framework version; only ``assets/data.js`` (and report.json) change between
runs. The payload ships as a script file rather than inline JSON or fetch()
because browsers load <script src> over file:// but block local fetch.

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
import time
from pathlib import Path
from typing import Any

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
    if rec["status"] == "failed" and s.get("msg"):
        rec["error"] = s["msg"]
    if s.get("screenshot"):
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


def _build_steps(flow_steps: list[dict], started_at: str) -> list[dict]:
    """Serialized StepResults → flat depth-annotated step records (Astra tree)."""
    if not flow_steps:
        return []

    # Sub-flow steps inherit the current section — their own section comes
    # from the sub-flow's markdown and would cause false section breaks.
    sections: list[tuple[str, list[dict]]] = []
    current: str | None = None
    for s in flow_steps:
        sec = current if s.get("sub_flow") else (s.get("section") or "")
        if sec != current or not sections:
            sections.append((sec or "", []))
            current = sec or ""
        sections[-1][1].append(s)

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
            "screenshot": r.get("screenshot"),
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

    if status in ("failed", "error"):
        message = r.get("error") or (r.get("longrepr") or "").split("\n")[0] or "Flow failed"
        test["error"] = {
            "message": message,
            "kind": "FlowError",
            "traceback": r.get("longrepr") or None,
        }
    return test


# ── generate_report ──────────────────────────────────────────────────────────

def generate_report(
    results: list[dict],
    session_start: float,
    output_path: Path,   # e.g. reports/staging/report.html
    environment: str = "staging",
) -> None:
    """Write report.html, report.json, assets/{report.css,report.js,data.js}."""
    report_dir = output_path.parent
    report_dir.mkdir(parents=True, exist_ok=True)

    tests = []
    for r in results:
        r = dict(r)
        r["screenshot"] = _screenshot_rel_path(r.get("screenshot"), report_dir)
        for s in r.get("flow_steps") or []:
            s["screenshot"] = _screenshot_rel_path(s.get("screenshot"), report_dir) or ""
        tests.append(_build_test(r))

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
            "browser": os.getenv("BROWSER", "chromium"),
            "headless": os.getenv("HEADLESS", "true").lower() != "false",
            "env": environment,
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

    data = json.dumps(payload, ensure_ascii=False)
    # U+2028/U+2029 are valid in JSON but not in JS source — escape them.
    data = data.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    (report_dir / "assets" / "data.js").write_text(
        f"window.__WEBAGENT_DATA__ = {data};\n", encoding="utf-8"
    )
    (report_dir / "report.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
