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

    E.g. /abs/reports/staging/images/<uuid>.png → images/<uuid>.png
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
        return f"{round(seconds * 1000)} ms"
    if seconds < 60:
        return f"{seconds:.1f}s"
    m = int(seconds // 60)
    s = round(seconds % 60)
    return f"{m}m {s}s" if s else f"{m}m"


_LOCATOR_RE = re.compile(
    r"(get_by_role|get_by_label|get_by_text|get_by_placeholder|"
    r"locator\(|click_button|fill_input|click_link|open_page|"
    r"fill\(|click\(|goto\()"
)

_STEP_RE = re.compile(r"^\s+([✓✗])\s+(Step\s+\d+\s+\[L\d+[^\]]*\]\s+.+?)(?:\s+\((\d+(?:\.\d+)?(?:ms|s))\))?\s*$")


def _parse_failure_details(longrepr: str) -> dict:
    if not longrepr:
        return {"assert_msg": "", "locators": [], "short_trace": "", "steps": []}
    lines = longrepr.splitlines()

    # ── Parse steps first (✓/✗ lines) ────────────────────────────────────────
    steps: list[dict] = []
    step_line_indices: set[int] = set()
    for idx, ln in enumerate(lines):
        m = _STEP_RE.match(ln)
        if m:
            passed = m.group(1) == "✓"
            label = m.group(2).strip()
            msg = ""
            dur = 0.0
            # Parse duration from group 3: "123ms" or "1.23s"
            dur_str = m.group(3)
            if dur_str:
                if dur_str.endswith("ms"):
                    dur = float(dur_str[:-2]) / 1000
                elif dur_str.endswith("s"):
                    dur = float(dur_str[:-1])
            step_line_indices.add(idx)
            if not passed and idx + 1 < len(lines):
                nxt = lines[idx + 1]
                if nxt.strip() and not _STEP_RE.match(nxt):
                    msg = nxt.strip()
                    step_line_indices.add(idx + 1)
            steps.append({"label": label, "passed": passed, "msg": msg, "duration": round(dur, 3)})

    # ── Assert message ────────────────────────────────────────────────────────
    # 1) Try E-prefixed lines (standard pytest failures)
    e_lines = [ln.lstrip("E").strip() for ln in lines if ln.lstrip().startswith("E ")]
    assert_msg = e_lines[-1] if e_lines else ""
    # 2) Try "Flow '...' failed" header (custom flow failures)
    if not assert_msg:
        for ln in lines:
            s = ln.strip()
            if s.startswith("Flow ") and "failed" in s:
                assert_msg = s
                break
    # 3) Fallback to common error prefixes
    if not assert_msg:
        for ln in reversed(lines):
            s = ln.strip()
            if any(s.startswith(x) for x in ("AssertionError", "TimeoutError", "Error:", "assert ")):
                assert_msg = s
                break
    if len(assert_msg) > 260:
        assert_msg = assert_msg[:257] + "…"

    # ── Locators ──────────────────────────────────────────────────────────────
    locators: list[str] = []
    for ln in lines:
        if _LOCATOR_RE.search(ln):
            c = ln.strip()
            if c and c not in locators:
                locators.append(c)
    locators = locators[:3]

    # ── Short trace — exclude step lines and their error messages ─────────────
    trace_lines = [
        ln for idx, ln in enumerate(lines)
        if ln.strip()
        and idx not in step_line_indices
        and not ln.lstrip().startswith("E ")
        and not ln.strip().startswith("_ ")
    ]
    short_trace = "\n".join(trace_lines[-5:])

    return {"assert_msg": assert_msg, "locators": locators, "short_trace": short_trace, "steps": steps}


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
/* ── QA-SPECIFIC COLOR VARIABLES ── */
:root, [data-bs-theme="light"] {
  --qa-pass:     #15803d;
  --qa-pass-bg:  #dcfce7;
  --qa-fail:     #b91c1c;
  --qa-fail-bg:  #fee2e2;
  --qa-skip:     #b45309;
  --qa-skip-bg:  #fef3c7;
  --chart-grid:  var(--bs-border-color);
  --chart-text:  var(--bs-secondary-color);
  --chart-bg:    var(--bs-body-bg);
}
[data-bs-theme="dark"] {
  --qa-pass:     #4ade80;
  --qa-pass-bg:  rgba(74,222,128,.12);
  --qa-fail:     #f87171;
  --qa-fail-bg:  rgba(248,113,113,.12);
  --qa-skip:     #fb923c;
  --qa-skip-bg:  rgba(251,146,60,.12);
  --chart-grid:  var(--bs-border-color);
  --chart-text:  var(--bs-secondary-color);
  --chart-bg:    var(--bs-body-bg);
}

/* ── Ensure [hidden] always wins ── */
[hidden] { display: none !important; }

/* ── App container ── */
#app { max-width: 1280px; margin: 0 auto; padding: 1.5rem 1.5rem 3rem; }

/* ── Logo badge ── */
.rpt-logo {
  width: 50px; height: 38px; border-radius: 8px;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  display: flex; align-items: center; justify-content: center;
  color: #fff; font-weight: 800; font-size: 1rem; flex-shrink: 0;
}

/* ── Stat card value colours ── */
.stat-value { font-size: 1.6rem; font-weight: 800; line-height: 1; }
.stat-value.blue   { color: #6366f1; }
.stat-value.green  { color: var(--qa-pass); }
.stat-value.red    { color: var(--qa-fail); }
.stat-value.orange { color: var(--qa-skip); }
.stat-value.purple { color: #8b5cf6; }

/* ── Chart canvas wrappers ── */
.dist-donut-wrap { position: relative; height: 160px; }
.trend-wrap      { position: relative; height: 160px; }
.cov-pie-wrap    { position: relative; height: 130px; }

/* ── Duration bar override ── */
.dur-bar-custom { height: 4px; }

/* ── Heatmap grid ── */
.heat-grid {
  display: grid;
  grid-template-columns: 36px repeat(7, 28px);
  gap: 3px; font-size: 0.68rem; min-width: 240px;
}
.heat-cell {
  width: 28px; height: 22px; border-radius: 3px;
  display: flex; align-items: center; justify-content: center;
  font-size: 0.65rem; font-weight: 600; color: rgba(0,0,0,.5);
}

/* ── Flakiness SVG wrapper ── */
.flik-wrap { display: inline-block; vertical-align: middle; }

/* ── Screenshot thumbnail ── */
.row-thumb {
  height: 75px; width: auto; border-radius: 4px; border: none;
  cursor: zoom-in; display: block; margin-left: auto;
  transition: opacity .15s, transform .15s; object-fit: contain;
}
.row-thumb:hover { opacity: .85; transform: scale(1.04); }

/* ── Detail steps ── */
.det-step { font-size: 0.95rem; padding: 2px 0; word-break: break-word; line-height: 1.5; }
.det-step-msg {
  font-size: 0.82rem; padding: 2px 0 4px 22px;
  border-left: 2px solid var(--qa-fail); margin-left: 8px;
}
.det-stacktrace-section {
  margin-top: 12px; padding-top: 12px;
  border-top: 1px solid var(--bs-border-color);
}

/* ── Stacktrace code block ── */
.det-trace {
  font-size: 0.82rem; white-space: pre-wrap; word-break: break-word;
  max-height: 220px; overflow-y: auto; line-height: 1.6;
}
.det-trace code.hljs { background: transparent; padding: 0; font-size: inherit; }
.det-trace-shot img {
  max-width: 220px; max-height: 150px; border-radius: 4px;
  cursor: zoom-in; display: block; transition: transform .15s;
}
.det-trace-shot img:hover { transform: scale(1.03); }
.det-trace-shot-img {
  max-width: 320px; max-height: 200px; cursor: zoom-in;
  display: block; transition: transform .15s;
}
.det-trace-shot-img:hover { transform: scale(1.03); }

/* ── Print / PDF ── */
@media print {
  * { -webkit-print-color-adjust: exact !important; print-color-adjust: exact !important; }
  .rpt-actions, .modal { display: none !important; }
  .card { box-shadow: none !important; break-inside: avoid; }
}
"""


# ── JS ────────────────────────────────────────────────────────────────────────
# NOTE: raw string — NOT an f-string — so {} are literal JavaScript.

_JS = r"""
'use strict';

// ── Module-level chart references (destroyed before recreation) ───────────────
let donutChart, trendChart, covChart;

// ── Theme ────────────────────────────────────────────────────────────────────
// Modes: 'system' | 'light' | 'dark'
const THEMES = ['system', 'light', 'dark'];
let themeIdx = 0;

function getEffectiveTheme() {
  const mode = THEMES[themeIdx];
  if (mode === 'light' || mode === 'dark') return mode;
  // system — read OS preference
  return (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) ? 'dark' : 'light';
}

function applyTheme() {
  document.documentElement.setAttribute('data-bs-theme', getEffectiveTheme());
}

(function initTheme() {
  try {
    const saved      = localStorage.getItem('qa_theme');
    const envDefault = document.documentElement.getAttribute('data-default-theme') || '';
    const resolved   = (saved !== null) ? saved : envDefault;
    themeIdx = THEMES.indexOf(resolved);
    if (themeIdx < 0) themeIdx = 0;
    applyTheme();
    updateThemeBtn();
    updateHljsTheme();
    // Listen for OS theme changes when in system mode
    if (window.matchMedia) {
      window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function() {
        if (THEMES[themeIdx] === 'system') { applyTheme(); updateChartTheme(); updateHljsTheme(); }
      });
    }
  } catch(e) { console.warn('Theme init failed:', e); }
})();

function cycleTheme() {
  try {
    themeIdx = (themeIdx + 1) % THEMES.length;
    applyTheme();
    localStorage.setItem('qa_theme', THEMES[themeIdx]);
    updateThemeBtn();
    updateChartTheme();
    updateHljsTheme();
  } catch(e) { console.error('cycleTheme error:', e); }
}

function updateThemeBtn() {
  const icons  = ['<i class="bi bi-circle-half"></i> System', '<i class="bi bi-sun"></i> Light', '<i class="bi bi-moon"></i> Dark'];
  const btn = document.getElementById('theme-btn');
  if (btn) btn.innerHTML = icons[themeIdx];
}

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

// ── highlight.js theme sync ───────────────────────────────────────────────────
function updateHljsTheme() {
  const link = document.getElementById('hljs-theme');
  if (!link) return;
  const isDark = getEffectiveTheme() === 'dark';
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

// ── Data init — data is embedded inline, no HTTP fetch required ───────────────
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
    ? '<span class="text-success fw-bold">ALL PASSED</span>'
    : '<span class="text-danger fw-bold">' + s.failed + ' TEST' + (s.failed > 1 ? 'S' : '') + ' FAILED</span>';
  el.innerHTML =
    '<div class="rpt-logo" aria-hidden="true">WUP</div>' +
    '<div>' +
      '<div class="fw-bold fs-6">' + escHtml(m.project) + '</div>' +
      '<div class="text-secondary small d-flex align-items-center gap-2 flex-wrap mt-1">' +
        '<span class="badge rounded-pill text-bg-info text-uppercase">' + escHtml(m.environment) + '</span>' +
        '<span>\u00b7</span>' +
        overall +
      '</div>' +
    '</div>' +
    '<div class="flex-grow-1"></div>' +
    '<div class="d-flex gap-2 align-items-center">' +
      '<span class="text-body-tertiary" style="font-size:.72rem">' + escHtml(m.generated_at) + '</span>' +
      '<button class="btn btn-outline-secondary btn-sm" id="theme-btn" onclick="cycleTheme()" aria-label="Toggle color theme"><i class="bi bi-circle-half"></i> System</button>' +
      '<button class="btn btn-primary btn-sm" id="pdf-btn" onclick="exportPDF()" aria-label="Export report as PDF"><i class="bi bi-file-earmark-pdf"></i> Export PDF</button>' +
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
    return '<div class="col"><div class="card h-100"><div class="card-body p-2">' +
      '<div class="text-uppercase text-body-tertiary fw-bold" style="font-size:.65rem;letter-spacing:.08em">' + escHtml(c.label) + '</div>' +
      '<div class="stat-value ' + c.color + '">' + escHtml(String(c.value)) + '</div>' +
    '</div></div></div>';
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
        chart.ctx.fillStyle = cssVar('--bs-body-color');
        chart.ctx.fillText(pr + '%', cx, cy - 9);
        chart.ctx.font = '600 10px system-ui';
        chart.ctx.fillStyle = cssVar('--bs-secondary-color');
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
          borderColor: cssVar('--bs-body-bg'),
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
        { color: '#4ade80', label: 'Passed',  val: D.summary.passed,  cls: 'text-success' },
        { color: '#f87171', label: 'Failed',  val: D.summary.failed,  cls: 'text-danger'  },
        { color: '#fb923c', label: 'Skipped', val: D.summary.skipped, cls: 'text-warning' },
      ];
      legEl.innerHTML = items.map(function(it) {
        return '<div class="d-flex align-items-center gap-2 py-1 border-top">' +
          '<span class="rounded-circle flex-shrink-0" style="width:10px;height:10px;background:' + it.color + '"></span>' +
          '<span class="flex-grow-1 text-secondary">' + it.label + '</span>' +
          '<span class="fw-bold ' + it.cls + '" style="font-variant-numeric:tabular-nums">' + it.val + '</span>' +
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
      const barColor = r.outcome !== 'passed' ? 'bg-danger' : 'bg-success';
      const name = r.name.length > 30 ? r.name.substring(0, 30) + '\u2026' : r.name;
      return '<div class="d-flex align-items-center gap-2 small">' +
        '<span class="text-secondary text-truncate" style="flex:1" title="' + escHtml(r.name) + '">' + escHtml(name) + '</span>' +
        '<div class="progress dur-bar-custom" style="width:80px"><div class="progress-bar ' + barColor + '" style="width:' + pct + '%;min-width:2px"></div></div>' +
        '<span class="fw-semibold" style="font-variant-numeric:tabular-nums;white-space:nowrap">' + formatDur(r.duration) + '</span>' +
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
          ? cat.failed + ' / ' + total + '<br><span class="text-danger">fail</span>'
          : cat.passed + ' / ' + total + '<br><span class="text-success">pass</span>';
      el.insertAdjacentHTML('beforeend',
        '<div class="d-flex align-items-center gap-2 small mb-1">' +
          '<span class="badge text-bg-info text-center" style="min-width:78px">' + escHtml(cat.name) + '</span>' +
          '<div class="progress flex-grow-1" style="height:8px">' +
            '<div class="progress-bar bg-danger" style="width:' + failPct + '%"></div>' +
            '<div class="progress-bar bg-success" style="width:' + passPct + '%"></div>' +
          '</div>' +
          '<div class="text-secondary text-end" style="min-width:52px;font-size:.72rem">' + statusTxt + '</div>' +
        '</div>');
    });
  } catch(e) { console.error('renderCategories error:', e); }
}

