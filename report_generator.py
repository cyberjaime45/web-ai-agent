"""
Professional HTML Report Generator — v4.

Design:
  ┌ Result Distribution ┐  ┌ Test Durations ┐  ┌ Pass Rate Trend (8 runs) ┐
  ├ By Category (1.5fr) ┤  ├ Failure Heatmap (2fr) ┤  ├ Code Coverage pie (1.1fr) ┤
  └ Test Results table (TEST | STATUS | ENV | DURATION | FLAKINESS | DETAILS)

Output files:
  reports/{env}/report.json       — pure data
  reports/{env}/assets/report.css — all CSS
  reports/{env}/assets/report.js  — all JavaScript
  reports/{env}/report.html       — minimal HTML shell
"""

from __future__ import annotations

import datetime
import html
import json
import re
import time
from pathlib import Path


# ── Category detection ────────────────────────────────────────────────────────

_CAT_PATTERNS: list[tuple[str, str]] = [
    (r"multipagenav|navigationagent",     "Navigation"),
    (r"loginagent|formvalid",             "Login / Auth"),
    (r"errorstate|autonomous",            "Error State"),
    (r"agentjourney|fullagent",           "Agent Flow"),
    (r"browsersmoke",                     "Smoke"),
    (r"flowparser",                       "Validation"),
]


def _get_category(class_str: str) -> str:
    key = class_str.lower().replace("::", "").replace("_", "")
    for pattern, name in _CAT_PATTERNS:
        if re.search(pattern, key):
            return name
    return "General"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _screenshot_rel_path(path: str | None, report_dir: Path) -> str:
    """Return a relative URL from report_dir to the screenshot file.

    E.g. /abs/reports/staging/images/FAIL_foo.png → images/FAIL_foo.png
    Returns '' when path is empty or outside report_dir.
    """
    if not path:
        return ""
    try:
        return str(Path(path).relative_to(report_dir)).replace("\\", "/")
    except ValueError:
        return ""


def _duration_str(seconds: float) -> str:
    if seconds < 1:
        return f"{seconds * 1000:.0f} ms"
    return f"{seconds:.2f} s"


_LOCATOR_RE = re.compile(
    r"(get_by_role|get_by_label|get_by_text|get_by_placeholder|"
    r"locator\(|click_button|fill_input|click_link|open_page|"
    r"fill\(|click\(|goto\()"
)


def _parse_failure_details(longrepr: str) -> dict:
    if not longrepr:
        return {"assert_msg": "", "locators": [], "short_trace": ""}
    lines = longrepr.splitlines()
    e_lines = [ln.lstrip("E").strip() for ln in lines if ln.lstrip().startswith("E ")]
    assert_msg = e_lines[-1] if e_lines else ""
    if not assert_msg:
        for ln in reversed(lines):
            s = ln.strip()
            if any(s.startswith(x) for x in ("AssertionError", "TimeoutError", "Error:", "assert ")):
                assert_msg = s
                break
    if len(assert_msg) > 260:
        assert_msg = assert_msg[:257] + "…"
    locators: list[str] = []
    for ln in lines:
        if _LOCATOR_RE.search(ln):
            c = ln.strip()
            if c and c not in locators:
                locators.append(c)
    locators = locators[:3]
    code_lines = [ln for ln in lines
                  if ln.strip() and not ln.lstrip().startswith("E ") and not ln.strip().startswith("_ ")]
    short_trace = "\n".join(code_lines[-5:])
    return {"assert_msg": assert_msg, "locators": locators, "short_trace": short_trace}


def _parse_nodeid(nodeid: str) -> tuple[str, str, str]:
    """Return (test_name, class_path, env)."""
    parts = nodeid.split("::")
    raw = parts[-1]
    m = re.search(r"\[([^\]]+)\]$", raw)
    env = m.group(1) if m else "default"
    name = raw[: m.start()] if m else raw
    cls = "::".join(parts[1:-1])
    return name, cls, env


def _flakiness_bars(outcome: str) -> list[list]:
    """Five [height_pct, color] bars representing stability."""
    if outcome == "passed":
        return [[45, "#4ade80"], [70, "#4ade80"], [90, "#4ade80"], [100, "#4ade80"], [75, "#4ade80"]]
    if outcome in ("failed", "error"):
        return [[100, "#f87171"], [55, "#4ade80"], [100, "#f87171"], [40, "#fb923c"], [100, "#f87171"]]
    return [[30, "#fb923c"]] * 5


def _compute_categories(results: list[dict]) -> list[dict]:
    cats: dict[str, dict] = {}
    for r in results:
        cat = _get_category(r.get("class", "") or r.get("cls", ""))
        if cat not in cats:
            cats[cat] = {"name": cat, "passed": 0, "failed": 0}
        if r.get("outcome") == "passed":
            cats[cat]["passed"] += 1
        elif r.get("outcome") in ("failed", "error"):
            cats[cat]["failed"] += 1
    return sorted(cats.values(), key=lambda x: -x["failed"])


def _load_and_update_history(history_path: Path, current: dict) -> list[dict]:
    history: list[dict] = []
    if history_path.exists():
        try:
            history = json.loads(history_path.read_text(encoding="utf-8"))
        except Exception:
            history = []
    history.append(current)
    history = history[-8:]
    try:
        history_path.parent.mkdir(parents=True, exist_ok=True)
        history_path.write_text(json.dumps(history, indent=2), encoding="utf-8")
    except Exception:
        pass
    return history


# Static placeholder heatmap (Mon–Sun × Wk1–Wk4).
# Replace with real per-day failure tracking if needed.
_DUMMY_HEATMAP = [
    [0, 0, 0, 2, 1, 0, 0],
    [1, 0, 3, 0, 4, 0, 0],
    [0, 2, 1, 0, 0, 2, 0],
    [4, 1, 0, 2, 4, 0, 0],
]


# ── CSS ───────────────────────────────────────────────────────────────────────

