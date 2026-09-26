"""HTML report writer — Astra-style modular report under reports/<environment>/.

Output layout (report.html is the entry point; everything is relative, so
the whole environment folder is portable):

    reports/<env>/
    ├── report.html         static shell
    ├── report_<build>.json this run's full payload as plain JSON; <build> is the
    │                       BUILD_NAME slug — one JSON per folder, stale ones removed
    ├── assets/report.css   static styles
    ├── assets/report.js    static rendering code (summary, lists, timeline)
    ├── assets/report-detail.js  per-test drawer + console/network views
    ├── assets/nunito.woff2 the Dashboard's font, bundled for offline use
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

What goes into the tests (sections, nested groups, healings, routed
console/network) is built by ``report_model.build_tests``; this module
writes it: assets, per-test detail shards, the slim payload and the JSON.
"""

from __future__ import annotations

import datetime
import importlib.metadata
import json
import os
import platform
import shutil
import time
from pathlib import Path
from typing import Any

from app.config.settings import settings
from app.observability.report_model import build_tests
from app.utils.banner import APP_VERSION
from app.utils.build import build_slug, get_build_name

# packaged asset name → (folder under the report root, target name)
_ASSETS = {
    "report.html": ("", "report.html"),
    "report.css": ("assets", "report.css"),
    "report.js": ("assets", "report.js"),
    "report-detail.js": ("assets", "report-detail.js"),
    "nunito.woff2": ("assets", "nunito.woff2"),   # Dashboard font, shipped so the report works offline
}


# ── Paths and versions ──────────────────────────────────────────────────────

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

def _relative_evidence(ev: dict | None, report_dir: Path) -> dict | None:
    """Copy of an evidence dict with its file paths made report-relative."""
    if not ev:
        return ev
    out = dict(ev)
    out["screenshots"] = {k: rel for k, p in (ev.get("screenshots") or {}).items()
                          if (rel := _screenshot_rel_path(p, report_dir))}
    out["trace"] = _screenshot_rel_path(ev.get("trace"), report_dir)
    out["files"] = {k: rel for k, p in (ev.get("files") or {}).items()
                    if (rel := _screenshot_rel_path(p, report_dir))}
    return out

def _relative_agent(agent: dict | None, report_dir: Path) -> dict | None:
    if not agent:
        return agent
    out = dict(agent)
    if agent.get("generated"):
        out["generated"] = _screenshot_rel_path(agent["generated"], report_dir)
    return out


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
        # Copy the step dicts too: rewriting screenshot paths on the caller's
        # data would make a second generate_report() call lose every image.
        r = dict(r, flow_steps=[
            dict(s, screenshot=_screenshot_rel_path(s.get("screenshot"), report_dir) or "",
                 evidence=_relative_evidence(s.get("evidence"), report_dir),
                 agent=_relative_agent(s.get("agent"), report_dir))
            for s in r.get("flow_steps") or []
        ])
        tests.extend(build_tests(r))

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
            "framework": APP_VERSION,
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
        shutil.copyfile(packaged / source_name, target_dir / target_name)   # text and binary alike

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
        checks = [c for s in t.get("steps") or [] for c in s.get("checks") or []]
        slim["counts"] = {
            "console": len(console),
            "con_err": sum(1 for c in console
                           if c.get("level") in ("error", "pageerror")),
            "con_warn": sum(1 for c in console if c.get("level") == "warning"),
            "network": len(network),
            "net_bad": sum(1 for n in network if not n.get("ok")),
            "checks": len([c for c in checks if c.get("severity") != "info"]),
            "checks_flagged": sum(1 for c in checks if not c.get("passed")),
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
    for stale in [*report_dir.glob("report_*.json"), report_dir / "report.json"]:
        if stale != json_path and stale.exists():
            stale.unlink()
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return json_path