// ── Failure heatmap ───────────────────────────────────────────────────────────
function heatColor(v) {
  if (v === 0) return 'var(--bs-border-color)';
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
    grid.insertAdjacentHTML('beforeend', '<div class="text-body-tertiary"></div>');
    days.forEach(function(d) {
      grid.insertAdjacentHTML('beforeend', '<div class="text-center text-body-tertiary fw-semibold">' + d + '</div>');
    });
    D.heatmap.forEach(function(wk, wi) {
      grid.insertAdjacentHTML('beforeend', '<div class="text-body-tertiary d-flex align-items-center" style="font-size:.66rem">Wk ' + (wi + 1) + '</div>');
      wk.forEach(function(v) {
        grid.insertAdjacentHTML('beforeend',
          '<div class="heat-cell" style="background:' + heatColor(v) + '">' + (v || '') + '</div>');
      });
    });

    const legEl = document.getElementById('heat-legend');
    if (legEl) {
      const colors = ['var(--bs-border-color)', '#bbf7d0', '#fde68a', '#fb923c', '#f87171'];
      legEl.innerHTML =
        '<span class="text-body-tertiary small">fewer</span>' +
        '<span class="d-flex gap-1">' +
          colors.map(function(c) { return '<span style="width:14px;height:10px;border-radius:2px;display:inline-block;background:' + c + '"></span>'; }).join('') +
        '</span>' +
        '<span class="text-body-tertiary small">more failures</span>';
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
        chart.ctx.fillStyle = cssVar('--bs-secondary-color');
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
          backgroundColor: [covColor, cssVar('--bs-border-color')],
          borderColor: cssVar('--bs-body-bg'),
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
        ? '<span class="badge text-bg-success"><i class="bi bi-check-circle-fill"></i> Target met</span>'
        : '<span class="badge text-bg-danger"><i class="bi bi-x-circle-fill"></i> Below target</span>';
      infoEl.innerHTML =
        '<div class="d-flex justify-content-between align-items-center mt-2 small text-secondary">' +
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
      tr.innerHTML = '<td colspan="5" class="text-center text-secondary py-4">No test results found.</td>';
      tbody.appendChild(tr);
      return;
    }
    const frag = document.createDocumentFragment();
    D.results.forEach(function(r, i) {
      const oc = r.outcome;
      const badgeCls = oc === 'passed' ? 'text-bg-success' : (oc === 'failed' || oc === 'error' ? 'text-bg-danger' : 'text-bg-warning');
      const badge = '<span class="badge rounded-pill ' + badgeCls + '">' + escHtml(oc) + '</span>';
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
        detailCell = '<span class="d-inline-flex align-items-center justify-content-center border border-dashed rounded bg-body-secondary text-body-tertiary" style="width:60px;height:36px;font-size:.65rem;line-height:1.2">no<br>shot</span>';
      } else {
        detailCell = '<span class="text-success small"><i class="bi bi-check-circle-fill"></i> All assertions passed</span>';
      }

      // Main row
      const tr = document.createElement('tr');
      tr.className = 'align-middle';
      tr.style.cursor = 'pointer';
      tr.setAttribute('aria-expanded', 'false');
      tr.setAttribute('tabindex', '0');
      tr.setAttribute('aria-label', 'Test: ' + r.name + ', status: ' + oc);
      tr.onclick = function() { toggleDetail(i, tr); };
      tr.onkeydown = function(e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggleDetail(i, tr); } };
      tr.innerHTML =
        '<td>' +
          '<div class="fw-semibold">' + escHtml(r.name) + '</div>' +
          '<div class="text-secondary" style="font-size:.68rem">' + escHtml((r.cls || '').split('::').pop() || (r.cls || '')) + '</div>' +
          '<div class="text-body-tertiary" style="font-size:.65rem" id="expand-hint-' + i + '"><i class="bi bi-chevron-right"></i> expand</div>' +
        '</td>' +
        '<td>' + badge + '</td>' +
        '<td class="text-secondary" style="font-variant-numeric:tabular-nums">' + formatDur(r.duration) + '</td>' +
        '<td><div class="flik-wrap">' + flikSVG + '</div></td>' +
        '<td>' + detailCell + '</td>';

      // Detail row (collapsed by default)
      const trDetail = document.createElement('tr');
      trDetail.className = 'collapse-row';
      trDetail.id = 'rdetail-' + i;
      const td = document.createElement('td');
      td.setAttribute('colspan', '5');
      td.style.padding = '0';
      const collapseDiv = document.createElement('div');
      collapseDiv.className = 'collapse';
      collapseDiv.id = 'collapse-' + i;
      const innerDiv = document.createElement('div');
      innerDiv.className = 'p-3 bg-body-secondary border-top';
      innerDiv.innerHTML = buildDetailLeft(r);
      collapseDiv.appendChild(innerDiv);
      td.appendChild(collapseDiv);
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
  let out = '<div class="d-flex flex-column gap-2">';
  const d = r.details || {};

  // "What failed" — error message banner
  if (d.assert_msg) {
    out += '<div><div class="text-uppercase text-body-tertiary fw-bold mb-1" style="font-size:.65rem;letter-spacing:.08em">What failed</div><div class="text-danger fw-medium" style="font-size:.78rem;word-break:break-word">' + escHtml(d.assert_msg) + '</div></div>';
  }

  // Steps — show ALL steps (pass and fail) with duration
  var allSteps = d.steps || [];
  if (allSteps.length) {
    out += '<div><div class="text-uppercase text-body-tertiary fw-bold mb-1" style="font-size:.65rem;letter-spacing:.08em">Steps</div>';
    allSteps.forEach(function(s) {
      var durTag = s.duration ? ' <span class="text-body-tertiary fw-normal" style="font-size:.75rem">' + formatDur(s.duration) + '</span>' : '';
      if (s.passed) {
        out += '<div class="det-step"><i class="bi bi-check-circle-fill text-success me-1"></i> ' + escHtml(s.label) + durTag + '</div>';
      } else {
        out += '<div class="det-step text-danger fw-semibold"><i class="bi bi-x-circle-fill text-danger me-1"></i> ' + escHtml(s.label) + durTag + '</div>';
        if (s.msg) out += '<div class="det-step-msg text-secondary">' + escHtml(s.msg) + '</div>';
      }
    });
    out += '</div>';
  }

  // Stacktrace — only show trace context (no duplicate step info)
  if (d.short_trace) {
    out += '<div class="det-stacktrace-section"><div class="text-uppercase text-danger fw-bold mb-1" style="font-size:.82rem;letter-spacing:.04em">Stacktrace</div>';
    out += '<div class="d-flex gap-3 align-items-start">';

    out += '<pre class="det-trace font-monospace bg-body border rounded p-2 flex-grow-1"><code class="hljs">' + hljsHighlight(d.short_trace) + '</code></pre>';

    if (r.screenshot_path) {
      out += '<div class="det-trace-shot flex-shrink-0">' +
        '<img class="border rounded" src="' + escHtml(r.screenshot_path) + '" alt="Failure screenshot" onclick="openLightbox(this.src)"/>' +
      '</div>';
    }

    out += '</div></div>';
  } else if (r.screenshot_path) {
    // No trace but there is a screenshot — show it standalone
    out += '<div class="det-stacktrace-section"><div class="text-uppercase text-danger fw-bold mb-1" style="font-size:.82rem;letter-spacing:.04em">Screenshot</div>';
    out += '<div><img class="border rounded det-trace-shot-img" src="' + escHtml(r.screenshot_path) + '" alt="Failure screenshot" onclick="openLightbox(this.src)"/></div>';
    out += '</div>';
  }

  if (!allSteps.length && !d.assert_msg && !d.short_trace) {
    out += '<div class="text-success small"><i class="bi bi-check-circle-fill"></i> Test passed with no errors.</div>';
  }

  out += '</div>';
  return out;
}