_CSS = """
/* ── LIGHT THEME (default) ── */
:root {
  --bg:          #f7f6f3;
  --surface:     #ffffff;
  --surface2:    #f1f0ed;
  --border:      #e5e3de;
  --text:        #1a1a2e;
  --text-2:      #4b5563;
  --label:       #9ca3af;
  --pass:        #15803d;
  --pass-bg:     #dcfce7;
  --pass-chart:  #4ade80;
  --fail:        #b91c1c;
  --fail-bg:     #fee2e2;
  --fail-chart:  #f87171;
  --skip:        #b45309;
  --skip-bg:     #fef3c7;
  --skip-chart:  #fb923c;
  --env-text:    #0e7490;
  --env-bg:      #e0f2fe;
  --cat-text:    #0e7490;
  --cat-bg:      #e0f2fe;
  --shadow:      0 1px 3px rgba(0,0,0,.08), 0 1px 2px rgba(0,0,0,.06);
  --radius:      8px;
  --chart-grid:  #e5e7eb;
  --chart-text:  #6b7280;
}

/* ── DARK THEME — system ── */
@media (prefers-color-scheme: dark) {
  :root:not([data-theme]) {
    --bg:          #0f172a;
    --surface:     #1e293b;
    --surface2:    #2d3f55;
    --border:      #334155;
    --text:        #f1f5f9;
    --text-2:      #94a3b8;
    --label:       #64748b;
    --pass:        #4ade80;
    --pass-bg:     rgba(74,222,128,.12);
    --fail:        #f87171;
    --fail-bg:     rgba(248,113,113,.12);
    --skip:        #fb923c;
    --skip-bg:     rgba(251,146,60,.12);
    --env-text:    #38bdf8;
    --env-bg:      rgba(56,189,248,.12);
    --cat-text:    #38bdf8;
    --cat-bg:      rgba(56,189,248,.12);
    --shadow:      0 2px 8px rgba(0,0,0,.4);
    --chart-grid:  #334155;
    --chart-text:  #94a3b8;
  }
}

/* ── DARK THEME — forced ── */
:root[data-theme="dark"] {
  --bg:          #0f172a;
  --surface:     #1e293b;
  --surface2:    #2d3f55;
  --border:      #334155;
  --text:        #f1f5f9;
  --text-2:      #94a3b8;
  --label:       #64748b;
  --pass:        #4ade80;
  --pass-bg:     rgba(74,222,128,.12);
  --fail:        #f87171;
  --fail-bg:     rgba(248,113,113,.12);
  --skip:        #fb923c;
  --skip-bg:     rgba(251,146,60,.12);
  --env-text:    #38bdf8;
  --env-bg:      rgba(56,189,248,.12);
  --cat-text:    #38bdf8;
  --cat-bg:      rgba(56,189,248,.12);
  --shadow:      0 2px 8px rgba(0,0,0,.4);
  --chart-grid:  #334155;
  --chart-text:  #94a3b8;
}

/* ── RESET & BASE ── */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
/* Ensure [hidden] always hides elements — prevents CSS display rules from overriding */
[hidden] { display: none !important; }
html { font-size: 14px; }
body {
  font-family: system-ui, -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif;
  background: var(--bg);
  color: var(--text);
  line-height: 1.55;
  min-height: 100vh;
  padding: 0;
}

/* ── APP CONTAINER — max-width 1280px centered ── */
#app { max-width: 1280px; margin: 0 auto; padding: 1.5rem 1.5rem 3rem; }

/* ── HEADER ── */
.rpt-header {
  display: flex; align-items: center; gap: 1rem; flex-wrap: wrap;
  padding: 1rem 0 1.25rem;
  border-bottom: 1px solid var(--border);
  margin-bottom: 1.5rem;
}
.rpt-logo {
  width: 38px; height: 38px; border-radius: 8px;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  display: flex; align-items: center; justify-content: center;
  color: #fff; font-weight: 800; font-size: 1rem; flex-shrink: 0;
}
.rpt-title { font-size: 1.15rem; font-weight: 700; color: var(--text); }
.rpt-sub {
  font-size: 0.76rem; color: var(--text-2); margin-top: 2px;
  display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap;
}
.env-tag {
  display: inline-block; padding: 1px 8px; border-radius: 999px;
  background: var(--env-bg); color: var(--env-text);
  font-size: 0.7rem; font-weight: 700; text-transform: uppercase; letter-spacing: .04em;
}
.rpt-spacer { flex: 1; }
.rpt-actions { display: flex; gap: .5rem; align-items: center; }

/* ── BUTTONS ── */
.btn {
  cursor: pointer; border: 1px solid var(--border);
  border-radius: 6px; padding: .35rem .75rem;
  font-size: 0.75rem; font-weight: 600; background: var(--surface);
  color: var(--text-2); transition: background .15s, color .15s;
}
.btn:hover { background: var(--surface2); color: var(--text); }
.btn-pdf {
  background: #6366f1; color: #fff; border-color: #6366f1;
}
.btn-pdf:hover { background: #4f46e5; border-color: #4f46e5; color: #fff; }
.btn-pdf.loading { opacity: .7; cursor: wait; }

/* ── SECTION LABEL ── */
.sec-label {
  font-size: 0.68rem; font-weight: 700; text-transform: uppercase;
  letter-spacing: .1em; color: var(--label); margin-bottom: .75rem;
}

/* ── CARDS ── */
.card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 1.1rem 1.25rem;
  box-shadow: var(--shadow);
}

/* ── STAT CARDS ── */
.stat-cards {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: .75rem;
  margin-bottom: 1rem;
}
.stat-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: .9rem 1rem;
  box-shadow: var(--shadow);
  display: flex; flex-direction: column; gap: .25rem;
}
.stat-label { font-size: 0.65rem; font-weight: 700; text-transform: uppercase; letter-spacing: .08em; color: var(--label); }
.stat-value { font-size: 1.6rem; font-weight: 800; line-height: 1; }
.stat-value.blue   { color: #6366f1; }
.stat-value.green  { color: var(--pass); }
.stat-value.red    { color: var(--fail); }
.stat-value.orange { color: var(--skip); }
.stat-value.purple { color: #8b5cf6; }

/* ── TOP ROW — 3 col grid ── */
.top-row {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 1rem;
  margin-bottom: 1rem;
}

/* ── RESULT DISTRIBUTION CARD ── */
.dist-donut-wrap { position: relative; height: 160px; }
.dist-legend { margin-top: .75rem; }
.dist-legend-row {
  display: flex; align-items: center; gap: .5rem;
  padding: .25rem 0;
  font-size: 0.8rem;
}
.dist-legend-row + .dist-legend-row { border-top: 1px solid var(--border); }
.leg-dot { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }
.leg-name { flex: 1; color: var(--text-2); }
.leg-val { font-weight: 700; font-variant-numeric: tabular-nums; }
.leg-val.pass { color: var(--pass); }
.leg-val.fail { color: var(--fail); }
.leg-val.skip { color: var(--skip); }

/* ── DURATION LIST ── */
.dur-list { display: flex; flex-direction: column; gap: .45rem; }
.dur-row {
  display: grid; grid-template-columns: 1fr auto auto;
  align-items: center; gap: .5rem; font-size: 0.78rem;
}
.dur-name { color: var(--text-2); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.dur-bar-wrap { width: 80px; height: 4px; background: var(--border); border-radius: 2px; }
.dur-bar { height: 100%; border-radius: 2px; background: #4ade80; min-width: 2px; }
.dur-bar.fail { background: #f87171; }
.dur-val { font-variant-numeric: tabular-nums; color: var(--text); font-weight: 600; white-space: nowrap; }

/* ── TREND CARD ── */
.trend-wrap { position: relative; height: 160px; }

/* ── MID ROW — 3 col: 1.5fr 2fr 1.1fr ── */
.mid-row {
  display: grid;
  grid-template-columns: 1.5fr 2fr 1.1fr;
  gap: 1rem;
  margin-bottom: 1rem;
}

/* ── BY CATEGORY CARD ── */
.cat-list { display: flex; flex-direction: column; gap: .6rem; }
.cat-row { display: flex; align-items: center; gap: .6rem; font-size: 0.78rem; }
.cat-badge {
  display: inline-block; min-width: 78px;
  padding: .2rem .55rem; border-radius: 4px;
  background: var(--cat-bg); color: var(--cat-text);
  font-size: 0.7rem; font-weight: 600; text-align: center; flex-shrink: 0;
}
.cat-bar-wrap { flex: 1; height: 8px; background: var(--border); border-radius: 4px; overflow: hidden; }
.cat-bar-inner { display: flex; height: 100%; }
.cat-seg-fail { background: #f87171; }
.cat-seg-pass { background: #4ade80; }
.cat-count { font-size: 0.72rem; color: var(--text-2); white-space: nowrap; text-align: right; min-width: 52px; }
.cat-count span { color: var(--label); }

/* ── HEATMAP CARD ── */
.heat-grid-wrap { overflow-x: auto; }
.heat-grid {
  display: grid;
  grid-template-columns: 36px repeat(7, 28px);
  gap: 3px;
  font-size: 0.68rem;
  min-width: 240px;
}
.heat-corner { color: var(--label); }
.heat-day-hdr { text-align: center; color: var(--label); font-weight: 600; }
.heat-wk-label { color: var(--label); font-size: 0.66rem; display: flex; align-items: center; }
.heat-cell {
  width: 28px; height: 22px; border-radius: 3px;
  display: flex; align-items: center; justify-content: center;
  font-size: 0.65rem; font-weight: 600; color: rgba(0,0,0,.5);
}
.heat-legend {
  margin-top: .6rem; display: flex; align-items: center;
  gap: .3rem; font-size: 0.68rem; color: var(--label);
}
.heat-legend-grad { display: flex; gap: 2px; }
.heat-legend-grad span {
  width: 14px; height: 10px; border-radius: 2px; display: inline-block;
}

/* ── COVERAGE PIE CARD ── */
.cov-pie-wrap { position: relative; height: 130px; }
.cov-info {
  margin-top: .6rem; font-size: 0.76rem; color: var(--text-2);
  display: flex; flex-direction: column; gap: .3rem;
}
.cov-info-row { display: flex; justify-content: space-between; align-items: center; }
.cov-status { display: inline-block; padding: .1rem .5rem; border-radius: 999px; font-size: 0.7rem; font-weight: 700; }
.cov-status.met  { background: var(--pass-bg); color: var(--pass); }
.cov-status.miss { background: var(--fail-bg); color: var(--fail); }

/* ── RESULTS TABLE — font-size: 0.96rem for tbody ── */
.results-wrap { overflow-x: auto; }
.rtable {
  width: 100%; border-collapse: separate; border-spacing: 0 4px;
  font-size: 0.8rem;
}
.rtable thead th {
  text-align: left; padding: .4rem .8rem;
  font-size: 0.66rem; font-weight: 700; text-transform: uppercase;
  letter-spacing: .08em; color: var(--label);
  border-bottom: 1px solid var(--border);
}
.rtable tbody tr.rrow {
  background: var(--surface); cursor: pointer;
  transition: background .1s;
}
.rtable tbody tr.rrow:hover { background: var(--surface2); }
.rtable tbody tr.rrow td {
  padding: .6rem .8rem; vertical-align: middle;
  border-top: 1px solid var(--border);
  border-bottom: 1px solid var(--border);
  font-size: 0.96rem;
}
.rtable tbody tr.rrow td:first-child {
  border-left: 1px solid var(--border);
  border-radius: var(--radius) 0 0 var(--radius);
}
.rtable tbody tr.rrow td:last-child {
  border-right: 1px solid var(--border);
  border-radius: 0 var(--radius) var(--radius) 0;
}
.rtable tbody tr.rdetail td {
  padding: 0;
  border-left: 1px solid var(--border);
  border-right: 1px solid var(--border);
  border-bottom: 1px solid var(--border);
  border-radius: 0 0 var(--radius) var(--radius);
  overflow: hidden;
}

/* ── TEST NAME/CLASS CELLS ── */
.t-name { font-weight: 600; color: var(--text); }
.t-cls { font-size: 0.68rem; color: var(--text-2); margin-top: 2px; }
.t-expand { font-size: 0.65rem; color: var(--label); margin-top: 3px; }

/* ── BADGE (passed/failed/skipped) ── */
.badge {
  display: inline-flex; align-items: center; gap: 4px;
  padding: .18rem .55rem; border-radius: 999px;
  font-size: 0.7rem; font-weight: 700;
}
.badge.passed  { background: var(--pass-bg); color: var(--pass); }
.badge.failed  { background: var(--fail-bg); color: var(--fail); }
.badge.skipped { background: var(--skip-bg); color: var(--skip); }
.badge.error   { background: var(--fail-bg); color: var(--fail); }
.badge .dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }

/* ── ENV CHIP ── */
.env-chip {
  display: inline-block; padding: .15rem .5rem; border-radius: 4px;
  background: var(--env-bg); color: var(--env-text);
  font-size: 0.68rem; font-weight: 600;
}
.dur-cell { font-variant-numeric: tabular-nums; color: var(--text-2); }
.det-snippet { font-size: 0.75rem; color: var(--text-2); max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* ── SCREENSHOT THUMBNAIL IN TABLE ROW ── */
.row-thumb {
  height: 75px; width: auto; border-radius: 4px;
  border: none; cursor: zoom-in;
  display: block; margin-left: auto;        /* right-align within the cell */
  transition: opacity .15s, transform .15s; object-fit: contain;
}
.row-thumb:hover { opacity: .85; transform: scale(1.04); }
.no-shot-placeholder {
  display: inline-flex; align-items: center; justify-content: center;
  width: 60px; height: 36px; border-radius: 4px;
  background: var(--surface2); border: 1px dashed var(--border);
  font-size: 0.65rem; color: var(--label); text-align: center; line-height: 1.2;
}

/* ── FLAKINESS BAR (SVG container) ── */
.flik-wrap { display: inline-block; vertical-align: middle; }

/* ── EXPANDABLE DETAIL ROW ── */
.rdetail-inner {
  display: none;
  padding: .9rem 1rem;
  background: var(--surface2);
  border-top: 1px dashed var(--border);
  gap: 1rem;
  grid-template-columns: 1fr auto;
}
.rdetail-inner.open { display: grid; }
.rdetail-left { display: flex; flex-direction: column; gap: .5rem; }

/* ── DETAIL SUB-SECTIONS ── */
.det-label {
  font-size: 0.65rem; font-weight: 700; text-transform: uppercase;
  letter-spacing: .08em; color: var(--label); margin-bottom: .15rem;
}
.det-msg { font-size: 0.78rem; color: var(--fail); font-weight: 500; word-break: break-word; }
.det-loc {
  font-family: 'Cascadia Code','Fira Code','Courier New',monospace;
  font-size: 0.72rem; color: #60a5fa;
  background: rgba(96,165,250,.07); border-left: 2px solid #60a5fa;
  padding: 2px 6px; border-radius: 0 3px 3px 0; margin: 1px 0;
  word-break: break-all;
}
.det-trace {
  font-family: 'Cascadia Code','Fira Code','Courier New',monospace;
  font-size: 0.7rem; color: var(--text-2); background: var(--surface);
  border: 1px solid var(--border); border-radius: 4px;
  padding: .5rem .7rem; white-space: pre-wrap; word-break: break-word;
  max-height: 160px; overflow-y: auto;
}
/* Let highlight.js provide its own colours inside our layout shell */
.det-trace code.hljs { background: transparent; padding: 0; font-size: inherit; }
.rdetail-shot img {
  max-width: 220px; max-height: 140px; border-radius: 5px;
  border: 1px solid var(--border); cursor: zoom-in;
  transition: transform .15s;
}
.rdetail-shot img:hover { transform: scale(1.03); }
.rdetail-shot .no-shot { font-size: 0.72rem; color: var(--label); }

/* ── LIGHTBOX ── */
#lightbox {
  display: none; position: fixed; inset: 0;
  background: rgba(0,0,0,.88); z-index: 9999;
  align-items: center; justify-content: center; cursor: zoom-out;
}
#lightbox.open { display: flex; }
#lightbox img { max-width: 95vw; max-height: 95vh; border-radius: 8px; box-shadow: 0 8px 40px rgba(0,0,0,.8); }

/* ── LOADING STATE ── */
#loading-state {
  display: flex; flex-direction: column; align-items: center;
  justify-content: center; gap: 1rem; padding: 4rem 2rem;
  color: var(--text-2); font-size: 0.9rem;
}
.spinner {
  width: 36px; height: 36px; border-radius: 50%;
  border: 3px solid var(--border);
  border-top-color: #6366f1;
  animation: spin .7s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

/* ── ERROR STATE ── */
#error-state {
  display: flex; flex-direction: column; align-items: center;
  justify-content: center; gap: .75rem; padding: 4rem 2rem;
  text-align: center;
}
.error-icon { font-size: 2.5rem; }
#error-state h2 { font-size: 1.1rem; color: var(--fail); }
#error-state p { font-size: 0.85rem; color: var(--text-2); max-width: 480px; }
.error-hint { background: var(--surface2); border: 1px solid var(--border); border-radius: 6px; padding: .75rem 1rem; font-size: 0.82rem !important; }
.error-hint code { font-family: 'Cascadia Code','Fira Code','Courier New',monospace; color: #60a5fa; }

/* ── FOOTER ── */
.rpt-footer {
  margin-top: 2rem; padding-top: 1.25rem;
  border-top: 1px solid var(--border);
  display: flex; justify-content: space-between;
  font-size: 0.72rem; color: var(--label);
}

/* ── PRINT / PDF ── */
@media print {
  * { -webkit-print-color-adjust: exact !important; print-color-adjust: exact !important; }
  .rpt-actions, #lightbox { display: none !important; }
  body { background: var(--bg) !important; }
  .card { box-shadow: none !important; break-inside: avoid; }
  .top-row, .mid-row { page-break-inside: avoid; }
}

/* ── RESPONSIVE ── */
@media (max-width: 900px) {
  .top-row { grid-template-columns: 1fr; }
  .mid-row  { grid-template-columns: 1fr; }
  .stat-cards { grid-template-columns: repeat(2, 1fr); }
}
"""


