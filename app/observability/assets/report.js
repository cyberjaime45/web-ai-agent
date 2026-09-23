const DATA = window.__WEBAGENT_DATA__;
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmtMs = ms => ms >= 60000 ? Math.floor(ms/60000)+'m '+Math.round(ms%60000/1000)+'s' : ms >= 1000 ? (ms/1000).toFixed(1)+'s' : Math.round(ms)+'ms';
const plural = (n, one, many) => `${n} ${n === 1 ? one : (many || one + 's')}`;
const cap = s => s ? s[0].toUpperCase() + s.slice(1) : s;
const failedLike = s => s === 'failed' || s === 'error';
const isFlaky = t => t.retries > 0 && !failedLike(t.status);
const effStatus = t => isFlaky(t) ? 'flaky' : t.status;
const areaOf = t => (t.file.match(/^(?:apps|tests|flows)\/([^/]+)\//) || [,'(root)'])[1];
const areaLabel = a => { const s = a === '(root)' ? 'Other' : a.replace(/^_+/, '').replace(/_/g, ' '); return s.length <= 3 ? s.toUpperCase() : cap(s); };
const suiteTitle = t => t.file_title || t.file.split('/').pop().replace(/\.(md|py)$/, '');
const lvlOf = c => c.level === 'pageerror' ? 'error' : c.level === 'log' ? 'info' : c.level;
const fmtBytes = b => b == null ? '' : b >= 1048576 ? (b/1048576).toFixed(1)+' MB' : b >= 1024 ? (b/1024).toFixed(1)+' KB' : b+' B';
const relTime = (ts, t0) => (ts != null && t0 != null) ? '+' + fmtMs(ts - t0) : '';
const fmtDate = iso => new Date(iso).toLocaleString(undefined, {dateStyle: 'medium', timeStyle: 'short'});
const debounce = (fn, ms = 150) => { let h; return (...a) => { clearTimeout(h); h = setTimeout(() => fn(...a), ms); }; };
const $ = id => document.getElementById(id);

/* ── icons: inline SVG so the report needs no network ── */
const ICONS = {
  check: '<circle cx="12" cy="12" r="10"/><polyline points="16 9 10.5 15 8 12.5"/>',
  x: '<circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/>',
  warn: '<path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>',
  info: '<circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/>',
  skip: '<circle cx="12" cy="12" r="10"/><line x1="8" y1="12" x2="16" y2="12"/>',
  clock: '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
  globe: '<circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>',
  monitor: '<rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/>',
  phone: '<rect x="5" y="2" width="14" height="20" rx="2"/><line x1="12" y1="18" x2="12.01" y2="18"/>',
  play: '<polygon points="6 3 20 12 6 21 6 3"/>',
  layers: '<polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/>',
  copy: '<rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
  chev: '<polyline points="9 18 15 12 9 6"/>',
  close: '<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>',
  search: '<circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>',
  moon: '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>',
  zap: '<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>',
  download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>',
  file: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/>',
  bot: '<rect x="3" y="8" width="18" height="12" rx="2"/><path d="M12 8V4"/><circle cx="12" cy="3" r="1"/><line x1="9" y1="13" x2="9" y2="15"/><line x1="15" y1="13" x2="15" y2="15"/>',
};
const icon = (name, cls = '') => `<svg class="ico ${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name]}</svg>`;

/* ── one vocabulary for status, used by every badge and filter ── */
const STATUS = {
  passed:  {label: 'Passed',          badge: 'success', icon: 'check'},
  failed:  {label: 'Failed',          badge: 'danger',  icon: 'x'},
  error:   {label: 'Error',           badge: 'danger',  icon: 'x'},
  skipped: {label: 'Skipped',         badge: 'neutral', icon: 'skip'},
  flaky:   {label: 'Passed on retry', badge: 'warning', icon: 'warn'},
};
const badge = (text, kind = 'neutral', title = '') =>
  `<span class="qa-badge qa-badge-${kind}"${title ? ` title="${esc(title)}"` : ''}>${text}</span>`;
// Icon-only badge: the label moves to the tooltip and to assistive tech.
const iconBadge = (name, kind, label) =>
  `<span class="qa-badge qa-badge-${kind}" role="img" aria-label="${esc(label)}" title="${esc(label)}">${icon(name)}</span>`;
const HEALED = 'Self-healed: a fallback locator found an element the flow describes. Update the flow so it passes on the first attempt.';
const statusBadge = st => badge(STATUS[st].label, STATUS[st].badge);

const T = DATA.tests, TOT = DATA.totals, ENV = DATA.environment;
// Per-test values every renderer needs — computed once, not per row per keystroke.
T.forEach((t, i) => {
  t._i = i;
  t._title = esc(t.title || t.name);
  t._hay = [t.title, t.name, t.file, t.file_title, t.error && t.error.message, t.profile && t.profile.name, ...(t.markers||[])].join(' ').toLowerCase();
  t._startMs = t.started_at ? new Date(t.started_at).getTime() : null;
});
const titleOf = t => t._title;
const failing = TOT.failed + TOT.errors;
const flakyCount = T.filter(isFlaky).length;
const healCount = T.reduce((n,t) => n + (t.healings||[]).length, 0);
const profiles = [...new Set(T.map(t => t.profile && t.profile.name).filter(Boolean))];
// ISO-8601 strings order correctly with plain comparison — no collator needed.
const byStart = T.map((t,i)=>i).sort((a,b) => { const x = T[a].started_at||'', y = T[b].started_at||''; return x < y ? -1 : x > y ? 1 : 0; });
const bySuite = {};
T.forEach(t => (bySuite[t.file] ||= []).push(t));

/* ── lazy per-test detail (console/network live in assets/data/t-<i>.js) ──
   Shards are JSONP-style scripts because fetch() is blocked on file://. */
const hasDetail = t => t.console !== undefined;
const DETAIL_CB = {}, DETAIL_P = {};
window.__WEBAGENT_DETAIL__ = (i, d) => {
  if (!T[i]) return;
  T[i].console = (d && d.console) || [];
  T[i].network = (d && d.network) || [];
  if (DETAIL_CB[i]) { DETAIL_CB[i](); delete DETAIL_CB[i]; }
};
function loadDetail(i){
  if (hasDetail(T[i])) return Promise.resolve(T[i]);
  if (!DETAIL_P[i]) DETAIL_P[i] = new Promise((ok, err) => {
    DETAIL_CB[i] = () => ok(T[i]);
    const s = document.createElement('script');
    s.src = `assets/data/t-${i}.js`;
    // scripts execute before their load event, so on load the callback has
    // already run — if it hasn't, the shard is missing or corrupt
    const fail = () => {
      if (!DETAIL_CB[i]) return;
      delete DETAIL_CB[i]; delete DETAIL_P[i];
      err(new Error('detail shard unavailable'));
    };
    s.onerror = fail; s.onload = fail;
    document.head.appendChild(s);
  });
  return DETAIL_P[i];
}

/* ── what failed, in words a reviewer can act on ── */
function failedStep(t){
  // The exception propagates up through nested steps, marking each ancestor
  // failed too — the last failed step is the deepest one: the failure site.
  const failed = (t.steps || []).filter(s => s.status === 'failed');
  return failed.length ? failed[failed.length - 1] : null;
}
function cleanError(msg){
  // Drop the layer-chain preamble and Playwright's call log; keep the sentence.
  return String(msg || '')
    .replace(/^L\d(\+L\d)* failed \([^)]*\):\s*/, '')
    .replace(/^Layers? [\d+]+ could not resolve step \d+ \(.*?\)\.\s*(Original:\s*)?/, '')
    .split(/\n|Call log:/)[0]
    .replace(/^Locator\.\w+:\s*/, '').replace(/^Error:\s*/, '').trim();
}
const argParts = args => String(args || '').split(/\s+\|\s+/).map(x => x.trim().replace(/^["']|["']$/g, '')).filter(Boolean);
const ACTION_LABEL = {
  goto: 'Open page', reload: 'Reload page', back: 'Go back', wait_load: 'Wait for page load', switch_tab: 'Switch tab',
  click: 'Click', click_link_text: 'Click link', double_click: 'Double-click', right_click: 'Right-click', hover: 'Hover',
  fill: 'Fill in', type: 'Type into', clear: 'Clear', focus: 'Focus', select: 'Choose option', check: 'Tick', uncheck: 'Untick',
  press: 'Press key', upload: 'Upload file', drag_to: 'Drag', scroll: 'Scroll', screenshot: 'Take screenshot', wait: 'Wait',
  assert_text: 'Check text is shown', assert_not_text: 'Check text is not shown', assert_visible: 'Check element is visible',
  assert_hidden: 'Check element is hidden', assert_url: 'Check page address', assert_enabled: 'Check element is enabled',
  assert_disabled: 'Check element is disabled', assert_checked: 'Check box is ticked',
  wait_for_element: 'Wait for element', wait_for_text: 'Wait for text', wait_for_url: 'Wait for page address',
  run_flow: 'Run shared steps', ai_click: 'AI click', ai_assert: 'AI check', ai_extract: 'AI extract', ai_summarize: 'AI summary',
  inspect_page: 'Inspect page', check_console_network: 'Check console and network', test_responsive: 'Test responsive layout',
  test_form: 'Test form', explore_page: 'Explore page', test_page: 'Test page',
};
const actionLabel = a => ACTION_LABEL[a] || cap(String(a || '').replace(/_/g, ' '));
const INTERACT = {click: 'click', click_link_text: 'click', double_click: 'double-click', right_click: 'right-click', hover: 'hover over',
  fill: 'fill in', type: 'type into', clear: 'clear', focus: 'focus', select: 'choose an option in', check: 'tick', uncheck: 'untick',
  upload: 'upload a file to', drag_to: 'drag', table_click: 'click in', ai_click: 'click'};
function explain(t){
  const s = failedStep(t);
  const raw = (s && s.error) || (t.error && t.error.message) || '';
  if (!s || !s.action) return cleanError(raw) || 'The test stopped with an error.';
  const [a] = argParts(s.args), A = a ? `"${a}"` : 'the element';
  const secs = (raw.match(/Timeout (\d+)ms/) || [])[1];
  const within = secs ? ` within ${Math.round(secs / 1000)} seconds` : '';
  const net = (raw.match(/net::(ERR_[A-Z_]+)/) || [])[1];
  const url = s.evidence && s.evidence.url;
  const checks = (s.checks || []).filter(c => !c.passed && c.severity === 'error');
  if (checks.length) return `The ${actionLabel(s.action).toLowerCase()} step found ${plural(checks.length, 'problem')}: ${checks.map(c => c.name).slice(0, 3).join(', ')}.`;
  if (/strict mode violation/i.test(raw)) return `More than one element matches ${A}, so the step could not tell which one to use.`;
  switch (s.action){
    case 'assert_text': case 'wait_for_text': return `Expected text ${A} was not found on the page${within}.`;
    case 'assert_not_text': return `Text ${A} was on the page, but it should not be.`;
    case 'assert_visible': case 'wait_for_element': return `Expected ${A} to be visible, but it did not appear${within}.`;
    case 'assert_hidden': return `${cap(A)} should have been hidden, but it was still visible.`;
    case 'assert_enabled': return `${cap(A)} should be enabled, but it was disabled or missing.`;
    case 'assert_disabled': return `${cap(A)} should be disabled, but it was enabled or missing.`;
    case 'assert_checked': return `${cap(A)} should be ticked, but it was not.`;
    case 'assert_url': case 'wait_for_url': return `The page address did not match ${A}${url ? ` (the browser was on ${url})` : ''}.`;
    case 'goto': return net ? `The page ${A} could not be reached (${net}).` : `The page ${A} did not finish loading${within}.`;
    case 'wait_load': return `The page did not finish loading${within}.`;
    case 'press': return `Could not press ${A}.`;
    case 'ai_assert': return `The AI check ${A} did not pass.`;
  }
  if (INTERACT[s.action]){
    if (/is not an? <|not a (checkbox|radio|select)/i.test(raw)) return `Found ${A}, but it is not the kind of field this step expected, so it could not ${INTERACT[s.action]} it.`;
    if (/intercepts pointer events/i.test(raw)) return `${cap(A)} is on the page, but something else was covering it.`;
    return `Could not find ${A} on the page to ${INTERACT[s.action]}${within}.`;
  }
  return `The step "${actionLabel(s.action)}${a ? ' ' + A : ''}" did not complete.` + (cleanError(raw) ? ' ' + cleanError(raw) : '');
}
function stepText(s){
  return s.action ? `${esc(actionLabel(s.action))}${s.args ? ` <code>${esc(s.args)}</code>` : ''}` : esc(s.name);
}
function failureShot(t){
  // The viewport at the failure site is the one a reviewer recognises.
  const a = t.artifacts || {};
  const vp = (a.screenshots || []).find(x => x.kind === 'viewport');
  return (vp && vp.path) || a.screenshot || ((a.screenshots || [])[0] || {}).path || null;
}

/* ── theme ── */
const setTheme = m => { document.documentElement.dataset.theme = m; try{localStorage.setItem('webagent-theme', m)}catch(e){} };
setTheme((()=>{try{return localStorage.getItem('webagent-theme')}catch(e){return null}})() || 'light');
$('themebtn').innerHTML = icon('moon');
$('themebtn').onclick = () => setTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark');

/* ── 1. execution summary ── */
(function summary(){
  if (ENV.build_name){ $('htitle').textContent = ENV.build_name; document.title = ENV.build_name; }
  $('envchip').textContent = ENV.env;
  $('hdate').textContent = fmtDate(DATA.created_at);
  $('hrunid').textContent = DATA.run_id;
  $('copyicon').innerHTML = icon('copy');
  $('copyrun').onclick = () => {
    const done = () => { $('copyicon').innerHTML = icon('check'); setTimeout(() => $('copyicon').innerHTML = icon('copy'), 1200); };
    try { navigator.clipboard.writeText(DATA.run_id).then(done, () => {}); } catch(e){}
  };
  const device = profiles.length ? profiles.map(cap).join(' & ') : 'Desktop';
  $('hmeta').innerHTML = [
    [icon('globe'), esc(String(ENV.env).toUpperCase())],
    [icon('monitor'), esc(cap(ENV.browser)) + (ENV.headless ? ' · headless' : '')],
    [icon(profiles.includes('mobile') ? 'phone' : 'monitor'), esc(device)],
    [icon('clock'), esc(fmtMs(TOT.duration_ms))],
    [icon('play'), ENV.ci ? 'CI pipeline' : 'Local run'],
  ].map(([i, v]) => `<span>${i}${v}</span>`).join('');

  const suites = Object.keys(bySuite).length;
  const failedSuites = Object.values(bySuite).filter(ts => ts.some(t => failedLike(t.status))).length;
  const executed = TOT.total - TOT.skipped;
  const v = !TOT.total ? ['unknown', 'info', 'No tests ran', 'The run finished without executing any test.']
    : failing ? ['bad', 'x', `${plural(failing, 'test')} failed`,
        `${failing} of ${TOT.total} tests failed${failedSuites > 1 ? ` across ${failedSuites} suites` : ''}. Each failure is listed below with the step where it stopped.`]
    : TOT.skipped ? ['info', 'info', 'Passed with skipped tests', `All ${executed} tests that ran passed; ${TOT.skipped} ${TOT.skipped === 1 ? 'was' : 'were'} skipped.`]
    : ['good', 'check', 'All tests passed', `All ${TOT.total} tests passed in ${fmtMs(TOT.duration_ms)}.`];
  const healNote = healCount && !failing ? ` ${plural(healCount, 'step')} needed a fallback locator; see Run details.` : '';
  $('verdict').innerHTML = `<div class="run-verdict run-verdict-${v[0]}" role="status">
    <span class="run-verdict-icon">${icon(v[1])}</span>
    <div><p class="run-verdict-headline">${v[2]}</p><p class="run-verdict-detail">${v[3]}${healNote}</p></div></div>`;

  const pct = n => (n / Math.max(TOT.total, 1) * 100).toFixed(2);
  const clean = TOT.passed - flakyCount;
  $('hero').innerHTML = `<div class="run-hero">
    <div class="run-rate"><span class="run-rate-value">${Math.floor(TOT.pass_rate)}<span class="run-rate-unit">%</span></span>
      <span class="run-rate-label">pass rate</span></div>
    <div class="run-hero-counts">
      ${failing ? `<p class="run-attention"><span class="run-attention-value">${failing}</span> ${failing === 1 ? 'test needs' : 'tests need'} attention</p>`
        : TOT.total ? `<p class="run-attention run-attention-clear">${icon('check')} Nothing needs attention</p>` : ''}
      <p class="run-breakdown"><span>${TOT.total} run</span><span class="run-breakdown-pass">${TOT.passed} passed</span>
        ${failing ? `<span class="run-breakdown-fail">${failing} failed</span>` : ''}
        ${flakyCount ? `<span>${flakyCount} passed on retry</span>` : ''}
        ${TOT.skipped ? `<span class="run-breakdown-skip">${TOT.skipped} skipped</span>` : ''}</p>
      <div class="run-bar" role="img" aria-label="${TOT.passed} passed, ${failing} failed, ${TOT.skipped} skipped">
        <div class="run-bar-pass" style="width:${pct(clean)}%"></div><div class="run-bar-flaky" style="width:${pct(flakyCount)}%"></div>
        <div class="run-bar-fail" style="width:${pct(failing)}%"></div><div class="run-bar-skip" style="width:${pct(TOT.skipped)}%"></div></div>
      <p class="run-bar-key"><span class="run-key-pass">passed</span>${flakyCount ? '<span class="run-key-flaky">passed on retry</span>' : ''}
        ${failing ? '<span class="run-key-fail">failed</span>' : ''}${TOT.skipped ? '<span class="run-key-skip">skipped</span>' : ''}</p>
    </div>
    <div class="run-stats">
      <div class="run-stat"><div class="metric-label">Duration</div><div class="metric-value">${esc(fmtMs(TOT.duration_ms))}</div></div>
      <div class="run-stat"><div class="metric-label">Suites</div><div class="metric-value">${suites}</div></div>
    </div></div>`;
  $('foot').textContent = `Generated ${fmtDate(DATA.created_at)} · Web Agent ${ENV.framework}`;
})();

/* ── 2. tests requiring attention ── */
(function attention(){
  const groups = {};
  T.filter(t => failedLike(t.status)).forEach(t => (groups[t.file] ||= []).push(t));
  if (!Object.keys(groups).length) return;
  $('attention').hidden = false;
  // A suite that is a single test (its heading is the test) needs no header of its own.
  $('failures').innerHTML = Object.values(groups).map(ts => `<div class="failure-group">
    ${ts.every(t => (t.title || t.name) === suiteTitle(t)) ? ''
      : `<div class="failure-group-head"><b>${esc(suiteTitle(ts[0]))}</b>${esc(areaLabel(areaOf(ts[0])))} · ${plural(ts.length, 'failure')}</div>`}
    ${ts.map(t => {
      const s = failedStep(t), shot = failureShot(t);
      return `<div class="failure-line">
        <button class="failure-row" data-open="${t._i}" aria-haspopup="dialog">${icon('x')}
          <span class="failure-row-main">
            <span class="failure-row-name">${titleOf(t)}</span>
            <span class="failure-row-why">${esc(explain(t))}</span>
            ${s ? `<span class="failure-row-step">Failed step: ${stepText(s)}</span>` : ''}
            <span class="failure-row-tags">${statusBadge(t.status)}${badge(esc(areaLabel(areaOf(t))))}${badge(icon('clock') + esc(fmtMs(t.duration_ms)))}
              ${profiles.length > 1 && t.profile ? badge(esc(cap(t.profile.name)), 'primary') : ''}
              ${shot ? '' : badge('No screenshot')}</span>
          </span></button>
        ${shot ? `<a class="failure-shot" href="${esc(shot)}" target="_blank" rel="noopener" title="Open the screenshot taken at the failure"><img src="${esc(shot)}" alt="Screen when ${titleOf(t)} failed" loading="lazy"></a>` : ''}
      </div>`;
    }).join('')}</div>`).join('');
})();

/* ── 3. all tests ── */
let statusFilter = '';
const FILTERS = [['', 'All', TOT.total, 'var(--primary)'], ['failed', 'Failed', failing, 'var(--bad)'],
  ['passed', 'Passed', TOT.passed, 'var(--good)'], ['flaky', 'Passed on retry', flakyCount, 'var(--warn)'], ['skipped', 'Skipped', TOT.skipped, 'var(--dot-skip)']]
  .filter(([k, , n]) => !k || n);
$('fchips').innerHTML = FILTERS.map(([k, l, n, c]) =>
  `<button class="qa-tab-btn filter-chip${k ? '' : ' active'}" data-f="${k}" style="--c:${c}">${l}<span class="n">${n}</span></button>`).join('');
$('fchips').querySelectorAll('[data-f]').forEach(ch => ch.onclick = () => {
  statusFilter = ch.dataset.f;
  $('fchips').querySelectorAll('[data-f]').forEach(x => x.classList.toggle('active', x === ch));
  renderTests();
});
const markers = [...new Set(T.flatMap(t => t.markers || []))].sort();
$('marker').innerHTML += markers.map(m => `<option>${esc(m)}</option>`).join('');
$('marker').hidden = !markers.length;   // nothing to pick from — don't show an empty control
const areas = [...new Set(T.map(areaOf))].sort();
$('suite').innerHTML += areas.map(a => `<option value="${esc(a)}">${esc(areaLabel(a))}</option>`).join('');
$('suite').hidden = areas.length < 2;
$('searchicon').innerHTML = icon('search');
$('search').addEventListener('input', debounce(renderTests));
['marker','suite'].forEach(id => $(id).addEventListener('change', renderTests));

function signalBadges(t){
  // Technical signals as badges: red for errors, amber for warnings, and
  // nothing at all when the test stayed clean.
  const c = t.counts || {};
  return [c.con_err && badge(plural(c.con_err, 'console error'), 'danger'),
          c.con_warn && badge(plural(c.con_warn, 'console warning'), 'warning'),
          c.net_bad && badge(plural(c.net_bad, 'failed request')),   // mostly third-party beacons: noted, not alarmed
          c.checks_flagged && badge(plural(c.checks_flagged, 'check flagged', 'checks flagged'), 'warning')].filter(Boolean).join('');
}
const openGroups = {};   // the reader's own open/close choices win over the defaults
function renderTests(){
  const q = $('search').value.toLowerCase(), mk = $('marker').value, ar = $('suite').value;
  const filtering = !!(q || mk || ar || statusFilter);
  const keep = T.filter(t => {
    if (statusFilter === 'failed' ? !failedLike(t.status) : statusFilter === 'flaky' ? !isFlaky(t) :
        statusFilter === 'passed' ? (t.status !== 'passed' || isFlaky(t)) : (statusFilter && t.status !== statusFilter)) return false;
    if (mk && !(t.markers||[]).includes(mk)) return false;
    if (ar && areaOf(t) !== ar) return false;
    return !q || t._hay.includes(q);
  });
  const groups = {};
  keep.forEach(t => (groups[t.file] ||= []).push(t));
  const few = Object.keys(groups).length <= 3;
  // Suites with failures lead; the rest keep their run order.
  const ordered = Object.entries(groups).sort(([, a], [, b]) => b.some(t => failedLike(t.status)) - a.some(t => failedLike(t.status)));
  $('tests').innerHTML = keep.length ? ordered.map(([file, ts]) => {
    const ko = ts.filter(t => failedLike(t.status)).length, time = ts.reduce((n,t) => n + t.duration_ms, 0);
    // Passing suites fold away so the failing ones are what the eye lands on.
    const open = openGroups[file] ?? (ko > 0 || few || filtering);
    return `<div class="tgroup${open ? '' : ' closed'}" data-file="${esc(file)}">
      <button class="tgroup-head" aria-expanded="${open}">${icon('chev', 'toggle-icon')}
        <span class="tgroup-name">${esc(suiteTitle(ts[0]))}<small>${esc(file)}</small></span>
        <span class="tgroup-counts">${ts.length - ko} of ${ts.length} passed${ko ? `<span class="bad">${ko} failed</span>` : ''}</span>
        <span class="trow-dur">${fmtMs(time)}</span></button>
      <div class="tgroup-body">${ts.map(t => {
        const st = effStatus(t);
        return `<button class="trow ${st}" data-open="${t._i}" aria-haspopup="dialog"><span class="sdot ${st}"></span>
          <span class="trow-name">${titleOf(t)}${t.title && t.title !== t.name ? `<span class="fn">${esc(t.name)}</span>` : ''}</span>
          <span class="trow-tags">${signalBadges(t)}
            ${(t.healings||[]).length ? iconBadge('zap', 'warning', HEALED) : ''}
            ${t.agent ? badge(icon('bot') + 'Autonomous', 'info') : ''}
            ${profiles.length > 1 && t.profile ? badge(esc(cap(t.profile.name)), 'primary') : ''}
            ${(t.markers||[]).map(m => badge(esc(m))).join('')}
            ${st !== 'passed' ? statusBadge(st) : ''}</span>
          <span class="trow-dur">${fmtMs(t.duration_ms)}</span></button>`;
      }).join('')}</div></div>`;
  }).join('') : `<div class="empty-state">${icon('search')}No tests match the current filters.</div>`;
}
$('tests').addEventListener('click', e => {
  const head = e.target.closest('.tgroup-head');
  if (!head) return;
  const g = head.parentElement, open = g.classList.toggle('closed') === false;
  head.setAttribute('aria-expanded', open);
  openGroups[g.dataset.file] = open;
});
renderTests();
$('tcount').textContent = TOT.total;

/* ── suites ── */
(function suites(){
  const rows = Object.entries(bySuite).map(([file, ts]) => {
    const ko = ts.filter(t => failedLike(t.status)).length, run = ts.filter(t => t.status !== 'skipped').length;
    return {file, ts, ko, rate: run ? Math.floor((run - ko) / run * 100) : 0, time: ts.reduce((n,t) => n + t.duration_ms, 0)};
  }).sort((a, b) => (b.ko > 0) - (a.ko > 0));
  $('scount').textContent = rows.length;
  $('suites').innerHTML = `<div class="list"><div class="list-head"><span>Suite</span><span>Pass rate</span><span>Results</span><span class="list-muted">Duration</span></div>
    ${rows.map(r => `<button class="list-row" data-suite="${esc(r.file)}">
      <span class="list-name">${esc(suiteTitle(r.ts[0]))}<small>${esc(areaLabel(areaOf(r.ts[0])))} · ${esc(r.file)}</small></span>
      <span class="list-rate ${r.ko ? 'bad' : 'good'}">${r.rate}%</span>
      <span class="list-counts">${r.ts.length - r.ko} of ${r.ts.length} passed${r.ko ? ` · <span class="bad">${r.ko} failed</span>` : ''}
        <span class="list-bar"><span class="run-bar-pass" style="width:${(r.ts.length - r.ko) / r.ts.length * 100}%"></span><span class="run-bar-fail" style="width:${r.ko / r.ts.length * 100}%"></span></span></span>
      <span class="list-muted">${fmtMs(r.time)}</span></button>`).join('')}</div>`;
  $('suites').addEventListener('click', e => {
    const row = e.target.closest('[data-suite]');
    if (!row) return;
    $('search').value = row.dataset.suite;
    showTab('tests'); renderTests();
    $('tests').scrollIntoView({behavior: 'smooth', block: 'start'});
  });
})();

/* ── run details ── */
(function runDetails(){
  const starts = T.map(t => t.started_at).filter(Boolean).sort();
  const dl = rows => rows.filter(r => r[1] != null && r[1] !== '').map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join('');
  const labels = [...new Set(T.map(t => t.profile && (t.profile.label || t.profile.name)).filter(Boolean))];
  $('sum-timing').innerHTML = dl([['Duration', esc(fmtMs(TOT.duration_ms))], ['Started', esc(fmtDate(starts[0] || DATA.created_at))],
    ['Finished', esc(fmtDate(DATA.created_at))], ['Total test time', esc(fmtMs(T.reduce((n,t) => n + t.duration_ms, 0)))]]);
  $('sum-env').innerHTML = dl([['Environment', esc(ENV.env)], ['Build', esc(ENV.build_name || 'Web Test Report')],
    ['Browser', esc(cap(ENV.browser) + (ENV.headless ? ' · headless' : ''))], ['Devices', labels.map(esc).join('<br>')],
    ['Operating system', esc(ENV.os)], ['Run type', ENV.ci ? badge('CI pipeline', 'success') : badge('Local run', 'primary')]]);
  $('sum-tool').innerHTML = dl([['Web Agent', esc(ENV.framework)], ['Python', esc(ENV.python)],
    ['Playwright', esc(ENV.playwright)], ['Run ID', `<span class="mono">${esc(DATA.run_id)}</span>`]]);

  const top = [...T].sort((a,b) => b.duration_ms - a.duration_ms).slice(0, 7);
  const max = Math.max(...top.map(t => t.duration_ms), 1);
  $('slowest').innerHTML = top.length ? top.map(t => `<div class="slow-row">
    <button data-open="${t._i}">${titleOf(t)}</button><span class="list-muted">${fmtMs(t.duration_ms)}</span>
    <span class="list-bar"><span class="${failedLike(t.status) ? 'run-bar-fail' : 'run-bar-pass'}" style="width:${t.duration_ms/max*100}%"></span></span></div>`).join('')
    : '<p class="empty-inline">No tests ran.</p>';

  const healed = T.filter(t => (t.healings||[]).length);
  $('healsum').innerHTML = healed.length
    ? `<p class="sub-lede">These steps passed only because a fallback locator found the element. Update the flow so they pass on the first attempt.</p>`
      + healed.map(t => `<div class="slow-row"><button data-open="${t._i}">${titleOf(t)}</button>
          <span class="list-muted">${plural(t.healings.length, 'step')}</span></div>`).join('')
    : `<p class="empty-inline">${icon('check')} No steps needed a fallback locator.</p>`;
})();

/* ── timeline ── */
(function timeline(){
  const withT = byStart.filter(i => T[i]._startMs != null);
  if (!withT.length){ $('lanes').innerHTML = '<div class="empty-state">No timing data.</div>'; return; }
  const start = i => T[i]._startMs, end = i => start(i) + T[i].duration_ms;
  let t0 = Infinity, t1 = -Infinity;
  withT.forEach(i => { t0 = Math.min(t0, start(i)); t1 = Math.max(t1, end(i)); });
  const span = Math.max(t1 - t0, 1);
  const lanes = [];  // greedy interval assignment ≈ xdist workers
  withT.forEach(i => {
    let L = lanes.find(l => l.end <= start(i) + 1);
    if (!L){ L = {end: 0, items: []}; lanes.push(L); }
    L.items.push(i); L.end = end(i);
  });
  $('wallclock').textContent = `Wall clock ${fmtMs(span)}.`;
  $('lanes').innerHTML = lanes.map((l, n) => `
    <div class="lane"><span class="lb">Lane ${n + 1}</span><div class="track">${l.items.map(i => `
      <button class="tbar ${effStatus(T[i])}" data-open="${i}" title="${titleOf(T[i])} · ${fmtMs(T[i].duration_ms)}"
        style="left:${(start(i)-t0)/span*100}%;width:${Math.max(T[i].duration_ms/span*100, .4)}%"></button>`).join('')}</div></div>`).join('');
  $('ticks').innerHTML = [0,.25,.5,.75,1].map(f => `<span>${fmtMs(span*f)}</span>`).join('');
})();

/* ── tabs, shortcuts, and the one click handler that opens a test ── */
document.querySelectorAll('.qa-tabs [data-tab]').forEach(b => b.onclick = () => showTab(b.dataset.tab));
function showTab(name){
  document.querySelectorAll('.qa-tabs [data-tab]').forEach(b => {
    b.classList.toggle('active', b.dataset.tab === name); b.setAttribute('aria-selected', b.dataset.tab === name);
  });
  document.querySelectorAll('.pane').forEach(p => p.classList.toggle('active', p.id === 'pane-' + name));
  if (name === 'console' || name === 'network') ensureGlobalViews();
}
document.addEventListener('click', e => {
  const o = e.target.closest('[data-open]');
  if (o){ e.preventDefault(); openTest(+o.dataset.open); }
});
document.addEventListener('keydown', e => {
  if (e.key === '/' && !e.target.matches('input,select,textarea')) { e.preventDefault(); showTab('tests'); $('search').focus(); }
  if (e.key === 'Escape') closeDrawer();
});
(function globalBadges(){
  let c = 0, n = 0;
  T.forEach(t => { c += t.counts.console; n += t.counts.network; });
  $('ccount').textContent = c;
  $('ncount').textContent = n;
  $('gconlist').innerHTML = '<div class="empty-inline" style="padding:.75rem">Loading…</div>';
  $('gnetlist').innerHTML = '<div class="empty-inline" style="padding:.75rem">Loading…</div>';
})();
