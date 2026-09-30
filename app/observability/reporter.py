"""HTML report writer — Astra-style modular report under reports/<environment>/.

Output layout (report.html is the entry point; everything is relative, so
the whole environment folder is portable):

    reports/<env>/
    ├── report.html         static shell
    ├── summary.json        run metadata + totals as plain JSON (no tests)
    ├── test_cases.json     every test with full detail inline (steps, failures,
    │                       attachments, console, network); the totals in
    │                       summary.json are counted from this list
    ├── junit.xml           the same test cases as JUnit XML, for CI test tabs
    ├── assets/report.css   static styles
    ├── assets/report.js    static rendering code (summary, lists, timeline)
    ├── assets/report-logs.js    console / network views (drawer panes and execution tabs)
    ├── assets/report-detail.js  per-test drawer
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
writes it: assets, per-test detail shards, the slim payload and the JSON files.
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
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, NamedTuple

from app.config.settings import settings
from app.execution import oracle
from app.observability.report_model import build_tests
from app.schemas.actions import NOT_JUDGED
from app.utils.banner import APP_VERSION
from app.utils.build import get_build_name

# packaged asset name → (folder under the report root, target name)
_ASSETS = {
    "report.html": ("", "report.html"),
    "report.css": ("assets", "report.css"),
    "report.js": ("assets", "report.js"),
    "report-logs.js": ("assets", "report-logs.js"),
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


class ReportFiles(NamedTuple):
    """What generate_report wrote, plus the totals every other output repeats."""
    summary: Path
    test_cases: Path
    junit: Path
    totals: dict
    status: str          # passed | passed_with_warnings | failed | error | interrupted
    exit_code: int       # what the process should exit with (see run_status)


INTERRUPTED = 2          # pytest.ExitCode.INTERRUPTED


def run_status(totals: dict, exit_status: int | None) -> tuple[str, int]:
    """The run's verdict and exit code, from the test cases.

    Interrupted (pytest exit 2) wins: the totals cover only what finished.
    Any other code but 0 / 1 (usage or internal error) means the run itself
    broke: status ``error``, pytest's code kept. Otherwise a failed or errored
    test case means exit 1 — and so does a pytest failure the model did not
    see (status ``error``): the report never calls a failed run passed."""
    if exit_status == INTERRUPTED:
        return "interrupted", INTERRUPTED
    if exit_status not in (None, 0, 1):
        return "error", exit_status
    if totals["failed"] or totals["errors"]:
        return "failed", 1
    if exit_status == 1:
        return "error", 1
    return ("passed_with_warnings" if totals["warnings"] else "passed"), 0


# XML 1.0 forbids most control characters, and ANSI colour codes are noise:
# one in a message would make CI reject the whole junit.xml.
_XML_BAD = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _xml(text: str | None) -> str | None:
    return _XML_BAD.sub("", text) if text else text


def _write_junit(path: Path, tests: list[dict], created_at: str) -> None:
    """One <testcase> per report test (a flow section, or a Python test), one
    <testsuite> per file — so CI test tabs count what summary.json counts."""
    root = ET.Element("testsuites", name="web-agent")
    suites: dict[str, ET.Element] = {}
    for t in tests:
        suite = suites.get(t["file"])
        if suite is None:
            suite = suites[t["file"]] = ET.SubElement(
                root, "testsuite", name=_xml(t.get("file_title") or t["file"]), timestamp=created_at)
        profile = (t.get("profile") or {}).get("name", "")
        name = t["name"] + (f" [{profile}]" if profile and profile != "desktop" else "")   # unique per profile
        case = ET.SubElement(suite, "testcase", classname=_xml(t["file"]), name=_xml(name),
                             time=f"{t['duration_ms'] / 1000:.3f}")
        error = t.get("error") or {}
        if t["status"] in ("failed", "error"):
            tag = "failure" if t["status"] == "failed" else "error"
            ET.SubElement(case, tag, message=_xml(error.get("message")) or "",
                          type=error.get("kind") or "").text = _xml(error.get("traceback")) or None
        elif t["status"] == "skipped":
            ET.SubElement(case, "skipped")
    for element in (root, *suites.values()):   # iter() reaches every case below it
        cases = list(element.iter("testcase"))
        element.set("tests", str(len(cases)))
        for tag, attr in (("failure", "failures"), ("error", "errors"), ("skipped", "skipped")):
            element.set(attr, str(sum(c.find(tag) is not None for c in cases)))
        element.set("time", f"{sum(float(c.get('time')) for c in cases):.3f}")
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def generate_report(
    results: list[dict],
    session_start: float,
    output_path: Path,   # e.g. reports/staging/report.html
    environment: str = "staging",
    exit_status: int | None = None,   # pytest's, to tell an interrupted run
) -> ReportFiles:
    """Write report.html, summary.json, test_cases.json, junit.xml and
    assets/{report.css,report.js,data.js}. Every count comes from one list of
    tests (``report_model.build_tests``), so the outputs never disagree.
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
    # a test that passed on retry counts there, not here (the report shows it once)
    warnings = sum(1 for t in tests if t["status"] == "passed" and t.get("warnings") and not t.get("retries"))
    # coverage gaps: test cases with a check the agent could not judge — never a failure or warning
    unverified = sum(1 for t in tests if t["status"] != "skipped" and t.get("unverified"))
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
            "warnings": warnings,          # passed test cases with at least one warning
            "unverified": unverified,      # test cases with a check the agent could not judge
            "pass_rate": round(passed / executed * 100, 1) if executed else 0.0,
            "duration_ms": round((time.time() - session_start) * 1000, 1),
        },
        "tests": tests,
    }
    status, exit_code = run_status(payload["totals"], exit_status)
    payload["status"], payload["exit_code"] = status, exit_code

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
            # cancelled requests (beacons, cut off by leaving a page) are not failures
            "net_bad": sum(1 for n in network if not n.get("ok") and not oracle.cancelled(n)),
            "checks": len([c for c in checks if c.get("severity") not in NOT_JUDGED]),
            "warnings": len(t.get("warnings") or []),
        }
        slim_tests.append(slim)

    (report_dir / "assets" / "data.js").write_text(
        f"window.__WEBAGENT_DATA__ = {_js_json(dict(payload, tests=slim_tests))};\n",
        encoding="utf-8",
    )
    # Plain JSON for CI/tooling: run-level facts in summary.json, the tests the
    # totals were counted from in test_cases.json (run_id ties the two together).
    summary_path = report_dir / "summary.json"
    cases_path = report_dir / "test_cases.json"
    junit_path = report_dir / "junit.xml"
    summary = {k: v for k, v in payload.items() if k != "tests"}
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    cases_path.write_text(json.dumps({"run_id": payload["run_id"], "tests": tests},
                                     indent=2, ensure_ascii=False), encoding="utf-8")
    _write_junit(junit_path, tests, payload["created_at"])
    return ReportFiles(summary_path, cases_path, junit_path, payload["totals"], status, exit_code)