# ── JS ────────────────────────────────────────────────────────────────────────
# NOTE: raw string — NOT an f-string — so {} are literal JavaScript.

_JS = r"""
'use strict';

// ── Module-level chart references (destroyed before recreation) ───────────────
let donutChart, trendChart, covChart;

// ── Theme ────────────────────────────────────────────────────────────────────
const THEMES = ['', 'light', 'dark'];
let themeIdx = 0;

(function initTheme() {
  try {
    // Priority: localStorage override → embedded default from .env → system
    const saved        = localStorage.getItem('qa_theme');
    const envDefault   = document.documentElement.getAttribute('data-default-theme') || '';
    const resolved     = (saved !== null) ? saved : envDefault;
    themeIdx = THEMES.indexOf(resolved);
    if (themeIdx < 0) themeIdx = 0;
    const t = THEMES[themeIdx];
    if (t) document.documentElement.setAttribute('data-theme', t);
    else   document.documentElement.removeAttribute('data-theme');
    updateThemeBtn();
    updateHljsTheme();
  } catch(e) { console.warn('Theme init failed:', e); }
})();

function cycleTheme() {
  try {
    themeIdx = (themeIdx + 1) % THEMES.length;
    const t = THEMES[themeIdx];
    if (t) document.documentElement.setAttribute('data-theme', t);
    else   document.documentElement.removeAttribute('data-theme');
    localStorage.setItem('qa_theme', t);
    updateThemeBtn();
    updateChartTheme();
    updateHljsTheme();
  } catch(e) { console.error('cycleTheme error:', e); }
}

function updateThemeBtn() {
  const labels = ['\u2299 System', '\u2600 Light', '\uD83C\uDF19 Dark'];
  const btn = document.getElementById('theme-btn');
  if (btn) btn.textContent = labels[themeIdx];
}

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

// ── highlight.js theme sync ───────────────────────────────────────────────────
function updateHljsTheme() {
  const link = document.getElementById('hljs-theme');
  if (!link) return;
  const forced = document.documentElement.getAttribute('data-theme');
  const isDark = forced === 'dark' ||
    (!forced && window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
  link.href = isDark
    ? 'https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github-dark.min.css'
    : 'https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github.min.css';
}

function hljsHighlight(code) {
  if (!window.hljs || !code) return escHtml(code || '');
  try {
    return hljs.highlight(code, { language: 'python', ignoreIllegals: true }).value;
  } catch(_) {
    try { return hljs.highlightAuto(code).value; } catch(__) { return escHtml(code); }
  }
}

// ── Loading / error state helpers ────────────────────────────────────────────
function showLoading() {
  const el = document.getElementById('loading-state');
  if (el) el.hidden = false;
}

function hideLoading() {
  const el = document.getElementById('loading-state');
  if (el) el.hidden = true;
}

function showError(msg) {
  hideLoading();
  const el = document.getElementById('error-state');
  const detail = document.getElementById('error-detail');
  if (detail) detail.textContent = msg;
  if (el) el.hidden = false;
}

function showBody() {
  hideLoading();
  const el = document.getElementById('pdf-body');
  if (el) el.hidden = false;
}

// ── Bootstrap — data is embedded inline, no HTTP fetch required ───────────────
document.addEventListener('DOMContentLoaded', function() {
  try {
    var D = window._QA_DATA;
    if (!D || typeof D !== 'object') {
      showError('Report data not found. Re-run the test suite to regenerate report.html.');
      return;
    }
    // Ensure required top-level keys have safe defaults
    D.meta        = D.meta        || {};
    D.summary     = D.summary     || { total: 0, passed: 0, failed: 0, skipped: 0, pass_rate: 0 };
    D.results     = D.results     || [];
    D.categories  = D.categories  || [];
    D.trend       = D.trend       || [];
    D.heatmap     = D.heatmap     || [];
    D.dur_list    = D.dur_list    || [];
    D.meta.project          = D.meta.project          || 'QA Web Agent';
    D.meta.environment      = D.meta.environment      || '';
    D.meta.base_url         = D.meta.base_url         || '';
    D.meta.log_level        = D.meta.log_level        || 'info';
    D.meta.coverage         = D.meta.coverage         != null ? D.meta.coverage         : 0;
    D.meta.coverage_target  = D.meta.coverage_target  != null ? D.meta.coverage_target  : 80;
    D.meta.generated_at     = D.meta.generated_at     || '';
    D.meta.duration         = D.meta.duration         || '0 ms';

    showBody();
    renderHeader(D);
    renderSummary(D);
    buildDonut(D);
    renderDurationList(D);
    buildTrend(D);
    renderCategories(D);
    renderHeatmap(D);
    buildCoveragePie(D);
    renderTable(D);
    renderFooter(D);
  } catch(e) {
    console.error('Render error:', e);
    showError('Render failed: ' + e.message);
  }
});

// ── Header ───────────────────────────────────────────────────────────────────
function renderHeader(D) {
  const el = document.getElementById('rpt-header');
  if (!el) return;
  const m = D.meta;
  const s = D.summary;
  const overall = s.failed === 0
    ? '<span style="color:var(--pass);font-weight:700">ALL PASSED</span>'
    : '<span style="color:var(--fail);font-weight:700">' + s.failed + ' TEST' + (s.failed > 1 ? 'S' : '') + ' FAILED</span>';
  el.innerHTML =
    '<div class="rpt-logo" aria-hidden="true">QA</div>' +
    '<div>' +
      '<div class="rpt-title">' + escHtml(m.project) + '</div>' +
      '<div class="rpt-sub">' +
        '<span class="env-tag">' + escHtml(m.environment) + '</span>' +
        (m.base_url ? '<span>BASE: ' + escHtml(m.base_url) + '</span>' : '') +
        '<span>LOG: ' + escHtml(m.log_level.toUpperCase()) + '</span>' +
        '<span>\u00b7</span>' +
        overall +
      '</div>' +
    '</div>' +
    '<div class="rpt-spacer"></div>' +
    '<div class="rpt-actions">' +
      '<span style="font-size:.72rem;color:var(--label)">' + escHtml(m.generated_at) + '</span>' +
      '<button class="btn" id="theme-btn" onclick="cycleTheme()" aria-label="Toggle color theme">\u2299 System</button>' +
      '<button class="btn btn-pdf" id="pdf-btn" onclick="exportPDF()" aria-label="Export report as PDF">\u2193 Export PDF</button>' +
    '</div>';
  updateThemeBtn();
}

// ── Summary stat cards ────────────────────────────────────────────────────────
function renderSummary(D) {
  const el = document.getElementById('stat-cards');
  if (!el) return;
  const s = D.summary;
  const m = D.meta;
  const cards = [
    { label: 'Total',    value: s.total,    color: 'blue'   },
    { label: 'Passed',   value: s.passed,   color: 'green'  },
    { label: 'Failed',   value: s.failed,   color: 'red'    },
    { label: 'Skipped',  value: s.skipped,  color: 'orange' },
    { label: 'Duration', value: m.duration, color: 'purple' },
  ];
  el.innerHTML = cards.map(function(c) {
    return '<div class="stat-card">' +
      '<div class="stat-label">' + escHtml(c.label) + '</div>' +
      '<div class="stat-value ' + c.color + '">' + escHtml(String(c.value)) + '</div>' +
    '</div>';
  }).join('');
}

// ── Result distribution doughnut ──────────────────────────────────────────────
function buildDonut(D) {
  const canvas = document.getElementById('donutChart');
  if (!canvas) return;
  try {
    if (donutChart) { donutChart.destroy(); donutChart = null; }
    const pr = D.summary.pass_rate;
    const centerPlugin = {
      id: 'centerText',
      afterDatasetsDraw: function(chart) {
        const ca = chart.chartArea;
        if (!ca) return;
        const cx = (ca.left + ca.right) / 2;
        const cy = (ca.top  + ca.bottom) / 2;
        chart.ctx.save();
        chart.ctx.textAlign = 'center';
        chart.ctx.textBaseline = 'middle';
        chart.ctx.font = 'bold 26px system-ui';
        chart.ctx.fillStyle = cssVar('--text');
        chart.ctx.fillText(pr + '%', cx, cy - 9);
        chart.ctx.font = '600 10px system-ui';
        chart.ctx.fillStyle = cssVar('--label');
        chart.ctx.fillText('PASS RATE', cx, cy + 11);
        chart.ctx.restore();
      }
    };
    donutChart = new Chart(canvas, {
      type: 'doughnut',
      plugins: [centerPlugin],
      data: {
        labels: ['Passed', 'Failed', 'Skipped'],
        datasets: [{
          data: [D.summary.passed, D.summary.failed, D.summary.skipped],
          backgroundColor: ['#4ade80', '#f87171', '#fb923c'],
          borderColor: cssVar('--surface'),
          borderWidth: 3,
          hoverOffset: 5,
        }]
      },
      options: {
        responsive: true, maintainAspectRatio: false, cutout: '68%',
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: {
            label: function(ctx) {
              return ' ' + ctx.label + ': ' + ctx.raw + ' (' + Math.round(ctx.raw / Math.max(D.summary.total, 1) * 100) + '%)';
            }
          }}
        }
      }
    });

    // Build legend
    const legEl = document.getElementById('dist-legend');
    if (legEl) {
      const items = [
        { color: '#4ade80', label: 'Passed',  val: D.summary.passed,  cls: 'pass' },
        { color: '#f87171', label: 'Failed',  val: D.summary.failed,  cls: 'fail' },
        { color: '#fb923c', label: 'Skipped', val: D.summary.skipped, cls: 'skip' },
      ];
      legEl.innerHTML = items.map(function(it) {
        return '<div class="dist-legend-row">' +
          '<div class="leg-dot" style="background:' + it.color + '"></div>' +
          '<div class="leg-name">' + it.label + '</div>' +
          '<div class="leg-val ' + it.cls + '">' + it.val + '</div>' +
        '</div>';
      }).join('');
    }
  } catch(e) { console.error('buildDonut error:', e); }
}

// ── Duration list ─────────────────────────────────────────────────────────────
function renderDurationList(D) {
  const el = document.getElementById('dur-list');
  if (!el) return;
  try {
    const list = D.dur_list || [];
    const maxDur = list.reduce(function(m, r) { return Math.max(m, r.duration); }, 0.001) || 0.001;
    el.innerHTML = list.map(function(r) {
      const pct = Math.round(r.duration / maxDur * 100);
      const failCls = r.outcome !== 'passed' ? ' fail' : '';
      const name = r.name.length > 30 ? r.name.substring(0, 30) + '\u2026' : r.name;
      return '<div class="dur-row">' +
        '<span class="dur-name" title="' + escHtml(r.name) + '">' + escHtml(name) + '</span>' +
        '<div class="dur-bar-wrap"><div class="dur-bar' + failCls + '" style="width:' + pct + '%"></div></div>' +
        '<span class="dur-val">' + formatDur(r.duration) + '</span>' +
      '</div>';
    }).join('');
  } catch(e) { console.error('renderDurationList error:', e); }
}

// ── Pass rate trend bar chart ─────────────────────────────────────────────────
function buildTrend(D) {
  const canvas = document.getElementById('trendChart');
  if (!canvas) return;
  try {
    if (trendChart) { trendChart.destroy(); trendChart = null; }
    trendChart = new Chart(canvas, {
      type: 'bar',
      data: {
        labels: D.trend.map(function(r) { return r.run_id; }),
        datasets: [
          { label: 'Passed',  data: D.trend.map(function(r) { return r.passed; }),  backgroundColor: '#4ade80', borderRadius: 3, stack: 's' },
          { label: 'Failed',  data: D.trend.map(function(r) { return r.failed; }),  backgroundColor: '#f87171', borderRadius: 3, stack: 's' },
          { label: 'Skipped', data: D.trend.map(function(r) { return r.skipped; }), backgroundColor: '#fb923c', borderRadius: 3, stack: 's' },
        ]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: {
          legend: { position: 'bottom', labels: { color: cssVar('--chart-text'), boxWidth: 12, font: { size: 10 } } }
        },
        scales: {
          x: { stacked: true, grid: { display: false }, ticks: { color: cssVar('--chart-text'), font: { size: 10 } } },
          y: { stacked: true, grid: { color: cssVar('--chart-grid') }, ticks: { color: cssVar('--chart-text'), font: { size: 10 } }, beginAtZero: true }
        }
      }
    });
  } catch(e) { console.error('buildTrend error:', e); }
}

// ── By Category horizontal bars ───────────────────────────────────────────────
function renderCategories(D) {
  const el = document.getElementById('cat-list');
  if (!el) return;
  try {
    el.innerHTML = '';
    D.categories.forEach(function(cat) {
      const total = cat.passed + cat.failed;
      const failPct = total ? Math.round(cat.failed / total * 100) : 0;
      const passPct = total ? Math.round(cat.passed / total * 100) : 0;
      const statusTxt = total === 0 ? '0 / 0' :
        cat.failed > 0
          ? cat.failed + ' / ' + total + '<br><span style="color:var(--fail)">fail</span>'
          : cat.passed + ' / ' + total + '<br><span style="color:var(--pass)">pass</span>';
      el.insertAdjacentHTML('beforeend',
        '<div class="cat-row">' +
          '<div class="cat-badge">' + escHtml(cat.name) + '</div>' +
          '<div class="cat-bar-wrap">' +
            '<div class="cat-bar-inner">' +
              '<div class="cat-seg-fail" style="width:' + failPct + '%"></div>' +
              '<div class="cat-seg-pass" style="width:' + passPct + '%"></div>' +
            '</div>' +
          '</div>' +
          '<div class="cat-count">' + statusTxt + '</div>' +
        '</div>');
    });
  } catch(e) { console.error('renderCategories error:', e); }
}

// ── Failure heatmap ───────────────────────────────────────────────────────────
function heatColor(v) {
  if (v === 0) return 'var(--border)';
  if (v === 1) return '#bbf7d0';
  if (v === 2) return '#fde68a';
  if (v === 3) return '#fb923c';
  return '#f87171';
}

function renderHeatmap(D) {
  const grid = document.getElementById('heat-grid');
  if (!grid) return;
  try {
    grid.innerHTML = '';
    const days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
    grid.insertAdjacentHTML('beforeend', '<div class="heat-corner"></div>');
    days.forEach(function(d) {
      grid.insertAdjacentHTML('beforeend', '<div class="heat-day-hdr">' + d + '</div>');
    });
    D.heatmap.forEach(function(wk, wi) {
      grid.insertAdjacentHTML('beforeend', '<div class="heat-wk-label">Wk ' + (wi + 1) + '</div>');
      wk.forEach(function(v) {
        grid.insertAdjacentHTML('beforeend',
          '<div class="heat-cell" style="background:' + heatColor(v) + '">' + (v || '') + '</div>');
      });
    });

    const legEl = document.getElementById('heat-legend');
    if (legEl) {
      const colors = ['var(--border)', '#bbf7d0', '#fde68a', '#fb923c', '#f87171'];
      legEl.innerHTML =
        '<span>fewer</span>' +
        '<div class="heat-legend-grad">' +
          colors.map(function(c) { return '<span style="background:' + c + '"></span>'; }).join('') +
        '</div>' +
        '<span>more failures</span>';
    }
  } catch(e) { console.error('renderHeatmap error:', e); }
}

// ── Coverage doughnut pie (mid-row col 3) ─────────────────────────────────────
function buildCoveragePie(D) {
  const canvas = document.getElementById('coverageChart');
  if (!canvas) return;
  try {
    if (covChart) { covChart.destroy(); covChart = null; }
    const cov = D.meta.coverage || 0;
    const tgt = D.meta.coverage_target || 80;
    const remaining = Math.max(0, 100 - cov);
    const met = cov >= tgt;
    const covColor = met ? '#4ade80' : (cov >= 50 ? '#fb923c' : '#f87171');

    const centerPlugin = {
      id: 'covCenter',
      afterDatasetsDraw: function(chart) {
        const ca = chart.chartArea;
        if (!ca) return;
        const cx = (ca.left + ca.right) / 2;
        const cy = (ca.top  + ca.bottom) / 2;
        chart.ctx.save();
        chart.ctx.textAlign = 'center';
        chart.ctx.textBaseline = 'middle';
        chart.ctx.font = 'bold 20px system-ui';
        chart.ctx.fillStyle = covColor;
        chart.ctx.fillText(cov + '%', cx, cy - 8);
        chart.ctx.font = '600 9px system-ui';
        chart.ctx.fillStyle = cssVar('--label');
        chart.ctx.fillText('COVERAGE', cx, cy + 9);
        chart.ctx.restore();
      }
    };

    covChart = new Chart(canvas, {
      type: 'doughnut',
      plugins: [centerPlugin],
      data: {
        labels: ['Covered', 'Uncovered'],
        datasets: [{
          data: [cov, remaining],
          backgroundColor: [covColor, cssVar('--border')],
          borderColor: cssVar('--surface'),
          borderWidth: 2,
          hoverOffset: 3,
        }]
      },
      options: {
        responsive: true, maintainAspectRatio: false, cutout: '70%',
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: {
            label: function(ctx) { return ' ' + ctx.label + ': ' + ctx.raw + '%'; }
          }}
        }
      }
    });

    const infoEl = document.getElementById('cov-info');
    if (infoEl) {
      const statusHtml = met
        ? '<span class="cov-status met">\u2713 Target met</span>'
        : '<span class="cov-status miss">\u2717 Below target</span>';
      infoEl.innerHTML =
        '<div class="cov-info-row">' +
          '<span>Target: <strong>' + tgt + '%</strong></span>' +
          statusHtml +
        '</div>';
    }
  } catch(e) { console.error('buildCoveragePie error:', e); }
}

// ── Test results table ────────────────────────────────────────────────────────
function renderTable(D) {
  const tbody = document.getElementById('results-tbody');
  if (!tbody) return;
  try {
    tbody.innerHTML = '';
    if (!D.results || !D.results.length) {
      const tr = document.createElement('tr');
      tr.innerHTML = '<td colspan="5" style="text-align:center;padding:2rem;color:var(--text2)">No test results found.</td>';
      tbody.appendChild(tr);
      return;
    }
    const frag = document.createDocumentFragment();
    D.results.forEach(function(r, i) {
      const oc = r.outcome;
      const badge = '<span class="badge ' + oc + '"><span class="dot"></span> ' + escHtml(oc) + '</span>';
      const flikSVG = buildFlakinessSVG(r.flakiness);
      // Details column: thumbnail for failed tests, text snippet otherwise
      let detailCell;
      if (oc !== 'passed' && r.screenshot_path) {
        detailCell =
          '<img class="row-thumb" ' +
          'src="' + escHtml(r.screenshot_path) + '" ' +
          'alt="Failure screenshot — click to expand" ' +
          'title="Click row to expand failure details" />';
      } else if (oc !== 'passed') {
        detailCell = '<span class="no-shot-placeholder">no<br>shot</span>';
      } else {
        detailCell = '<span class="det-snippet" style="color:var(--pass)">\u2713 All assertions passed</span>';
      }

      // Main row
      const tr = document.createElement('tr');
      tr.className = 'rrow';
      tr.setAttribute('aria-expanded', 'false');
      tr.setAttribute('tabindex', '0');
      tr.setAttribute('aria-label', 'Test: ' + r.name + ', status: ' + oc);
      tr.onclick = function() { toggleDetail(i, tr); };
      tr.onkeydown = function(e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggleDetail(i, tr); } };
      tr.innerHTML =
        '<td>' +
          '<div class="t-name">' + escHtml(r.name) + '</div>' +
          '<div class="t-cls">' + escHtml((r.cls || '').split('::').pop() || (r.cls || '')) + '</div>' +
          '<div class="t-expand" id="expand-hint-' + i + '">\u25b6 expand</div>' +
        '</td>' +
        '<td>' + badge + '</td>' +
        '<td class="dur-cell">' + formatDur(r.duration) + '</td>' +
        '<td><div class="flik-wrap">' + flikSVG + '</div></td>' +
        '<td>' + detailCell + '</td>';

      // Detail row
      const trDetail = document.createElement('tr');
      trDetail.className = 'rdetail';
      trDetail.id = 'rdetail-' + i;
      const td = document.createElement('td');
      td.setAttribute('colspan', '5');
      const inner = document.createElement('div');
      inner.className = 'rdetail-inner';
      inner.id = 'rdetail-inner-' + i;
      inner.innerHTML = buildDetailLeft(r) + buildDetailShot(r);
      td.appendChild(inner);
      trDetail.appendChild(td);

      frag.appendChild(tr);
      frag.appendChild(trDetail);
    });
    tbody.appendChild(frag);
  } catch(e) { console.error('renderTable error:', e); }
}

function buildFlakinessSVG(bars) {
  const w = 28, h = 16;
  if (!bars || !bars.length) return '';
  let rects = '';
  bars.forEach(function(bar, i) {
    const pct = bar[0]; const color = bar[1];
    const bh = Math.max(2, Math.round(pct / 100 * h));
    const y  = h - bh;
    rects += '<rect x="' + (i * 6) + '" y="' + y + '" width="4" height="' + bh + '" rx="1" fill="' + color + '"/>';
  });
  return '<svg width="' + w + '" height="' + h + '" viewBox="0 0 ' + w + ' ' + h + '" style="display:block" aria-hidden="true">' + rects + '</svg>';
}

function buildDetailLeft(r) {
  let out = '<div class="rdetail-left">';
  const d = r.details || {};
  if (d.assert_msg) {
    out += '<div><div class="det-label">What failed</div><div class="det-msg">' + escHtml(d.assert_msg) + '</div></div>';
  }
  if (d.locators && d.locators.length) {
    out += '<div><div class="det-label">Locator / action tried</div>';
    d.locators.forEach(function(l) { out += '<div class="det-loc">' + escHtml(l) + '</div>'; });
    out += '</div>';
  }
  if (d.short_trace) {
    out += '<div><div class="det-label">Stacktrace</div>' +
      '<pre class="det-trace"><code class="hljs">' + hljsHighlight(d.short_trace) + '</code></pre></div>';
  }
  if (!d.assert_msg && !d.short_trace) {
    out += '<div style="color:var(--pass);font-size:.8rem">\u2713 Test passed with no errors.</div>';
  }
  out += '</div>';
  return out;
}

function buildDetailShot(r) {
  if (!r.screenshot_path) return '<div class="rdetail-shot"><span class="no-shot">No screenshot</span></div>';
  return '<div class="rdetail-shot">' +
    '<img src="' + escHtml(r.screenshot_path) + '" alt="Failure screenshot" onclick="openLightbox(this.src)" style="cursor:zoom-in"/>' +
  '</div>';
}

function toggleDetail(i, trEl) {
  const inner = document.getElementById('rdetail-inner-' + i);
  const hint  = document.getElementById('expand-hint-' + i);
  if (!inner) return;
  const isOpen = inner.classList.toggle('open');
  if (hint) hint.textContent = isOpen ? '\u25bc collapse' : '\u25b6 expand';
  if (trEl) trEl.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
}

// ── Footer ────────────────────────────────────────────────────────────────────
function renderFooter(D) {
  const el = document.getElementById('rpt-footer');
  if (!el) return;
  const m = D.meta;
  el.innerHTML =
    '<span>' + escHtml(m.project) + ' \u00b7 ' + escHtml(m.environment) + '</span>' +
    '<span>Generated ' + escHtml(m.generated_at) + ' \u00b7 Duration ' + escHtml(m.duration) + '</span>';
}

// ── Update charts after theme change ─────────────────────────────────────────
function updateChartTheme() {
  try {
    const grid = cssVar('--chart-grid');
    const txt  = cssVar('--chart-text');
    const surf = cssVar('--surface');
    if (donutChart) {
      donutChart.data.datasets[0].borderColor = surf;
      donutChart.update();
    }
    if (trendChart) {
      trendChart.options.scales.x.ticks.color = txt;
      trendChart.options.scales.y.ticks.color = txt;
      trendChart.options.scales.y.grid.color  = grid;
      trendChart.options.plugins.legend.labels.color = txt;
      trendChart.update();
    }
    if (covChart) {
      covChart.data.datasets[0].borderColor = surf;
      covChart.update();
    }
  } catch(e) { console.error('updateChartTheme error:', e); }
}

// ── Utilities ─────────────────────────────────────────────────────────────────
function escHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function formatDur(s) {
  if (s < 1) return Math.round(s * 1000) + ' ms';
  return s.toFixed(2) + ' s';
}

// ── Lightbox ──────────────────────────────────────────────────────────────────
function openLightbox(src) {
  const img = document.getElementById('lightbox-img');
  const lb  = document.getElementById('lightbox');
  if (img) img.src = src;
  if (lb)  lb.classList.add('open');
}

function closeLightbox() {
  const lb = document.getElementById('lightbox');
  if (lb) lb.classList.remove('open');
}

document.addEventListener('keydown', function(e) {
  if (e.key === 'Escape') closeLightbox();
});

// ── PDF Export — programmatic jsPDF + autoTable ───────────────────────────────
function exportPDF() {
  const btn = document.getElementById('pdf-btn');
  if (btn) { btn.classList.add('loading'); btn.textContent = '\u23f3 Generating\u2026'; }
  try {
    const D = window._QA_DATA;
    if (!D) throw new Error('Report data not loaded yet.');

    const { jsPDF } = window.jspdf;

    // ── Detect current effective theme ──
    const forcedTheme = document.documentElement.getAttribute('data-theme');
    const systemDark  = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
    const isDark      = forcedTheme === 'dark' || (!forcedTheme && systemDark);

    // ── Theme colour palettes ──
    const T = isDark ? {
      bg:      [15,  23,  42],   surface: [30,  41,  59],
      surface2:[20,  32,  50],   border:  [51,  65,  85],
      text:    [241, 245, 249],  text2:   [148, 163, 184],
      label:   [100, 116, 139],
      pass:    [74,  222, 128],  fail:    [248, 113, 113],
      skip:    [251, 146, 60],   accent:  [99,  102, 241],
    } : {
      bg:      [247, 246, 243],  surface: [255, 255, 255],
      surface2:[241, 240, 237],  border:  [229, 227, 222],
      text:    [26,  26,  46],   text2:   [75,  85,  99],
      label:   [156, 163, 175],
      pass:    [21,  128, 61],   fail:    [185, 28,  28],
      skip:    [180, 83,  9],    accent:  [99,  102, 241],
    };

    const pdf  = new jsPDF({ orientation: 'portrait', unit: 'mm', format: 'a4' });
    const PW   = 210;
    const MG   = 14;
    const CW   = PW - MG * 2;

    function newPage() {
      pdf.addPage();
      pdf.setFillColor(...T.bg);
      pdf.rect(0, 0, PW, 297, 'F');
    }

    function sectionLabel(text, y) {
      pdf.setFont('helvetica', 'bold');
      pdf.setFontSize(6.5);
      pdf.setTextColor(...T.label);
      pdf.text(text.toUpperCase(), MG, y);
    }

    // ── PAGE 1 ────────────────────────────────────────────────────────────────
    pdf.setFillColor(...T.bg);
    pdf.rect(0, 0, PW, 297, 'F');

    // Header bar
    pdf.setFillColor(...T.accent);
    pdf.rect(0, 0, PW, 20, 'F');
    pdf.setFont('helvetica', 'bold');
    pdf.setFontSize(13);
    pdf.setTextColor(255, 255, 255);
    pdf.text(D.meta.project + '  \u2014  Test Report', MG, 13);
    pdf.setFont('helvetica', 'normal');
    pdf.setFontSize(7.5);
    pdf.text(D.meta.environment.toUpperCase() + '   \u00b7   ' + D.meta.generated_at, PW - MG, 13, { align: 'right' });

    // Sub-header
    let y = 28;
    y += 2;  // small gap below header bar — BASE/LOG/DURATION removed per spec

    // Stat cards (5 boxes)
    const stats = [
      { label: 'TOTAL',     value: String(D.summary.total),     color: T.accent },
      { label: 'PASSED',    value: String(D.summary.passed),    color: T.pass   },
      { label: 'FAILED',    value: String(D.summary.failed),    color: T.fail   },
      { label: 'SKIPPED',   value: String(D.summary.skipped),   color: T.skip   },
      { label: 'PASS RATE', value: D.summary.pass_rate + '%',   color: D.summary.pass_rate === 100 ? T.pass : (D.summary.failed > 0 ? T.fail : T.accent) },
    ];
    const boxW = (CW - 4 * 3) / 5;
    stats.forEach(function(s, i) {
      const bx = MG + i * (boxW + 3);
      pdf.setFillColor(...T.surface);
      pdf.roundedRect(bx, y, boxW, 20, 2, 2, 'F');
      pdf.setDrawColor(...T.border);
      pdf.setLineWidth(0.2);
      pdf.roundedRect(bx, y, boxW, 20, 2, 2, 'S');
      pdf.setFont('helvetica', 'normal');
      pdf.setFontSize(6);
      pdf.setTextColor(...T.label);
      pdf.text(s.label, bx + boxW / 2, y + 6, { align: 'center' });
      pdf.setFont('helvetica', 'bold');
      pdf.setFontSize(15);
      pdf.setTextColor(...s.color);
      pdf.text(s.value, bx + boxW / 2, y + 16, { align: 'center' });
    });
    y += 27;

    // By Category
    sectionLabel('By Category', y);
    y += 5;
    D.categories.forEach(function(cat) {
      const total   = cat.passed + cat.failed;
      const failPct = total ? cat.failed / total : 0;
      const passPct = total ? cat.passed / total : 0;
      pdf.setFont('helvetica', 'normal');
      pdf.setFontSize(7.5);
      pdf.setTextColor(...T.text);
      pdf.text(cat.name, MG, y + 3);
      const barX = MG + 34; const barW = CW - 34 - 16;
      pdf.setFillColor(...T.border);
      pdf.roundedRect(barX, y - 0.5, barW, 5, 1, 1, 'F');
      if (failPct > 0) { pdf.setFillColor(...T.fail);  pdf.roundedRect(barX, y - 0.5, barW * failPct, 5, 1, 1, 'F'); }
      if (passPct > 0) { pdf.setFillColor(...T.pass);  pdf.roundedRect(barX + barW * failPct, y - 0.5, barW * passPct, 5, 1, 1, 'F'); }
      pdf.setFontSize(6.5);
      pdf.setTextColor(...T.text2);
      pdf.text(cat.failed + 'F / ' + total, barX + barW + 3, y + 3.5);
      y += 8;
    });
    y += 3;

    // Coverage info
    sectionLabel('Code Coverage', y);
    y += 5;
    const cov = D.meta.coverage || 0;
    const tgt = D.meta.coverage_target || 80;
    const covColor = cov >= tgt ? T.pass : (cov >= 50 ? T.skip : T.fail);
    pdf.setFont('helvetica', 'bold');
    pdf.setFontSize(9);
    pdf.setTextColor(...covColor);
    // covered value
    pdf.text(cov + '%', MG, y);
    pdf.setFont('helvetica', 'normal');
    pdf.setFontSize(7.5);
    pdf.setTextColor(...T.text2);
    pdf.text('covered', MG + 10, y);
    y += 5;
    // target value
    pdf.setFont('helvetica', 'bold');
    pdf.setFontSize(9);
    pdf.setTextColor(...T.text);
    pdf.text(tgt + '%', MG, y);
    pdf.setFont('helvetica', 'normal');
    pdf.setFontSize(7.5);
    pdf.setTextColor(...T.text2);
    pdf.text('target', MG + 10, y);
    y += 8;

    // ── Test Results table ────────────────────────────────────────────────────
    sectionLabel('Test Results', y);
    y += 3;

    const statusColor = function(s) {
      if (s === 'passed')  return T.pass;
      if (s === 'failed' || s === 'error') return T.fail;
      return T.skip;
    };

    pdf.autoTable({
      startY: y,
      head:   [['Test', 'Status', 'Duration', 'Failure Details']],
      body:   D.results.map(function(r) {
        const dur     = r.duration < 1 ? Math.round(r.duration * 1000) + 'ms' : r.duration.toFixed(2) + 's';
        const details = r.details && r.details.assert_msg
          ? r.details.assert_msg.substring(0, 80)
          : (r.outcome === 'passed' ? 'Passed' : '\u2014');
        return [r.name.substring(0, 42), r.outcome, dur, details];
      }),
      margin: { left: MG, right: MG },
      styles: {
        font: 'helvetica', fontSize: 7.5, cellPadding: 2.5,
        fillColor: T.surface, textColor: T.text,
        lineColor: T.border, lineWidth: 0.2,
      },
      headStyles: {
        fillColor: T.surface2, textColor: T.label,
        fontStyle: 'bold', fontSize: 6.5, cellPadding: 2,
      },
      alternateRowStyles: { fillColor: T.surface2 },
      columnStyles: {
        0: { cellWidth: 64 },
        1: { cellWidth: 20, halign: 'center', fontStyle: 'bold' },
        2: { cellWidth: 20, halign: 'center' },
        3: { cellWidth: 'auto' },
      },
      didParseCell: function(data) {
        if (data.section === 'body' && data.column.index === 1) {
          data.cell.styles.textColor = statusColor(data.cell.raw);
        }
        // "Passed" in the Failure Details column — dark green, no icon
        if (data.section === 'body' && data.column.index === 3 && data.cell.raw === 'Passed') {
          data.cell.styles.textColor = T.pass;
        }
      },
      theme: 'grid',
    });

    // ── PAGE 2: Failure screenshots ───────────────────────────────────────────
    const failedWithShots = D.results.filter(function(r) {
      return r.outcome !== 'passed' && r.screenshot_path;
    });
    const failedNoShots = D.results.filter(function(r) {
      return r.outcome !== 'passed' && !r.screenshot_path && r.details && r.details.assert_msg;
    });

    if (failedWithShots.length > 0 || failedNoShots.length > 0) {
      newPage();
      // Page header stripe
      pdf.setFillColor(...T.accent);
      pdf.rect(0, 0, PW, 12, 'F');
      pdf.setFont('helvetica', 'bold');
      pdf.setFontSize(10);
      pdf.setTextColor(255, 255, 255);
      pdf.text('Failure Details & Screenshots', MG, 8.5);

      y = 20;

      // Failed with screenshots first
      failedWithShots.forEach(function(r) {
        if (y > 230) { newPage(); y = 14; }

        // Test name chip
        pdf.setFillColor(...T.fail);
        pdf.roundedRect(MG, y, 4, 4, 0.5, 0.5, 'F');
        pdf.setFont('helvetica', 'bold');
        pdf.setFontSize(8);
        pdf.setTextColor(...T.fail);
        pdf.text(r.name.substring(0, 65), MG + 6, y + 3);
        y += 7;

        // Class path
        if (r.cls) {
          pdf.setFont('helvetica', 'normal');
          pdf.setFontSize(6.5);
          pdf.setTextColor(...T.label);
          pdf.text(r.cls, MG, y);
          y += 5;
        }

        // Error message
        if (r.details && r.details.assert_msg) {
          const msgLines = pdf.splitTextToSize('\u2717 ' + r.details.assert_msg, CW);
          pdf.setFont('helvetica', 'normal');
          pdf.setFontSize(7);
          pdf.setTextColor(...T.fail);
          pdf.text(msgLines.slice(0, 3), MG, y);
          y += msgLines.slice(0, 3).length * 3.8 + 2;
        }

        // Locators tried
        if (r.details && r.details.locators && r.details.locators.length) {
          pdf.setFont('courier', 'normal');
          pdf.setFontSize(6.5);
          pdf.setTextColor(...T.text2);
          r.details.locators.slice(0, 2).forEach(function(l) {
            pdf.text('\u2192 ' + l.substring(0, 80), MG + 2, y);
            y += 3.8;
          });
          y += 1;
        }

        // Screenshot — only render when path is present, no red border
        if (r.screenshot_path) {
          try {
            const shotH = 58; const shotW = Math.min(CW, shotH * (16 / 9));
            pdf.addImage(r.screenshot_path, 'PNG', MG, y, shotW, shotH);
            y += shotH + 3;
          } catch(_) { /* skip unrenderable image */ }
        }

        // Divider
        pdf.setDrawColor(...T.border);
        pdf.setLineWidth(0.15);
        pdf.line(MG, y, PW - MG, y);
        y += 6;
      });

      // Failed without screenshots (details only)
      failedNoShots.forEach(function(r) {
        if (y > 260) { newPage(); y = 14; }
        pdf.setFont('helvetica', 'bold');
        pdf.setFontSize(7.5);
        pdf.setTextColor(...T.fail);
        pdf.text('\u2717 ' + r.name.substring(0, 65), MG, y);
        y += 5;
        if (r.details && r.details.assert_msg) {
          const lines = pdf.splitTextToSize(r.details.assert_msg, CW);
          pdf.setFont('helvetica', 'normal');
          pdf.setFontSize(7);
          pdf.setTextColor(...T.text2);
          pdf.text(lines.slice(0, 4), MG, y);
          y += lines.slice(0, 4).length * 3.8 + 4;
        }
      });
    }

    // ── Save ─────────────────────────────────────────────────────────────────
    const envStr = D.meta.environment || 'report';
    pdf.save('qa-report-' + envStr + '-' + new Date().toISOString().slice(0, 10) + '.pdf');

  } catch(e) {
    alert('PDF generation failed: ' + e.message + '\n\nCheck the browser console for details.');
    console.error('exportPDF error:', e);
  }
  if (btn) { btn.classList.remove('loading'); btn.textContent = '\u2193 Export PDF'; }
}
"""