function toggleDetail(i, trEl) {
  const collapseEl = document.getElementById('collapse-' + i);
  const hint = document.getElementById('expand-hint-' + i);
  if (!collapseEl) return;
  var bsCollapse = bootstrap.Collapse.getOrCreateInstance(collapseEl, { toggle: false });
  var isOpen = collapseEl.classList.contains('show');
  if (isOpen) {
    bsCollapse.hide();
    if (hint) hint.innerHTML = '<i class="bi bi-chevron-right"></i> expand';
    if (trEl) trEl.setAttribute('aria-expanded', 'false');
  } else {
    bsCollapse.show();
    if (hint) hint.innerHTML = '<i class="bi bi-chevron-down"></i> collapse';
    if (trEl) trEl.setAttribute('aria-expanded', 'true');
  }
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
    const bg   = cssVar('--bs-body-bg');
    if (donutChart) {
      donutChart.data.datasets[0].borderColor = bg;
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
      covChart.data.datasets[0].borderColor = bg;
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
  if (s < 60) return s.toFixed(1) + 's';
  var m = Math.floor(s / 60);
  var sec = Math.round(s % 60);
  return sec ? m + 'm ' + sec + 's' : m + 'm';
}

// ── Lightbox (Bootstrap Modal) ────────────────────────────────────────────────
function openLightbox(src) {
  const img = document.getElementById('lightbox-img');
  if (img) img.src = src;
  var modal = bootstrap.Modal.getOrCreateInstance(document.getElementById('lightboxModal'));
  modal.show();
}

// ── PDF Export — programmatic jsPDF + autoTable ───────────────────────────────

// Load an image from a relative URL and return a data URL via canvas
function _loadImageAsDataURL(src) {
  return new Promise(function(resolve) {
    var img = new Image();
    img.onload = function() {
      var canvas = document.createElement('canvas');
      canvas.width = img.naturalWidth;
      canvas.height = img.naturalHeight;
      canvas.getContext('2d').drawImage(img, 0, 0);
      resolve(canvas.toDataURL('image/png'));
    };
    img.onerror = function() { resolve(''); };
    img.src = src;
  });
}

async function exportPDF() {
  const btn = document.getElementById('pdf-btn');
  if (btn) { btn.classList.add('disabled'); btn.innerHTML = '<i class="bi bi-hourglass-split"></i> Generating\u2026'; }
  try {
    const D = window._QA_DATA;
    if (!D) throw new Error('Report data not loaded yet.');

    // Pre-load all failure screenshots as data URLs
    const shotCache = {};
    const failedResults = D.results.filter(function(r) { return r.outcome !== 'passed' && r.screenshot_path; });
    for (var fi = 0; fi < failedResults.length; fi++) {
      var sp = failedResults[fi].screenshot_path;
      if (sp && !shotCache[sp]) {
        shotCache[sp] = await _loadImageAsDataURL(sp);
      }
    }

    const { jsPDF } = window.jspdf;

    // ── Detect current effective theme ──
    const bsTheme    = document.documentElement.getAttribute('data-bs-theme');
    const isDark     = bsTheme === 'dark';

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
    y += 2;

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
    pdf.text(cov + '%', MG, y);
    pdf.setFont('helvetica', 'normal');
    pdf.setFontSize(7.5);
    pdf.setTextColor(...T.text2);
    pdf.text('covered', MG + 10, y);
    y += 5;
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
        var dur = formatDur(r.duration);
        var details = '';
        if (r.outcome === 'passed') {
          details = 'Passed';
        } else if (r.details && r.details.steps) {
          var fStep = r.details.steps.filter(function(s) { return !s.passed; })[0];
          if (fStep) details = fStep.label.substring(0, 80);
          else if (r.details.assert_msg) details = r.details.assert_msg.substring(0, 80);
          else details = '\u2014';
        } else if (r.details && r.details.assert_msg) {
          details = r.details.assert_msg.substring(0, 80);
        } else {
          details = '\u2014';
        }
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
        if (data.section === 'body' && data.column.index === 3 && data.cell.raw === 'Passed') {
          data.cell.styles.textColor = T.pass;
        }
      },
      theme: 'grid',
    });

    // ── PAGE 2: Failure Details & Screenshots ──────────────────────────────────
    const allFailed = D.results.filter(function(r) { return r.outcome !== 'passed'; });

    if (allFailed.length > 0) {
      newPage();
      pdf.setFillColor(...T.accent);
      pdf.rect(0, 0, PW, 12, 'F');
      pdf.setFont('helvetica', 'bold');
      pdf.setFontSize(10);
      pdf.setTextColor(255, 255, 255);
      pdf.text('Failure Details & Screenshots', MG, 8.5);

      y = 20;

      allFailed.forEach(function(r) {
        // Estimate space needed: name(7) + details(~15) + screenshot(~65) + separator(6)
        var needsSpace = 30;
        var shotData = r.screenshot_path ? shotCache[r.screenshot_path] : '';
        if (shotData) needsSpace += 65;
        if (y + needsSpace > 275) { newPage(); y = 14; }

        // 1. Test name
        pdf.setFillColor(...T.fail);
        pdf.roundedRect(MG, y, 4, 4, 0.5, 0.5, 'F');
        pdf.setFont('helvetica', 'bold');
        pdf.setFontSize(8);
        pdf.setTextColor(...T.fail);
        pdf.text(r.name.substring(0, 65), MG + 6, y + 3);
        y += 7;

        // 2. Failure details — failed step from parsed steps
        var failStep = (r.details && r.details.steps)
          ? r.details.steps.filter(function(s) { return !s.passed; })[0]
          : null;

        if (failStep) {
          var stepLine = pdf.splitTextToSize('\u2717 ' + failStep.label, CW);
          pdf.setFont('courier', 'bold');
          pdf.setFontSize(7);
          pdf.setTextColor(...T.fail);
          pdf.text(stepLine.slice(0, 2), MG, y);
          y += stepLine.slice(0, 2).length * 3.8;
          if (failStep.msg) {
            var msgLine = pdf.splitTextToSize('  ' + failStep.msg, CW - 4);
            pdf.setFont('courier', 'normal');
            pdf.setFontSize(6.5);
            pdf.setTextColor(...T.text2);
            pdf.text(msgLine.slice(0, 3), MG + 2, y);
            y += msgLine.slice(0, 3).length * 3.5;
          }
          y += 2;
        } else if (r.details && r.details.assert_msg) {
          var msgLines = pdf.splitTextToSize('\u2717 ' + r.details.assert_msg, CW);
          pdf.setFont('helvetica', 'normal');
          pdf.setFontSize(7);
          pdf.setTextColor(...T.fail);
          pdf.text(msgLines.slice(0, 3), MG, y);
          y += msgLines.slice(0, 3).length * 3.8 + 2;
        }

        // 3. Screenshot
        if (shotData) {
          try {
            var shotH = 58;
            var shotW = Math.min(CW, shotH * (16 / 9));
            pdf.addImage(shotData, 'PNG', MG, y, shotW, shotH);
            y += shotH + 3;
          } catch(_) { /* skip unrenderable image */ }
        }

        // Separator
        pdf.setDrawColor(...T.border);
        pdf.setLineWidth(0.15);
        pdf.line(MG, y, PW - MG, y);
        y += 6;
      });
    }

    // ── Save ─────────────────────────────────────────────────────────────────
    const envStr = D.meta.environment || 'report';
    pdf.save('qa-report-' + envStr + '-' + new Date().toISOString().slice(0, 10) + '.pdf');

  } catch(e) {
    alert('PDF generation failed: ' + e.message + '\n\nCheck the browser console for details.');
    console.error('exportPDF error:', e);
  }
  if (btn) { btn.classList.remove('disabled'); btn.innerHTML = '<i class="bi bi-file-earmark-pdf"></i> Export PDF'; }
}
"""


# ── HTML shell ────────────────────────────────────────────────────────────────

_HTML_SHELL = """<!DOCTYPE html>
<html lang="en" data-bs-theme="light" data-default-theme="__THEME__">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <meta name="description" content="QA Test Report \u2014 __ENV__"/>
  <meta name="robots" content="noindex"/>
  <title>__TITLE__</title>
  <!-- Bootstrap 5.3.3 -->
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet"/>
  <!-- Bootstrap Icons 1.11.3 -->
  <link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css" rel="stylesheet"/>
  <!-- Custom overrides -->
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

