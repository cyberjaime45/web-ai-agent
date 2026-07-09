"""
Professional HTML Report Generator — v4.

Design:
  ┌ Result Distribution ┐  ┌ Pass Rate Trend (8 runs) ┐  ┌ Code Coverage ┐
  └ Test Results table (TEST | STATUS | DURATION | FLAKINESS | DETAILS)

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


_STEP_RE = re.compile(r"^\s+([✓✗])\s+(Step\s+\d+\s+\[L\d+[^\]]*\]\s+.+?)(?:\s+\((\d+(?:\.\d+)?(?:ms|s))\))?\s*$")
_SUB_FLOW_RE = re.compile(r"↳\s*\[([^\]]+)\]")


def _parse_failure_details(longrepr: str) -> dict:
    if not longrepr:
        return {"steps": []}
    lines = longrepr.splitlines()

    steps: list[dict] = []
    for idx, ln in enumerate(lines):
        m = _STEP_RE.match(ln)
        if not m:
            continue
        passed = m.group(1) == "✓"
        label = m.group(2).strip()
        msg = ""
        dur = 0.0
        dur_str = m.group(3)
        if dur_str:
            if dur_str.endswith("ms"):
                dur = float(dur_str[:-2]) / 1000
            elif dur_str.endswith("s"):
                dur = float(dur_str[:-1])
        if not passed and idx + 1 < len(lines):
            nxt = lines[idx + 1]
            if nxt.strip() and not _STEP_RE.match(nxt):
                msg = nxt.strip()
        sub_flow_m = _SUB_FLOW_RE.search(label)
        steps.append({
            "label": label, "passed": passed, "msg": msg,
            "duration": round(dur, 3),
            "sub_flow": sub_flow_m.group(1) if sub_flow_m else "",
        })

    return {"steps": steps}


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
  --qa-accent:   #4f46e5;
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
  --qa-accent:   #818cf8;
  --chart-grid:  var(--bs-border-color);
  --chart-text:  var(--bs-secondary-color);
  --chart-bg:    var(--bs-body-bg);
}

/* ── Typography scale (centralized, rem-based) ── */
:root {
  --fs-xs:   0.75rem;   /* 12px — micro labels, uppercase caps, metadata */
  --fs-sm:   0.85rem;  /* 14px — body, step rows, messages */
  --fs-md:   1rem;      /* 16px — default body, section headers */
  --fs-lg:   1.25rem;   /* 20px — stat card values, emphasized numbers */
  --fs-xl:   1.5rem;    /* 24px — page/section titles */
  --fs-2xl:  2rem;      /* 32px — hero icons */
  --lh-tight: 1.3;
  --lh-base:  1.5;
  --lh-loose: 1.6;
}
.qa-fs-xs  { font-size: var(--fs-xs)  !important; }
.qa-fs-sm  { font-size: var(--fs-sm)  !important; }
.qa-fs-md  { font-size: var(--fs-md)  !important; }
.qa-fs-lg  { font-size: var(--fs-lg)  !important; }
.qa-fs-xl  { font-size: var(--fs-xl)  !important; }
.qa-fs-2xl { font-size: var(--fs-2xl) !important; }

/* ── Ensure [hidden] always wins ── */
[hidden] { display: none !important; }

/* ════════════════════════════════════════════════════════════════════
   QA PORTAL THEME — enterprise refresh, aligned with the QA website.
   Adds only brand tokens, a navy top bar, softer cards, pill badges and
   brand-blue buttons. Reuses every existing Bootstrap + .qa-* class so
   the JS render layer is untouched. All overrides resolve through the
   --qa-* tokens, so dark mode keeps working.
   ════════════════════════════════════════════════════════════════════ */
:root {
  --qa-navy:       #0d1b2a;
  --qa-blue:       #2563eb;
  --qa-blue-hover: #1d4ed8;
  --qa-radius:     14px;
  --qa-card-sh:    0 1px 2px rgba(16,24,40,.04), 0 1px 3px rgba(16,24,40,.07);
  --bs-body-font-family: 'Poppins', system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
}
[data-bs-theme="light"] { --qa-page-bg: #f4f6f9; --qa-card-bd: #e7ebf0; }
[data-bs-theme="dark"]  { --qa-card-bd: var(--bs-border-color); }

body { font-family: var(--bs-body-font-family); }
[data-bs-theme="light"] body { background: var(--qa-page-bg); color: #1f2937; }

/* ── Cards — rounded, hairline border, soft shadow ── */
.card {
  border: 1px solid var(--qa-card-bd);
  border-radius: var(--qa-radius);
  box-shadow: var(--qa-card-sh);
}
[data-bs-theme="dark"] .card { box-shadow: none; }
.card-body { padding: 1.15rem 1.25rem; }

/* ── Brand top bar (full-bleed navy) ── */
.qa-navbar { background: var(--qa-navy); width: 100%; }
.qa-navbar-inner {
  max-width: 1280px; margin: 0 auto;
  padding: .8rem 1.5rem;
  display: flex; align-items: center; gap: .65rem; flex-wrap: wrap;
}
.qa-navbar-inner,
.qa-navbar-inner .text-secondary,
.qa-navbar-inner .text-body-tertiary { color: #cbd5e1 !important; }
.qa-navbar-inner .fw-bold.fs-6 { color: #fff; }
.qa-navbar-inner .text-success { color: #4ade80 !important; }
.qa-navbar-inner .text-danger  { color: #f87171 !important; }
.qa-navbar-inner .badge.text-bg-info {
  background: rgba(255,255,255,.14) !important; color: #dbeafe !important;
}
.qa-navbar-inner .btn-outline-secondary {
  color: #e2e8f0; border-color: rgba(255,255,255,.25);
}
.qa-navbar-inner .btn-outline-secondary:hover {
  background: rgba(255,255,255,.1); color: #fff; border-color: rgba(255,255,255,.45);
}

/* ── Buttons — brand blue, gently rounded ── */
.btn { border-radius: 9px; font-weight: 500; }
.btn-sm { border-radius: 8px; }
.btn-primary {
  --bs-btn-bg: var(--qa-blue);            --bs-btn-border-color: var(--qa-blue);
  --bs-btn-hover-bg: var(--qa-blue-hover); --bs-btn-hover-border-color: var(--qa-blue-hover);
  --bs-btn-active-bg: var(--qa-blue-hover); --bs-btn-active-border-color: var(--qa-blue-hover);
}

/* ── Badges — soft pills that adapt to theme via --qa-* tokens ── */
.badge { font-weight: 600; }
.badge.rounded-pill { padding: .42em .8em; }
.badge.text-bg-success { background: var(--qa-pass-bg) !important; color: var(--qa-pass) !important; }
.badge.text-bg-danger  { background: var(--qa-fail-bg) !important; color: var(--qa-fail) !important; }
.badge.text-bg-warning { background: var(--qa-skip-bg) !important; color: var(--qa-skip) !important; }

/* ── Stat cards — larger, calmer numbers ── */
.stat-value { font-size: 1.65rem; }
#stat-cards .card-body { padding: .9rem 1rem !important; }

/* ── Table polish ── */
thead th { border-bottom-color: var(--qa-card-bd) !important; }
.table-hover > tbody > tr:hover > * { background-color: rgba(37,99,235,.045); }

/* ── App container ── */
#app { max-width: 1280px; margin: 0 auto; padding: 1.5rem 1.5rem 3rem; }

/* ── Logo badge ── */
.rpt-logo {
  width: 50px; height: 38px; border-radius: 8px;
  background: linear-gradient(135deg, #3b82f6, #1e40af);
  display: flex; align-items: center; justify-content: center;
  color: #fff; font-weight: 800; font-size: var(--fs-md); flex-shrink: 0;
}

/* ── Stat card value colours ── */
.stat-value { font-size: var(--fs-lg); font-weight: 800; line-height: 1; }
.stat-value.blue   { color: #6366f1; }
.stat-value.green  { color: var(--qa-pass); }
.stat-value.red    { color: var(--qa-fail); }
.stat-value.orange { color: var(--qa-skip); }
.stat-value.purple { color: #8b5cf6; }

/* ── Chart canvas wrappers ── */
.dist-donut-wrap { position: relative; height: 160px; }
.trend-wrap      { position: relative; height: 160px; }
.cov-pie-wrap    { position: relative; height: 130px; }

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
.det-step { font-size: var(--fs-sm); padding: 2px 0; word-break: break-word; line-height: var(--lh-base); }
.det-step-msg {
  font-size: var(--fs-sm); margin-left: 8px; margin-top: 4px;
}

/* ── Section groups ── */
.det-section-group { margin: 8px 0 4px 0; }
.det-section-header {
  font-size: var(--fs-sm); font-weight: 700; letter-spacing: .04em;
  color: var(--bs-body-color); margin-bottom: 4px; padding: 4px 0;
  border-bottom: 1px solid var(--bs-border-color);
  display: flex; align-items: center; gap: 6px;
}
.det-section-header .bi-collection { font-size: var(--fs-sm); }
.det-section-body { padding-left: 4px; }
/* ── Sub-flow (nested steps) ── */
.det-subflow-group {
  margin: 6px 0 6px 18px; padding: 8px 12px;
  border-left: 3px solid var(--qa-accent, #6366f1);
  border-radius: 0 6px 6px 0;
  background: color-mix(in srgb, var(--qa-accent, #6366f1) 6%, transparent);
}
.det-subflow-header {
  font-size: var(--fs-sm); font-weight: 600; letter-spacing: .04em;
  color: var(--qa-accent, #6366f1); margin-bottom: 4px;
  display: flex; align-items: center; gap: 6px; cursor: pointer;
  user-select: none;
}
.det-subflow-header .bi { font-size: var(--fs-xs); transition: transform .15s; }
.det-subflow-header.collapsed .bi-chevron-down { transform: rotate(-90deg); }
.det-subflow-header:hover { opacity: .8; }
.det-subflow-body { padding-left: 4px; }
.det-subflow-body.hide { display: none; }
.det-step-trigger {
  font-weight: 600; color: var(--qa-accent, #6366f1);
}
.det-step-trigger i.bi { color: var(--qa-accent, #6366f1) !important; }
/* ── Failure screenshot ── */
.det-screenshot-section {
  margin-top: 12px; padding-top: 12px;
  border-top: 1px solid var(--bs-border-color);
}
.det-screenshot-img {
  max-width: 320px; max-height: 200px; cursor: zoom-in;
  display: block; border-radius: 4px; transition: transform .15s;
}
.det-screenshot-img:hover { transform: scale(1.03); }

/* ── Failed step message (syntax-highlighted, dark theme) ── */
.det-step-msg pre {
  margin: 0; white-space: pre-wrap; word-break: break-word;
  font-size: var(--fs-sm); line-height: var(--lh-loose);
  background: #1e1e2e; color: #cdd6f4;
  border-radius: 6px; padding: 10px 14px;
  border-left: 3px solid var(--qa-fail);
}
.det-step-msg code.hljs {
  background: transparent; padding: 0; font-size: inherit;
  color: inherit;
}
/* Force dark hljs token colors inside failed-step blocks */
.det-step-msg .hljs-keyword { color: #cba6f7; }
.det-step-msg .hljs-string  { color: #a6e3a1; }
.det-step-msg .hljs-number  { color: #fab387; }
.det-step-msg .hljs-built_in,
.det-step-msg .hljs-type    { color: #89dceb; }
.det-step-msg .hljs-title   { color: #89b4fa; }
.det-step-msg .hljs-comment { color: #6c7086; font-style: italic; }
.det-step-msg .hljs-literal { color: #fab387; }
.det-step-msg .hljs-attr,
.det-step-msg .hljs-attribute { color: #89b4fa; }
.det-step-msg .hljs-params  { color: #f2cdcd; }
.det-step-msg .hljs-punctuation { color: #9399b2; }

/* ── Inline step screenshots ── */
.det-step-fail-row, .det-step-shot-row {
  display: flex; align-items: flex-start; gap: 12px;
}
.det-step-fail-content { flex: 1; min-width: 0; }
.det-step-fail-shot, .det-step-shot {
  flex-shrink: 0; margin-top: 2px;
}
.det-step-fail-shot img, .det-step-shot img {
  width: 120px; height: auto; max-height: 80px;
  object-fit: cover; border-radius: 4px; cursor: zoom-in;
  transition: transform .15s;
}
.det-step-fail-shot img:hover, .det-step-shot img:hover { transform: scale(1.05); }

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
    D.trend       = D.trend       || [];
    D.meta.project          = D.meta.project          || 'QA Web Agent';
    D.meta.environment      = D.meta.environment      || '';
    D.meta.coverage         = D.meta.coverage         != null ? D.meta.coverage         : 0;
    D.meta.coverage_target  = D.meta.coverage_target  != null ? D.meta.coverage_target  : 80;
    D.meta.generated_at     = D.meta.generated_at     || '';
    D.meta.duration         = D.meta.duration         || '0 ms';

    showBody();
    renderHeader(D);
    renderSummary(D);
    buildDonut(D);
    buildCoveragePie(D);
    buildTrend(D);
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
      '<span class="qa-fs-xs text-body-tertiary">' + escHtml(m.generated_at) + '</span>' +
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
      '<div class="qa-fs-xs text-uppercase text-body-tertiary fw-bold" style="letter-spacing:.08em">' + escHtml(c.label) + '</div>' +
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

  } catch(e) { console.error('buildDonut error:', e); }
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

// ── Coverage doughnut pie ─────────────────────────────────────
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
        detailCell = '<span class="qa-fs-xs d-inline-flex align-items-center justify-content-center border border-dashed rounded bg-body-secondary text-body-tertiary" style="width:60px;height:36px;line-height:1.2">no<br>shot</span>';
      } else {
        detailCell = '<span class="text-success small"><i class="bi bi-check-circle-fill"></i></span>';
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
          '<div class="d-flex align-items-center gap-2">' +
            '<i class="bi bi-chevron-right qa-fs-xs text-body-tertiary flex-shrink-0" id="expand-hint-' + i + '" style="transition:transform .15s"></i>' +
            '<div>' +
              '<div class="qa-fs-sm">' + escHtml(r.name) + '</div>' +
              '<div class="qa-fs-xs text-secondary">' + escHtml((r.cls || '').split('::').pop() || (r.cls || '')) + '</div>' +
            '</div>' +
          '</div>' +
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

  // Steps — show ALL steps (pass and fail) with duration, grouped by sub-flow
  var allSteps = d.steps || [];
  if (allSteps.length) {
    out += '<div>';

    // ── Helper: render a single step (pass, fail, or skipped) ──
    function renderStep(s) {
      var html = '';
      var hasShot = s.screenshot && s.screenshot !== '';
      var durTag = s.duration ? ' <span class="qa-fs-xs text-body-tertiary fw-normal">' + formatDur(s.duration) + '</span>' : '';
      var isTrigger = s.label && s.label.indexOf('run_flow') !== -1;
      if (s.skipped) {
        html += '<div class="det-step text-body-tertiary"><i class="bi bi-dash-circle text-secondary me-1"></i> ' + escHtml(s.label) + '</div>';
      } else if (s.passed) {
        var cls = isTrigger ? 'det-step det-step-trigger' : 'det-step';
        if (hasShot) html += '<div class="det-step-shot-row">';
        html += '<div class="' + cls + '"><i class="bi bi-check-circle-fill text-success me-1"></i> ' + escHtml(s.label) + durTag + '</div>';
        if (hasShot) {
          html += '<div class="det-step-shot"><img class="border" src="' + escHtml(s.screenshot) + '" alt="Step screenshot" onclick="openLightbox(this.src)"/></div>';
          html += '</div>';
        }
      } else {
        if (hasShot) html += '<div class="det-step-fail-row">';
        html += hasShot ? '<div class="det-step-fail-content">' : '';
        html += '<div class="det-step text-danger fw-semibold"><i class="bi bi-x-circle-fill text-danger me-1"></i> ' + escHtml(s.label) + durTag + '</div>';
        if (s.msg) html += '<div class="det-step-msg"><pre><code class="hljs">' + hljsHighlight(s.msg) + '</code></pre></div>';
        if (hasShot) {
          html += '</div>';
          html += '<div class="det-step-fail-shot"><img class="border" src="' + escHtml(s.screenshot) + '" alt="Step failure" onclick="openLightbox(this.src)"/></div>';
          html += '</div>';
        }
      }
      return html;
    }

    // ── Helper: render a sub-flow group ──
    function renderSubFlowGroup(steps) {
      var html = '';
      var groupPassed = steps.every(function(gs) { return gs.passed || gs.skipped; });
      var groupDur = steps.reduce(function(sum, gs) { return sum + (gs.duration || 0); }, 0);
      var groupDurTag = groupDur ? ' <span class="qa-fs-xs text-body-tertiary fw-normal">' + formatDur(groupDur) + '</span>' : '';
      var groupIcon = groupPassed
        ? '<i class="bi bi-check-circle-fill text-success me-1"></i>'
        : '<i class="bi bi-x-circle-fill text-danger me-1"></i>';
      html += '<div class="det-subflow-group">';
      html += '<div class="det-subflow-header" onclick="var b=this.nextElementSibling;b.classList.toggle(\'hide\');this.classList.toggle(\'collapsed\')">';
      html += groupIcon + ' <i class="bi bi-chevron-down"></i> <span>run_flow: ' + escHtml(steps[0].sub_flow) + '</span>' + groupDurTag;
      html += '</div>';
      html += '<div class="det-subflow-body">';
      steps.forEach(function(gs) { html += renderStep(gs); });
      html += '</div></div>';
      return html;
    }

    // ── Build section groups — sub-flow steps stay in the parent section ──
    var sectionGroups = [];
    var curSection = null;
    allSteps.forEach(function(s) {
      // Sub-flow steps inherit the current section — their own section
      // comes from the sub-flow's markdown and would cause false breaks.
      var sec = s.sub_flow ? curSection : (s.section || '');
      if (sec !== curSection) {
        sectionGroups.push({ name: sec, steps: [] });
        curSection = sec;
      }
      sectionGroups[sectionGroups.length - 1].steps.push(s);
    });

    // Show section headers when there are multiple distinct sections,
    // or when the single section isn't the default "Steps" name.
    var distinctSections = {};
    sectionGroups.forEach(function(g) { if (g.name) distinctSections[g.name] = true; });
    var showSections = Object.keys(distinctSections).length > 1
      || (Object.keys(distinctSections).length === 1 && !distinctSections['Steps']);

    sectionGroups.forEach(function(group) {
      if (showSections && group.name) {
        var secDur = group.steps.reduce(function(sum, s) { return sum + (s.duration || 0); }, 0);
        var secDurTag = secDur ? ' <span class="qa-fs-xs text-body-tertiary fw-normal">' + formatDur(secDur) + '</span>' : '';
        var secFailed  = group.steps.filter(function(s) { return !s.passed && !s.skipped; }).length;
        var secSkipped = group.steps.filter(function(s) { return s.skipped; }).length;
        var secIcon = secFailed > 0
          ? '<i class="bi bi-collection text-danger me-1"></i>'
          : '<i class="bi bi-collection text-success me-1"></i>';
        var secBadges = '';
        if (secFailed  > 0) secBadges += ' <span class="badge text-bg-danger qa-fs-xs">'   + secFailed  + ' failed</span>';
        if (secSkipped > 0) secBadges += ' <span class="badge text-bg-secondary qa-fs-xs">' + secSkipped + ' skipped</span>';
        out += '<div class="det-section-group">';
        out += '<div class="det-section-header">' + secIcon + ' ' + escHtml(group.name) + secDurTag + secBadges + '</div>';
        out += '<div class="det-section-body">';
      }

      var j = 0;
      while (j < group.steps.length) {
        var s = group.steps[j];
        if (s.sub_flow) {
          var subSteps = [];
          var subName = s.sub_flow;
          while (j < group.steps.length && group.steps[j].sub_flow === subName) {
            subSteps.push(group.steps[j]);
            j++;
          }
          out += renderSubFlowGroup(subSteps);
        } else {
          out += renderStep(s);
          j++;
        }
      }

      if (showSections && group.name) {
        out += '</div></div>';
      }
    });

    out += '</div>';
  }

  // Screenshot — show test-level failure screenshot only when no step has its own
  var hasStepShots = allSteps.some(function(st) { return st.screenshot && st.screenshot !== ''; });
  if (r.screenshot_path && !hasStepShots) {
    out += '<div class="det-screenshot-section"><div class="qa-fs-sm text-uppercase text-danger fw-bold mb-1" style="letter-spacing:.04em">Screenshot</div>';
    out += '<div><img class="border rounded det-screenshot-img" src="' + escHtml(r.screenshot_path) + '" alt="Failure screenshot" onclick="openLightbox(this.src)"/></div>';
    out += '</div>';
  }

  if (!allSteps.length) {
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
    if (hint) { hint.classList.remove('bi-chevron-down'); hint.classList.add('bi-chevron-right'); }
    if (trEl) trEl.setAttribute('aria-expanded', 'false');
  } else {
    bsCollapse.show();
    if (hint) { hint.classList.remove('bi-chevron-right'); hint.classList.add('bi-chevron-down'); }
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
          details = fStep ? fStep.label.substring(0, 80) : '\u2014';
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

        // 2. Failure details — steps grouped by section
        var pdfSteps = (r.details && r.details.steps) ? r.details.steps : [];
        if (pdfSteps.length > 0) {
          var curPdfSec = null;
          // Detect distinct top-level sections (ignore sub-flow sections)
          var pdfSecs = {};
          pdfSteps.forEach(function(ps) {
            if (!ps.sub_flow && ps.section) pdfSecs[ps.section] = true;
          });
          var showPdfSec = Object.keys(pdfSecs).length > 1
            || (Object.keys(pdfSecs).length === 1 && !pdfSecs['Steps']);

          pdfSteps.forEach(function(ps) {
            // Sub-flow steps stay in the current section
            var sec = ps.sub_flow ? curPdfSec : (ps.section || '');
            if (showPdfSec && sec && sec !== curPdfSec) {
              curPdfSec = sec;
              if (y + 6 > 275) { newPage(); y = 14; }
              pdf.setFont('helvetica', 'bold');
              pdf.setFontSize(7);
              pdf.setTextColor(...T.accent);
              pdf.text('\u25b8 ' + curPdfSec, MG, y);
              y += 4;
            }
            if (y + 5 > 275) { newPage(); y = 14; }
            var icon = ps.passed ? '\u2713' : '\u2717';
            var indent = ps.sub_flow ? 6 : 2;
            var stepLine = pdf.splitTextToSize(icon + ' ' + ps.label, CW - indent - 2);
            pdf.setFont('courier', ps.passed ? 'normal' : 'bold');
            pdf.setFontSize(6.5);
            pdf.setTextColor(ps.passed ? T.text2 : T.fail);
            pdf.text(stepLine.slice(0, 2), MG + indent, y);
            y += stepLine.slice(0, 2).length * 3.2;
            if (!ps.passed && ps.msg) {
              var msgLine = pdf.splitTextToSize('  ' + ps.msg, CW - indent - 4);
              pdf.setFont('courier', 'normal');
              pdf.setFontSize(6);
              pdf.setTextColor(...T.text2);
              pdf.text(msgLine.slice(0, 3), MG + indent + 2, y);
              y += msgLine.slice(0, 3).length * 3;
            }
          });
          y += 2;
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
  <!-- Brand font (Poppins) -->
  <link rel="preconnect" href="https://fonts.googleapis.com"/>
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
  <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700;800&display=swap" rel="stylesheet"/>
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

<!-- Brand top bar (full-bleed navy) -->
<header class="qa-navbar" role="banner">
  <div class="qa-navbar-inner" id="rpt-header"></div>
</header>

<div id="app">

  <!-- Loading state -->
  <div id="loading-state" class="d-flex flex-column align-items-center justify-content-center gap-3 py-5" role="status" aria-live="polite">
    <div class="spinner-border text-primary" role="status"><span class="visually-hidden">Loading\u2026</span></div>
    <p class="text-secondary">Loading report data\u2026</p>
  </div>

  <!-- Error state -->
  <div id="error-state" hidden class="d-flex flex-column align-items-center justify-content-center gap-3 py-5 text-center" aria-live="assertive">
    <div class="qa-fs-2xl"><i class="bi bi-exclamation-triangle text-warning"></i></div>
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

    <!-- Charts: Distribution \u00b7 Trend \u00b7 Coverage -->
    <div class="row g-3 mb-3">
      <div class="col-md-4">
        <div class="card h-100" id="card-distribution">
          <div class="card-body">
            <div class="qa-fs-xs text-uppercase text-body-tertiary fw-bold mb-2" style="letter-spacing:.1em">Result Distribution</div>
            <div class="dist-donut-wrap"><canvas id="donutChart" aria-label="Result distribution donut chart"></canvas></div>
          </div>
        </div>
      </div>
      <div class="col-md-4">
        <div class="card h-100" id="card-trend">
          <div class="card-body">
            <div class="qa-fs-xs text-uppercase text-body-tertiary fw-bold mb-2" style="letter-spacing:.1em">Pass Rate Trend \u2014 Last 8 Runs</div>
            <div class="trend-wrap"><canvas id="trendChart" aria-label="Pass rate trend bar chart"></canvas></div>
          </div>
        </div>
      </div>
      <div class="col-md-4">
        <div class="card h-100" id="card-coverage">
          <div class="card-body">
            <div class="qa-fs-xs text-uppercase text-body-tertiary fw-bold mb-2" style="letter-spacing:.1em">Code Coverage</div>
            <div class="cov-pie-wrap"><canvas id="coverageChart" aria-label="Coverage pie chart"></canvas></div>
            <div id="cov-info"></div>
          </div>
        </div>
      </div>
    </div>

    <!-- Test Results -->
    <div class="card mb-3" id="card-results">
      <div class="card-body">
        <div class="qa-fs-xs text-uppercase text-body-tertiary fw-bold mb-2" style="letter-spacing:.1em">Test Results</div>
        <div class="table-responsive">
          <table class="table table-hover align-middle mb-0" role="table">
            <thead>
              <tr class="qa-fs-xs text-uppercase text-body-tertiary" style="letter-spacing:.08em">
                <th scope="col" style="width:55%">Test</th>
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
            for fs in flow_steps:
                fs["screenshot"] = _screenshot_rel_path(
                    fs.get("screenshot"), output_path.parent
                )
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

    report_data = {
        "meta": {
            "project":         project_name,
            "environment":     environment,
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
        "trend":      trend,
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