# ── HTML shell ────────────────────────────────────────────────────────────────

_HTML_SHELL = """<!DOCTYPE html>
<html lang="en" data-theme="" data-default-theme="__THEME__">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <meta name="description" content="QA Test Report \u2014 __ENV__"/>
  <meta name="robots" content="noindex"/>
  <title>__TITLE__</title>
  <link rel="stylesheet" href="assets/report.css"/>
  <!-- highlight.js — theme toggled by JS based on current colour mode -->
  <link id="hljs-theme" rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github.min.css"/>
  <!-- CDN libraries -->
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"></script>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/jspdf/2.5.1/jspdf.umd.min.js"></script>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/jspdf-autotable/3.8.2/jspdf.plugin.autotable.min.js"></script>
</head>
<body>

<!-- Lightbox -->
<div id="lightbox" role="dialog" aria-modal="true" aria-label="Screenshot preview" onclick="closeLightbox()">
  <img id="lightbox-img" src="" alt="Failure screenshot"/>
</div>

<div id="app">
  <header class="rpt-header" id="rpt-header" role="banner"></header>

  <!-- Loading state -->
  <div id="loading-state" role="status" aria-live="polite">
    <div class="spinner"></div>
    <p>Loading report data\u2026</p>
  </div>

  <!-- Error state -->
  <div id="error-state" hidden aria-live="assertive">
    <div class="error-icon">\u26a0</div>
    <h2>Report data unavailable</h2>
    <p id="error-detail"></p>
    <p class="error-hint">
      If viewing locally, serve via HTTP:<br/>
      <code>python -m http.server 8080</code>
    </p>
  </div>

  <!-- Report body (hidden until data loaded) -->
  <div id="pdf-body" hidden>

    <!-- Summary stat cards (JS fills) -->
    <div class="stat-cards" id="stat-cards"></div>

    <!-- Row 1: Distribution \u00b7 Durations \u00b7 Trend -->
    <div class="top-row">
      <div class="card" id="card-distribution">
        <div class="sec-label">Result Distribution</div>
        <div class="dist-donut-wrap"><canvas id="donutChart" aria-label="Result distribution donut chart"></canvas></div>
        <div class="dist-legend" id="dist-legend"></div>
      </div>
      <div class="card" id="card-durations">
        <div class="sec-label">Test Durations</div>
        <div class="dur-list" id="dur-list"></div>
      </div>
      <div class="card" id="card-trend">
        <div class="sec-label">Pass Rate Trend \u2014 Last 8 Runs</div>
        <div class="trend-wrap"><canvas id="trendChart" aria-label="Pass rate trend bar chart"></canvas></div>
      </div>
    </div>

    <!-- Row 2: Category \u00b7 Heatmap \u00b7 Coverage -->
    <div class="mid-row">
      <div class="card" id="card-categories">
        <div class="sec-label">By Category</div>
        <div class="cat-list" id="cat-list"></div>
      </div>
      <div class="card" id="card-heatmap">
        <div class="sec-label">Failure Heatmap \u2014 Last 4 Weeks</div>
        <div class="heat-grid-wrap">
          <div class="heat-grid" id="heat-grid"></div>
        </div>
        <div class="heat-legend" id="heat-legend"></div>
      </div>
      <div class="card" id="card-coverage">
        <div class="sec-label">Code Coverage</div>
        <div class="cov-pie-wrap"><canvas id="coverageChart" aria-label="Coverage pie chart"></canvas></div>
        <div class="cov-info" id="cov-info"></div>
      </div>
    </div>

    <!-- Row 3: Test Results -->
    <div class="card" id="card-results">
      <div class="sec-label">Test Results</div>
      <div class="results-wrap">
        <table class="rtable" role="table">
          <thead>
            <tr>
              <th scope="col" style="width:28%">Test</th>
              <th scope="col" style="width:11%">Status</th>
              <th scope="col" style="width:9%">Duration</th>
              <th scope="col" style="width:8%">Flakiness</th>
              <th scope="col">Details</th>
            </tr>
          </thead>
          <tbody id="results-tbody"></tbody>
        </table>
      </div>
    </div>

  </div><!-- /pdf-body -->

  <footer class="rpt-footer" id="rpt-footer" role="contentinfo"></footer>

</div><!-- /app -->

<script>
/* Inline report data — no HTTP fetch required, works with file:// */
window._QA_DATA = __REPORT_DATA__;
</script>
<script src="assets/report.js"></script>
</body>
</html>
"""