<!-- Lightbox Modal -->
<div class="modal fade" id="lightboxModal" tabindex="-1" aria-label="Screenshot preview" aria-hidden="true">
  <div class="modal-dialog modal-xl modal-dialog-centered">
    <div class="modal-content bg-transparent border-0">
      <div class="text-center">
        <img id="lightbox-img" src="" alt="Failure screenshot" class="img-fluid rounded shadow-lg" style="max-height:90vh"/>
      </div>
    </div>
  </div>
</div>

<div id="app">
  <header class="d-flex align-items-center gap-2 py-3 border-bottom flex-wrap mb-3" id="rpt-header" role="banner"></header>

  <!-- Loading state -->
  <div id="loading-state" class="d-flex flex-column align-items-center justify-content-center gap-3 py-5" role="status" aria-live="polite">
    <div class="spinner-border text-primary" role="status"><span class="visually-hidden">Loading\u2026</span></div>
    <p class="text-secondary">Loading report data\u2026</p>
  </div>

  <!-- Error state -->
  <div id="error-state" hidden class="d-flex flex-column align-items-center justify-content-center gap-3 py-5 text-center" aria-live="assertive">
    <div style="font-size:2.5rem"><i class="bi bi-exclamation-triangle text-warning"></i></div>
    <h2 class="fs-5 text-danger">Report data unavailable</h2>
    <p class="text-secondary" id="error-detail" style="max-width:480px"></p>
    <div class="alert alert-warning small" style="max-width:480px">
      If viewing locally, serve via HTTP:<br/>
      <code>python -m http.server 8080</code>
    </div>
  </div>

  <!-- Report body (hidden until data loaded) -->
  <div id="pdf-body" hidden>

    <!-- Summary stat cards (JS fills) -->
    <div class="row row-cols-2 row-cols-md-5 g-2 mb-3" id="stat-cards"></div>

    <!-- Row 1: Distribution \u00b7 Durations \u00b7 Trend -->
    <div class="row g-3 mb-3">
      <div class="col-md-4">
        <div class="card h-100" id="card-distribution">
          <div class="card-body">
            <div class="text-uppercase text-body-tertiary fw-bold mb-2" style="font-size:.68rem;letter-spacing:.1em">Result Distribution</div>
            <div class="dist-donut-wrap"><canvas id="donutChart" aria-label="Result distribution donut chart"></canvas></div>
            <div id="dist-legend" class="mt-2"></div>
          </div>
        </div>
      </div>
      <div class="col-md-4">
        <div class="card h-100" id="card-durations">
          <div class="card-body">
            <div class="text-uppercase text-body-tertiary fw-bold mb-2" style="font-size:.68rem;letter-spacing:.1em">Test Durations</div>
            <div class="d-flex flex-column gap-1" id="dur-list"></div>
          </div>
        </div>
      </div>
      <div class="col-md-4">
        <div class="card h-100" id="card-trend">
          <div class="card-body">
            <div class="text-uppercase text-body-tertiary fw-bold mb-2" style="font-size:.68rem;letter-spacing:.1em">Pass Rate Trend \u2014 Last 8 Runs</div>
            <div class="trend-wrap"><canvas id="trendChart" aria-label="Pass rate trend bar chart"></canvas></div>
          </div>
        </div>
      </div>
    </div>

    <!-- Row 2: Category \u00b7 Heatmap \u00b7 Coverage -->
    <div class="row g-3 mb-3">
      <div class="col-md-4">
        <div class="card h-100" id="card-categories">
          <div class="card-body">
            <div class="text-uppercase text-body-tertiary fw-bold mb-2" style="font-size:.68rem;letter-spacing:.1em">By Category</div>
            <div id="cat-list"></div>
          </div>
        </div>
      </div>
      <div class="col-md-5">
        <div class="card h-100" id="card-heatmap">
          <div class="card-body">
            <div class="text-uppercase text-body-tertiary fw-bold mb-2" style="font-size:.68rem;letter-spacing:.1em">Failure Heatmap \u2014 Last 4 Weeks</div>
            <div class="overflow-auto">
              <div class="heat-grid" id="heat-grid"></div>
            </div>
            <div class="d-flex align-items-center gap-1 mt-2" id="heat-legend"></div>
          </div>
        </div>
      </div>
      <div class="col-md-3">
        <div class="card h-100" id="card-coverage">
          <div class="card-body">
            <div class="text-uppercase text-body-tertiary fw-bold mb-2" style="font-size:.68rem;letter-spacing:.1em">Code Coverage</div>
            <div class="cov-pie-wrap"><canvas id="coverageChart" aria-label="Coverage pie chart"></canvas></div>
            <div id="cov-info"></div>
          </div>
        </div>
      </div>
    </div>

    <!-- Row 3: Test Results -->
    <div class="card mb-3" id="card-results">
      <div class="card-body">
        <div class="text-uppercase text-body-tertiary fw-bold mb-2" style="font-size:.68rem;letter-spacing:.1em">Test Results</div>
        <div class="table-responsive">
          <table class="table table-hover align-middle mb-0" role="table">
            <thead>
              <tr class="text-uppercase text-body-tertiary" style="font-size:.66rem;letter-spacing:.08em">
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
    </div>

  </div><!-- /pdf-body -->

  <footer class="d-flex justify-content-between border-top pt-3 text-body-tertiary small" id="rpt-footer" role="contentinfo"></footer>

</div><!-- /app -->

<script>
/* Inline report data — no HTTP fetch required, works with file:// */
window._QA_DATA = __REPORT_DATA__;
</script>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
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
        # Prefer direct flow_steps (with accurate duration) over text-parsed steps
        flow_steps = r.get("flow_steps")
        if flow_steps is not None:
            details["steps"] = flow_steps
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
    # Store the theme preference in data-default-theme; JS initTheme() reads it
    html_theme = safe_theme
    # Embed report_data as a JS literal so the report works without an HTTP server.
    # Images reference relative paths (images/<uuid>.png) resolved by the browser.
    data_json = json.dumps(report_data, ensure_ascii=False)
    shell = (
        _HTML_SHELL
        .replace("__TITLE__",       title)
        .replace("__ENV__",         safe_env)
        .replace("__THEME__",       html_theme)
        .replace("__REPORT_DATA__", data_json)
    )
    output_path.write_text(shell, encoding="utf-8")