# ── generate_report ───────────────────────────────────────────────────────────

def generate_report(
    results: list[dict],
    session_start: float,
    output_path: Path,          # e.g. reports/staging/report.html
    project_name: str = "QA Web Agent",
    environment: str = "staging",
    base_url: str = "",
    log_level: str = "info",
    coverage: int = 0,
    coverage_target: int = 80,
    history_path: Path | None = None,
    theme_style: str = "system",   # "system" | "light" | "dark"
) -> None:
    """Write 4 report files: report.json, assets/report.css, assets/report.js, report.html."""

    total   = len(results)
    passed  = sum(1 for r in results if r.get("outcome") == "passed")
    failed  = sum(1 for r in results if r.get("outcome") in ("failed", "error"))
    skipped = sum(1 for r in results if r.get("outcome") == "skipped")
    dur_s   = time.time() - session_start
    gen_at  = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    pass_rate = round(passed / total * 100) if total else 0

    # Enrich results
    enriched: list[dict] = []
    for idx, r in enumerate(results):
        name, cls, env = _parse_nodeid(r.get("nodeid", r.get("name", "")))
        details = _parse_failure_details(r.get("longrepr", "") or "")
        enriched.append({
            "_idx":           idx,
            "name":           name or r.get("name", ""),
            "cls":            cls  or r.get("class", ""),
            "outcome":        r.get("outcome", "unknown"),
            "duration":       round(r.get("duration", 0.0), 3),
            "env":            env,
            "details":        details,
            "screenshot_path": _screenshot_rel_path(r.get("screenshot"), output_path.parent),
            "flakiness":      _flakiness_bars(r.get("outcome", "")),
        })

    categories = _compute_categories(enriched)

    # History / trend
    current_run = {
        "run_id":  f"Run {datetime.datetime.now().strftime('%m-%d %H:%M')}",
        "passed":  passed,
        "failed":  failed,
        "skipped": skipped,
    }
    if history_path is None:
        history_path = output_path.parent.parent / "run_history.json"
    trend = _load_and_update_history(history_path, current_run)

    # Duration list (top 8, sorted longest first)
    dur_sorted = sorted(enriched, key=lambda r: -r["duration"])[:8]

    report_data = {
        "meta": {
            "project":         project_name,
            "environment":     environment,
            "base_url":        base_url,
            "log_level":       log_level,
            "coverage":        coverage,
            "coverage_target": coverage_target,
            "generated_at":    gen_at,
            "duration":        _duration_str(dur_s),
        },
        "summary": {
            "total":     total,
            "passed":    passed,
            "failed":    failed,
            "skipped":   skipped,
            "pass_rate": pass_rate,
        },
        "results":    enriched,
        "categories": categories,
        "trend":      trend,
        "heatmap":    _DUMMY_HEATMAP,
        "dur_list":   [
            {
                "name":     r["name"],
                "duration": r["duration"],
                "outcome":  r["outcome"],
                "_idx":     r["_idx"],
            }
            for r in dur_sorted
        ],
    }

    # ── Write files ──────────────────────────────────────────────────────────
    report_dir = output_path.parent
    assets_dir = report_dir / "assets"
    report_dir.mkdir(parents=True, exist_ok=True)
    assets_dir.mkdir(parents=True, exist_ok=True)

    # 1. report.json — pure data
    (report_dir / "report.json").write_text(
        json.dumps(report_data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # 2. assets/report.css
    (assets_dir / "report.css").write_text(_CSS, encoding="utf-8")

    # 3. assets/report.js
    (assets_dir / "report.js").write_text(_JS, encoding="utf-8")

    # 4. report.html — self-contained shell with data embedded inline
    title      = f"{html.escape(project_name)} \u2014 Test Report"
    safe_env   = html.escape(environment)
    safe_theme = html.escape(theme_style if theme_style in ("system", "light", "dark") else "system")
    # "system" → empty data-theme (CSS media query takes over); else force the value
    html_theme = "" if safe_theme == "system" else safe_theme
    # Embed report_data as a JS literal so the report works without an HTTP server.
    # Images reference relative paths (images/FAIL_name.png) rather than base64.
    data_json = json.dumps(report_data, ensure_ascii=False)
    shell = (
        _HTML_SHELL
        .replace("__TITLE__",       title)
        .replace("__ENV__",         safe_env)
        .replace("__THEME__",       html_theme)
        .replace("__REPORT_DATA__", data_json)
    )
    output_path.write_text(shell, encoding="utf-8")
