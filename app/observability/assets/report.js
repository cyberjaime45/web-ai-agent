const DATA = window.__WEBAGENT_DATA__;
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmtMs = ms => ms >= 60000 ? Math.floor(ms/60000)+'m '+Math.round(ms%60000/1000)+'s' : ms >= 1000 ? (ms/1000).toFixed(1)+'s' : Math.round(ms)+'ms';
const failedLike = s => s === 'failed' || s === 'error';
const isFlaky = t => t.retries > 0 && !failedLike(t.status);
const effStatus = t => isFlaky(t) ? 'flaky' : t.status;
const suiteOf = t => (t.file.match(/^(?:apps|tests|flows)\/([^/]+)\//) || [,'(root)'])[1];
const lvlOf = c => c.level === 'pageerror' ? 'error' : c.level === 'log' ? 'info' : c.level;
const fmtBytes = b => b == null ? '' : b >= 1048576 ? (b/1048576).toFixed(1)+' MB' : b >= 1024 ? (b/1024).toFixed(1)+' KB' : b+' B';
const relTime = (ts, t0) => (ts != null && t0 != null) ? '+' + fmtMs(ts - t0) : '';
const NET_CATS = [['','All'], ['bad','Failed'], ['xhr','XHR'], ['doc','Doc'], ['js','JS'], ['css','CSS'], ['img','Img'], ['other','Other']];
const CON_LEVELS = [['error','Errors'], ['warning','Warnings'], ['info','Info'], ['debug','Debug']];
function catOf(n){
  const rt = n.resource_type || '';
  return rt === 'xhr' || rt === 'fetch' ? 'xhr' : rt === 'document' ? 'doc' :
    rt === 'script' ? 'js' : rt === 'stylesheet' ? 'css' :
    rt === 'image' || rt === 'media' || rt === 'font' ? 'img' : 'other';
}
const debounce = (fn, ms = 150) => { let h; return (...a) => { clearTimeout(h); h = setTimeout(() => fn(...a), ms); }; };
const T = DATA.tests, TOT = DATA.totals, ENV = DATA.environment;
// Per-test values every renderer needs — computed once, not per row per keystroke.
T.forEach((t, i) => {
  t._i = i;
  t._title = esc(t.title || t.name);
  t._hay = [t.title, t.name, t.file, t.file_title, t.error && t.error.message, ...(t.markers||[])].join(' ').toLowerCase();
  t._startMs = t.started_at ? new Date(t.started_at).getTime() : null;
});
const titleOf = t => t._title;
const flakyCount = T.filter(isFlaky).length;
const healCount = T.reduce((n,t) => n + (t.healings||[]).length, 0);
// ISO-8601 strings order correctly with plain comparison — no collator needed.
const byStart = T.map((t,i)=>i).sort((a,b) => { const x = T[a].started_at||'', y = T[b].started_at||''; return x < y ? -1 : x > y ? 1 : 0; });

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

/* ── theme ── */
const themebtn = document.getElementById('themebtn');
const setTheme = m => { document.documentElement.dataset.theme = m; try{localStorage.setItem('webagent-theme', m)}catch(e){} };
setTheme((()=>{try{return localStorage.getItem('webagent-theme')}catch(e){return null}})() || 'light');
themebtn.onclick = () => setTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark');

/* ── top bar + hero + pulse + tabs ── */
const failing = TOT.failed + TOT.errors, pill = document.getElementById('statuspill');
pill.className = 'pill ' + (failing ? 'bad' : 'good');
pill.textContent = failing ? `✕ ${failing} Failing` : '✓ All Tests Passed';
const cap = s => s ? s[0].toUpperCase() + s.slice(1) : s;
const triggeredBy = ENV.ci ? 'CI Pipeline' : 'Local run';
document.getElementById('envchip').textContent = ENV.env;
if (ENV.build_name){ document.getElementById('htitle').textContent = ENV.build_name; document.title = ENV.build_name; }
document.getElementById('hdate').textContent = new Date(DATA.created_at).toLocaleString();
document.getElementById('hrunid').textContent = DATA.run_id;
document.getElementById('htrigger').textContent = triggeredBy;
document.getElementById('hbrowser').textContent = cap(ENV.browser) + (ENV.headless ? ' (headless)' : '');
document.getElementById('copyrun').onclick = function(){
  const done = () => { this.textContent = '✓'; setTimeout(() => this.textContent = '⧉', 1200); };
  try { navigator.clipboard.writeText(DATA.run_id).then(done.bind(this), () => {}); } catch(e){}
};
document.getElementById('tcount').textContent = TOT.total;
document.getElementById('pulse').innerHTML = byStart.map(i => {
  const t = T[i], st = effStatus(t);
  return `<div class="px ${st}" title="${titleOf(t)} · ${st}" onclick="openTest(${i})"></div>`;
}).join('');
document.querySelectorAll('.tabs button').forEach(b => b.onclick = () => showTab(b.dataset.tab));
function showTab(name){
  document.querySelectorAll('.tabs button').forEach(b => b.setAttribute('aria-selected', b.dataset.tab === name));
  document.querySelectorAll('.pane').forEach(p => p.classList.toggle('active', p.id === 'pane-' + name));
  if (name === 'console' || name === 'network') ensureGlobalViews();
}
document.getElementById('foot').textContent =
  `Generated on ${new Date(DATA.created_at).toLocaleString()} · Web Agent ${ENV.framework}`;

/* ── overview ── */
(function donut(){
  const segs = [[TOT.passed,'var(--pass)','Passed'], [failing,'var(--fail)','Failed'],
                [flakyCount,'#d99a11','Flaky'], [TOT.skipped,'#b7bcc2','Skipped']];
  let acc = 0; const stops = [];
  const denom = Math.max(TOT.total, 1);
  segs.forEach(([n,c]) => { if(n){ stops.push(`${c} ${acc/denom*100}% ${(acc+n)/denom*100}%`); acc += n; } });
  document.getElementById('donut').innerHTML = `
    <div class="donut" style="background:conic-gradient(${stops.join(',') || 'var(--border) 0 100%'})">
      <i><div><b>${TOT.pass_rate}%</b><span>pass rate</span></div></i></div>
    <div class="legend">${segs.map(([n,c,l]) =>
      `<div><span class="sw" style="background:${c}"></span>${l}<b>${n}</b></div>`).join('')}</div>`;
})();

(function histo(){
  let max = 1;
  T.forEach(t => { if (t.duration_ms > max) max = t.duration_ms; });
  const N = 12, buckets = Array(N).fill(0);
  T.forEach(t => buckets[Math.min(N-1, Math.floor(t.duration_ms/max*N))]++);
  const bmax = Math.max(...buckets, 1);
  document.getElementById('totaldur').textContent = `Total ${fmtMs(TOT.duration_ms)}`;
  document.getElementById('histo').innerHTML =
    `<div class="histo">${buckets.map(b => `<div style="height:${b/bmax*100}%" title="${b} tests"></div>`).join('')}</div>
     <div class="axis"><span>0</span><span>${fmtMs(max)}</span></div>`;
})();

(function healsum(){
  const healed = T.filter(t => (t.healings||[]).length);
  document.getElementById('healsum').innerHTML = healed.length
    ? healed.map(t => `<div class="rowline"><span class="sdot ${effStatus(t)}"></span>
          <span class="nm" onclick="openTest(${t._i})">${titleOf(t)}</span>
          <span class="val" style="color:var(--skip)">🩹 ${t.healings.length} L${Math.max(...t.healings.map(h=>h.layer))}</span></div>`
      ).join('') + `<div class="axis" style="margin-top:10px"><span>${healCount} heal${healCount===1?'':'s'} — update these page objects</span></div>`
    : `<div class="estate"><div class="ecirc">✓</div>
       <div class="ehead">No locators needed healing 🎉</div>
       <div class="esub">Great job! No unstable locators detected.</div></div>`;
})();

(function failures(){
  const fails = T.filter(t => failedLike(t.status));
  document.getElementById('failures').innerHTML = fails.length
    ? fails.map(t => `<div class="failcard" onclick="openTest(${t._i})">
        <div class="fname">${titleOf(t)} ${(t.markers||[]).map(m=>`<span class="chiplet">${esc(m)}</span>`).join(' ')}</div>
        <div class="ferr">${esc((t.error && t.error.message || '').split('\n')[0])}</div>
        <div class="ffile">${t.file_title ? `${esc(t.file_title)} · ` : ''}${esc(t.file)}</div></div>`).join('')
    : `<div class="estate"><div class="ecirc">🛡</div>
       <div class="ehead">No failures 🎉</div>
       <div class="esub">All tests passed successfully.</div></div>`;
})();

(function slowest(){
  const top = [...T].sort((a,b) => b.duration_ms - a.duration_ms).slice(0, 7);
  const max = Math.max(...top.map(t => t.duration_ms), 1);
  document.getElementById('slowest').innerHTML = top.map(t => `
    <div class="rowline" style="border-bottom:none;padding-bottom:2px">
      <span class="nm" onclick="openTest(${t._i})">${titleOf(t)}</span>
      <span class="val">${fmtMs(t.duration_ms)}</span></div>
    <div class="meterwrap"><div class="meter" style="width:${t.duration_ms/max*100}%;background:${failedLike(t.status)?'var(--fail)':'var(--bar)'}"></div></div>`).join('');
})();

/* ── summary tab — three metric groups, each led by a headline value ── */
(function execSummary(){
  // End time = report creation; start = earliest test start when recorded.
  const starts = T.map(t => t.started_at).filter(Boolean).sort();
  const startAt = starts[0] || DATA.created_at;
  const testTime = T.reduce((n,t) => n + t.duration_ms, 0);
  const fmtT = iso => new Date(iso).toLocaleString();
  const row = ([ico, k, v, cls]) =>
    `<div class="xrow"><span class="xk"><i>${ico}</i>${k}</span><span class="xv ${cls || ''}">${v}</span></div>`;
  const lead = (lbl, val) => `<div class="xlead"><div class="lbl">${lbl}</div><div class="num">${val}</div></div>`;
  document.getElementById('sum-timing').innerHTML =
    lead('Wall-clock duration', esc(fmtMs(TOT.duration_ms))) + [
      ['◷', 'Start time', esc(fmtT(startAt))],
      ['◶', 'End time', esc(fmtT(DATA.created_at))],
      ['Σ', 'Cumulative test time', esc(fmtMs(testTime))]
    ].map(row).join('');
  document.getElementById('sum-env').innerHTML =
    lead('Environment', esc(ENV.env)) + [
      ['⬒', 'Build', esc(ENV.build_name || 'Web Test Report')],
      ['◍', 'Browser', esc(cap(ENV.browser) + (ENV.headless ? ' · headless' : ''))],
      ['⌗', 'OS', esc(ENV.os)],
      ['⚙', 'Run type', `<span class="vchip ${ENV.ci ? 'green' : 'blue'}">${ENV.ci ? 'Automated' : 'Local'}</span>`]
    ].map(row).join('');
  document.getElementById('sum-tool').innerHTML =
    lead('Web Agent', esc(ENV.framework)) + [
      ['⬡', 'Python', esc(ENV.python)],
      ['⬢', 'Playwright', esc(ENV.playwright)],
      ['#', 'Run id', esc(DATA.run_id), 'mono']
    ].map(row).join('');
})();

(function suites(){
  const groups = {};
  T.forEach(t => (groups[suiteOf(t)] ||= []).push(t));
  document.getElementById('suites').innerHTML = Object.entries(groups).map(([name, ts]) => {
    const ok = ts.filter(t => !failedLike(t.status)).length;
    const time = ts.reduce((n,t) => n + t.duration_ms, 0);
    const pct = ok/ts.length*100;
    return `<div class="rowline" style="border-bottom:none;padding-bottom:2px">
      <span class="nm mono">${esc(name)}</span>
      <span class="val">${ok}/${ts.length} passed · ${fmtMs(time)}</span></div>
      <div class="meterwrap"><div class="meter" style="width:${pct}%;background:${ok===ts.length?'var(--pass)':'var(--fail)'}"></div></div>`;
  }).join('');
})();

/* ── tests tab ── */
let statusFilter = '';
const FILTERS = [['passed','var(--pass)',TOT.passed], ['failed','var(--fail)',failing],
                 ['flaky','#d99a11',flakyCount], ['skipped','#b7bcc2',TOT.skipped]];
document.getElementById('fchips').innerHTML = FILTERS.map(([s,c,n]) =>
  `<div class="fchip" data-f="${s}"><span class="sw" style="background:${c}"></span>${s[0].toUpperCase()+s.slice(1)}<span class="n">${n}</span></div>`).join('');
document.querySelectorAll('.fchip[data-f]').forEach(ch => ch.onclick = () => {
  statusFilter = statusFilter === ch.dataset.f ? '' : ch.dataset.f;
  document.querySelectorAll('.fchip[data-f]').forEach(x => x.classList.toggle('on', x.dataset.f === statusFilter));
  renderTests();
});
const markers = [...new Set(T.flatMap(t => t.markers || []))].sort();
const markerSel = document.getElementById('marker');
markerSel.innerHTML += markers.map(m => `<option>${esc(m)}</option>`).join('');
markerSel.hidden = !markers.length;   // nothing to pick from — don't show an empty control
const suiteNames = [...new Set(T.map(suiteOf))].sort();
document.getElementById('suite').innerHTML += suiteNames.map(s => `<option>${esc(s)}</option>`).join('');
document.getElementById('search').addEventListener('input', debounce(renderTests));
['marker','suite'].forEach(id => document.getElementById(id).addEventListener('change', renderTests));
document.addEventListener('keydown', e => {
  if (e.key === '/' && !e.target.matches('input,select')) { e.preventDefault(); showTab('tests'); document.getElementById('search').focus(); }
  if (e.key === 'Escape') closeDrawer();
});

function chips(t){
  const {con_err: cerr, con_warn: cwarn, net_bad: nbad} = t.counts;
  return [
    cerr ? `<span class="chiplet cbad" title="console errors">⚠ ${cerr}</span>` : '',
    cwarn ? `<span class="chiplet cwarn" title="console warnings">⚠ ${cwarn}</span>` : '',
    nbad ? `<span class="chiplet cbad" title="failed requests">⇅ ${nbad}</span>` : '',
    t.retries ? `<span class="chiplet" style="color:var(--skip)" title="reruns">↻ ${t.retries}</span>` : '',
    (t.healings||[]).length ? `<span class="chiplet" style="color:var(--skip)" title="healed locators">🩹 ${t.healings.length}</span>` : '',
    ...(t.markers||[]).map(m => `<span class="chiplet">${esc(m)}</span>`)
  ].join('');
}

function renderTests(){
  const q = document.getElementById('search').value.toLowerCase();
  const mk = document.getElementById('marker').value, su = document.getElementById('suite').value;
  const keep = T.filter(t => {
    if (statusFilter === 'failed' ? !failedLike(t.status) :
        statusFilter === 'flaky' ? !isFlaky(t) :
        (statusFilter && t.status !== statusFilter)) return false;
    if (mk && !(t.markers||[]).includes(mk)) return false;
    if (su && suiteOf(t) !== su) return false;
    return !q || t._hay.includes(q);
  });
  const groups = {};
  keep.forEach(t => (groups[t.file] ||= []).push(t));
  document.getElementById('tests').innerHTML = keep.length ? Object.entries(groups).map(([file, ts]) => {
    const ok = ts.filter(t => !failedLike(t.status)).length, ko = ts.length - ok;
    const time = ts.reduce((n,t) => n + t.duration_ms, 0);
    // A flow file is a suite: its # title leads and the path is secondary.
    // Files without a title (or non-flow tests) keep the path as the label.
    const ftitle = (ts.find(t => t.file_title) || {}).file_title;
    const flabel = ftitle
      ? `<span class="fp">${esc(ftitle)}<span class="fpsub">${esc(file)}</span></span>`
      : `<span class="fp path">${esc(file)}</span>`;
    return `<div class="filegrp">
      <div class="filehead" onclick="this.parentElement.classList.toggle('closed')">
        <span class="arrow">▼</span>${flabel}
        <span class="sum"><span class="ok">✓ ${ok}</span>${ko ? `<span class="ko">✕ ${ko}</span>` : ''}<span class="t">${fmtMs(time)}</span></span>
      </div>
      <div class="trows">${ts.map(t => `
        <div class="trow" onclick="openTest(${t._i})">
          <span class="sdot ${effStatus(t)}"></span>
          <span class="tt">${titleOf(t)}${t.title && t.title !== t.name ? `<span class="fn">${esc(t.name)}</span>` : ''}</span>
          <span class="right">${chips(t)}<span class="dur">${fmtMs(t.duration_ms)}</span></span>
        </div>`).join('')}</div>
    </div>`;
  }).join('') : '<div class="empty">No tests match the current filters.</div>';
}
renderTests();

/* ── drawer ── */
function stepTree(steps){
  // flat depth-annotated list → nested tree
  const root = {children: []}, stack = [root];
  steps.forEach(s => {
    while (stack.length - 1 > s.depth) stack.pop();
    const node = {step: s, children: []};
    stack[stack.length - 1].children.push(node);
    stack.push(node);
  });
  return root.children;
}
function shotThumb(s){
  // attachment is a report-relative path; escape it like any other attribute value
  return s.attachment
    ? `<a href="${esc(s.attachment)}" target="_blank"><img class="sthumb" src="${esc(s.attachment)}" alt="Screenshot at failing step" loading="lazy"></a>`
    : '';
}
function failedStep(t){
  // The exception propagates up through nested steps, marking each ancestor
  // failed too — the last failed step is the deepest one: the failure site.
  const failed = (t.steps || []).filter(s => s.status === 'failed');
  return failed.length ? failed[failed.length - 1] : null;
}
function stepErr(t, n, errStep){
  const s = n.step;
  // Ancestors carry a copy of the child's error — render only at the site.
  if (s.status !== 'failed' || n.children.some(c => c.step.status === 'failed')) return '';
  if (t.error && s === errStep) return errCard(t.error, true);
  return s.error ? `<pre class="codebox serrbox">${esc(s.error)}</pre>` : '';
}
function stepIcon(status){
  return status === 'failed' ? '✕' : status === 'skipped' ? '»' : '✓';
}
function stepName(s){
  // Flow steps carry the action verb and its (secret-masked) argument text;
  // anything else (groups, legacy data) shows its raw name.
  const layer = s.layer > 1 ? `<span class="slayer" title="resolved by layer ${s.layer}">L${s.layer}</span>` : '';
  if (!s.action) return `<span class="sname">${esc(s.name)}</span>${layer}`;
  return `<span class="sname"><span class="sverb">${esc(s.action)}</span>${s.args ? `<span class="sargs">${esc(s.args)}</span>` : ''}</span>${layer}`;
}
function stepNodes(t, nodes, nested, errStep){
  return nodes.map((n, i) => {
    const s = n.step;
    const label = `<span class="slabel">Step ${i + 1}</span>`;
    const dur = `<span class="sdur">${fmtMs(s.duration_ms)}</span>`;
    const err = stepErr(t, n, errStep);
    if (n.children.length){
      return `<div class="sgroup ${s.status}">
        <div class="sghead" onclick="this.parentElement.classList.toggle('closed')">
          <span class="sicon grp ${s.status}">${stepIcon(s.status)}</span><span class="chev">▼</span>
          ${label}<span class="sgname">${esc(s.name)}</span>${dur}
        </div>
        <div class="sgbody">${stepNodes(t, n.children, true, errStep)}${err}</div>
      </div>`;
    }
    return `<div class="srow ${s.status}">
      <span class="sicon ${s.status}">${stepIcon(s.status)}</span>
      <div class="smain">${label}${nested ? '<span class="hook">↳</span>' : ''}${stepName(s)}${dur}${shotThumb(s)}${err}</div>
    </div>`;
  }).join('');
}
function stepsHtml(t){
  if (!(t.steps||[]).length) return '<div class="empty" style="padding:14px 0">No steps recorded.</div>';
  return stepNodes(t, stepTree(t.steps), false, failedStep(t));
}
function errCard(e, instep){
  // headline without the class prefix when the kind chip already shows it
  let headline = (e.message || '').split('\n')[0];
  if (e.kind && headline.startsWith(e.kind + ':')) headline = headline.slice(e.kind.length + 1).trim();
  return `<div class="errcard${instep ? ' instep' : ''}">
    <div class="errhead">${e.kind ? `<span class="ekind">${esc(e.kind)}</span>` : ''}<span class="msg">${esc(headline)}</span></div>
    ${e.traceback ? `<details class="fullout"><summary>Full output</summary><pre class="codebox tall">${esc(e.traceback)}</pre></details>` : ''}
  </div>`;
}
function errorHtml(t){
  // Failures inside a step render at the step itself; this section only
  // covers failures outside any step (fixture setup, bare asserts).
  if (!t.error || failedStep(t)) return '';
  return `<div class="sec"><h3>Error</h3>${errCard(t.error, false)}</div>`;
}
function healHtml(t){
  const h = t.healings || [];
  if (!h.length) return '';
  return `<div class="sec"><h3>🩹 Healed locators</h3><div class="healbox">
    Resolved by the fallback chain at runtime — update the page object.
    <ul>${h.map(e => `<li><span class="layer">L${e.layer}</span>'${esc(e.description)}'
      <br>healed by <code>${esc(e.healed_by)}</code> → <code>${esc(e.resolved)}</code></li>`).join('')}</ul></div></div>`;
}

/* ── console & network row renderers (shared by drawer + execution tabs) ── */
function groupConsole(logs){
  const map = new Map(), out = [];
  logs.forEach(c => {
    const k = c.level + ' ' + c.text + ' ' + (c.location || '');
    if (map.has(k)) map.get(k).count++;
    else { const g = {...c, count: 1}; map.set(k, g); out.push(g); }
  });
  return out;
}
function conRowHtml(c, t0, ti){
  const lvl = lvlOf(c);
  const lines = String(c.text ?? '').split('\n');
  const main = `<span class="ctime">${relTime(c.ts, t0)}</span><span class="clvl ${lvl}">${esc(c.level)}</span>
    <span class="ctext">${esc(lines[0])}${c.count > 1 ? `<span class="cxn">×${c.count}</span>` : ''}</span>
    ${ti != null ? `<span class="cfrom" onclick="event.preventDefault();openTest(${ti})">${titleOf(T[ti])}</span>` : ''}
    ${c.step ? `<span class="cstep" title="active step">${esc(c.step)}</span>` : ''}
    ${c.location ? `<span class="cloc" title="${esc(c.location)}">${esc(c.location.replace(/^https?:\/\/[^/]*/, ''))}</span>` : ''}`;
  return lines.length > 1
    ? `<details class="crow ${lvl}"><summary>${main}<span class="nchev">▸</span></summary><pre class="codebox">${esc(lines.slice(1).join('\n'))}</pre></details>`
    : `<div class="crow ${lvl}">${main}</div>`;
}
function curlOf(n){
  const q = s => `'${String(s).replace(/'/g, "'\\''")}'`;
  const h = Object.entries(n.request_headers || {}).map(([k, v]) => ` -H ${q(k + ': ' + v)}`).join('');
  return `curl -X ${n.method} ${q(n.url)}${h}${n.post_data ? ` --data ${q(n.post_data)}` : ''}`;
}
// Entries behind the rendered rows of each network list, keyed by view, so
// the drawer and the execution-level list never clobber each other's copy
// buttons (both can be on screen once the drawer has been opened and closed).
const NET_CTX = {};
window.copyIdx = (kind, ctx, i, btn) => {
  const n = (NET_CTX[ctx] || [])[i]; if (!n) return;
  const txt = kind === 'curl' ? curlOf(n) : n.url;
  try { navigator.clipboard.writeText(txt).then(() => { btn.textContent = '✓'; setTimeout(() => btn.textContent = kind === 'curl' ? 'Copy cURL' : 'Copy URL', 900); }, () => {}); } catch(e) {}
};
const fmtKv = o => Object.entries(o || {}).map(([k, v]) => `${k}: ${v}`).join('\n');
function netRowHtml(n, t0, ctx, idx, ti){
  let host = '', path = n.url;
  try { const u = new URL(n.url); host = u.host; path = u.pathname + u.search; } catch(e) {}
  const status = n.status != null
    ? `<span class="nstat ${n.status >= 400 ? 'sbad' : n.status >= 300 ? 'swarn' : 'sok'}">${n.status}</span>`
    : `<span class="nstat ${n.method === 'WS' ? 'swarn' : 'sbad'}">${n.method === 'WS' ? 'WS' : 'ERR'}</span>`;
  const slow = (n.duration_ms || 0) > 2000;
  const summary = `<span class="nmethod">${esc(n.method)}</span>${status}
    <span class="nurl" title="${esc(n.url)}"><span class="nhost">${esc(host)}</span>${esc(path)}${n.failure ? ` <span class="nfailure">${esc(n.failure)}</span>` : ''}</span>
    ${ti != null ? `<span class="cfrom" onclick="event.preventDefault();openTest(${ti})">${titleOf(T[ti])}</span>` : ''}
    <span class="ntime">${relTime(n.ts, t0)}</span>
    <span class="ndur${slow ? ' slow' : ''}"${slow ? ' title="slow request (>2s)"' : ''}>${n.duration_ms != null ? fmtMs(n.duration_ms) : ''}</span>
    <span class="nsize">${fmtBytes(n.size)}</span>
    <span class="ntype"${n.resource_type ? ` title="${esc(n.resource_type)}"` : ''}>${esc(n.resource_type || '')}</span>`;
  let qp = '';
  try { qp = [...new URL(n.url).searchParams].map(([k, v]) => `${k} = ${v}`).join('\n'); } catch(e) {}
  const detail = `<div class="ndetail">
    <div class="nbtns">
      <button class="minibtn" onclick="copyIdx('curl','${ctx}',${idx},this)">Copy cURL</button>
      <button class="minibtn" onclick="copyIdx('url','${ctx}',${idx},this)">Copy URL</button>
      ${n.step ? `<span class="cstep" title="active step">during: ${esc(n.step)}</span>` : ''}
    </div>
    ${qp ? `<div class="sublbl">Query parameters</div><pre class="codebox">${esc(qp)}</pre>` : ''}
    ${n.request_headers ? `<div class="sublbl">Request headers</div><pre class="codebox">${esc(fmtKv(n.request_headers))}</pre>` : ''}
    ${n.post_data ? `<div class="sublbl">Request body</div><pre class="codebox">${esc(n.post_data)}</pre>` : ''}
    ${n.response_headers ? `<div class="sublbl">Response headers</div><pre class="codebox">${esc(fmtKv(n.response_headers))}</pre>` : ''}
    ${n.body ? `<div class="sublbl">Response body</div><pre class="codebox netbody">${esc(n.body)}</pre>` : ''}
  </div>`;
  return `<details class="netrow ${n.ok ? 'ok' : 'bad'}"><summary>${summary}<span class="nchev">▸</span></summary>${detail}</details>`;
}
const netHeadHtml = withTest =>
  `<div class="nethead"><span>Method</span><span>Status</span><span>Name</span>${withTest ? '<span>Test</span>' : ''}<span class="num">Offset</span><span class="num">Duration</span><span class="num">Size</span><span>Type</span><span></span></div>`;
function netSummaryHtml(net){
  // One pass; Math.max(...arr) would overflow the call stack on a large
  // execution-level list (hundreds of tests × up to 1500 requests).
  let failed = 0, bytes = 0, slowest = null, first = null, last = null;
  for (const n of net){
    if (!n.ok) failed++;
    bytes += n.size || 0;
    if (n.duration_ms != null && (slowest == null || n.duration_ms > slowest)) slowest = n.duration_ms;
    if (n.ts != null){
      const end = n.ts + (n.duration_ms || 0);
      if (first == null || n.ts < first) first = n.ts;
      if (last == null || end > last) last = end;
    }
  }
  return `<div class="netsum">
    <span><b>${net.length}</b> requests</span>
    <span class="${failed ? 'ko' : ''}"><b>${failed}</b> failed</span>
    <span><b>${fmtBytes(bytes) || '0 B'}</b> transferred</span>
    ${slowest != null ? `<span>slowest <b>${fmtMs(slowest)}</b></span>` : ''}
    ${first != null ? `<span>span <b>${fmtMs(last - first)}</b></span>` : ''}</div>`;
}

/* ── one console view and one network view, used by the drawer and the
   execution-level tabs. Items are {e, t0, i?}: the entry, the owning test's
   t0 for offsets, and (aggregated views only) the test index. ── */
const chipHtml = (cls, key, label, n, on) =>
  `<span class="fchip ${cls}${on ? ' on' : ''}" data-k="${key}">${label}<span class="n">${n}</span></span>`;
function wireChips(host, cls, onPick, toggle){
  host.querySelectorAll('.' + cls).forEach(ch => ch.onclick = () => {
    const picked = onPick(ch.dataset.k, toggle);
    host.querySelectorAll('.' + cls).forEach(x => x.classList.toggle('on', x.dataset.k === picked));
  });
}
function showMore(list, id, hidden, onClick){
  if (hidden <= 0) return;
  list.insertAdjacentHTML('beforeend', `<button class="showmore" id="${id}">Show more (${hidden} hidden)</button>`);
  document.getElementById(id).onclick = onClick;
}
function consoleView({items, list, chipsHost, search, group, pageSize, cls}){
  // group: collapse identical messages (drawer); aggregated view keeps every row
  const t0 = items.length ? items[0].t0 : null;
  const rows = group ? groupConsole(items.map(x => x.e)).map(e => ({e, t0})) : items;
  rows.forEach(x => { x.q = (x.e.text + ' ' + (x.e.location || '')).toLowerCase(); });
  const tally = {};
  rows.forEach(x => { const l = lvlOf(x.e); tally[l] = (tally[l] || 0) + 1; });
  chipsHost.innerHTML = CON_LEVELS.map(([l, lbl]) => chipHtml(cls, l, lbl, tally[l] || 0, false)).join('');
  let lvl = '', q = '', shown = pageSize;
  const render = () => {
    const keep = rows.filter(x => (!lvl || lvlOf(x.e) === lvl) && (!q || x.q.includes(q)));
    list.innerHTML = keep.slice(0, shown).map(x => conRowHtml(x.e, x.t0, x.i)).join('') ||
      '<div class="empty" style="padding:10px 0">No matching messages.</div>';
    showMore(list, list.id + '-more', keep.length - shown, () => { shown += 2 * pageSize; render(); });
  };
  wireChips(chipsHost, cls, k => { lvl = lvl === k ? '' : k; render(); return lvl; });
  search.addEventListener('input', debounce(e => { q = e.target.value.toLowerCase(); shown = pageSize; render(); }));
  render();
}
function networkView({items, list, chipsHost, search, sortSel, ctx, pageSize, withTest, cls}){
  items.forEach(x => { x.q = x.e.url.toLowerCase(); x.c = catOf(x.e); });
  const tally = {'': items.length, bad: 0};
  items.forEach(x => { if (!x.e.ok) tally.bad++; tally[x.c] = (tally[x.c] || 0) + 1; });
  chipsHost.innerHTML = NET_CATS.filter(([c]) => tally[c]).map(([c, lbl]) => chipHtml(cls, c, lbl, tally[c], c === '')).join('');
  let cat = '', q = '', sort = 'time', shown = pageSize;
  const render = () => {
    const keep = items.filter(x => (cat === '' || (cat === 'bad' ? !x.e.ok : x.c === cat)) && (!q || x.q.includes(q)));
    if (sort === 'dur') keep.sort((a, b) => (b.e.duration_ms || 0) - (a.e.duration_ms || 0));
    else if (sort === 'status') keep.sort((a, b) => (b.e.status || 999) - (a.e.status || 999));
    else if (sort === 'size') keep.sort((a, b) => (b.e.size || 0) - (a.e.size || 0));
    NET_CTX[ctx] = keep.map(x => x.e);
    const rows = keep.slice(0, shown).map((x, i) => netRowHtml(x.e, x.t0, ctx, i, withTest ? x.i : undefined)).join('');
    list.innerHTML = rows ? netHeadHtml(withTest) + rows : '<div class="empty" style="padding:10px 0">No matching requests.</div>';
    showMore(list, list.id + '-more', keep.length - shown, () => { shown += 2 * pageSize; render(); });
  };
  wireChips(chipsHost, cls, k => { cat = k; render(); return cat; });
  search.addEventListener('input', debounce(e => { q = e.target.value.toLowerCase(); shown = pageSize; render(); }));
  if (sortSel) sortSel.addEventListener('change', e => { sort = e.target.value; render(); });
  render();
}

/* ── drawer panes ── */
function consolePaneHtml(t){
  if (!(t.console || []).length && !t.console_dropped)
    return '<div class="empty" style="padding:14px 0">No console messages captured.</div>';
  return `<div class="minibar"><input class="minisearch" id="consearch" placeholder="Search messages…"><span id="conchips"></span></div>
    <div class="loglist" id="conlist"></div>
    ${t.console_dropped ? `<div class="dropnote">${t.console_dropped} more entries were not captured (flow limit).</div>` : ''}`;
}
function netPaneHtml(t){
  const net = t.network || [];
  if (!net.length && !t.network_dropped)
    return '<div class="empty" style="padding:14px 0">No network activity recorded.</div>';
  return `${netSummaryHtml(net)}
    <div class="minibar"><input class="minisearch" id="netsearch" placeholder="Search URL or endpoint…">
      <select class="minisel" id="netsort"><option value="time">By time</option><option value="dur">By duration</option><option value="status">By status</option><option value="size">By size</option></select>
      <span id="netchips"></span></div>
    <div class="netlist" id="netlist"></div>
    ${t.network_dropped ? `<div class="dropnote">${t.network_dropped} more requests were not captured (flow limit).</div>` : ''}`;
}
function wireDrawerPanes(t){
  const $ = id => document.getElementById(id);
  if ($('conlist')) consoleView({
    items: (t.console || []).map(e => ({e, t0: t.t0})), list: $('conlist'), chipsHost: $('conchips'),
    search: $('consearch'), group: true, pageSize: 200, cls: 'cf'});
  if ($('netlist')) networkView({
    items: (t.network || []).map(e => ({e, t0: t.t0})), list: $('netlist'), chipsHost: $('netchips'),
    search: $('netsearch'), sortSel: $('netsort'), ctx: 'drawer', pageSize: 100, withTest: false, cls: 'nf'});
}
function relatedHtml(t){
  if (!failedLike(t.status)) return '';
  const fs = failedStep(t);
  const from = fs && fs.ts != null ? fs.ts - 2000 :
    t.t0 != null ? t.t0 + Math.max(t.duration_ms - 10000, 0) : null;
  if (from == null) return '';
  const end = t.t0 != null ? t.t0 + t.duration_ms + 2000 : Infinity;
  const cons = (t.console || []).filter(c => lvlOf(c) === 'error' && c.ts >= from && c.ts <= end).slice(-5);
  const net = (t.network || []).filter(n => !n.ok && n.ts >= from && n.ts <= end).slice(-5);
  if (!cons.length && !net.length) return '';
  // failed requests reuse the console row shape: level "net", text = request + outcome
  const netRows = net.map(n => ({level: 'error', ts: n.ts,
    text: `${n.method} ${n.url} — ${n.failure ? n.failure : 'HTTP ' + n.status}`}));
  return `<div class="sec"><h3>Likely related activity</h3><div class="relbox">
    <div class="relnote">Browser activity near the failure — troubleshooting hints, not a confirmed root cause.</div>
    ${cons.map(c => conRowHtml(c, t.t0)).join('')}
    ${netRows.map(c => conRowHtml(c, t.t0).replace('>error<', '>net<')).join('')}
  </div></div>`;
}
let lastDtab = 'd-con';
let drawerSeq = 0;   // ignore shard arrivals for a test the user has left
function openTest(i){
  const t = T[i];
  const counts = t.counts;
  const loading = '<div class="empty" style="padding:14px 0">Loading detail data…</div>';
  const drawer = document.getElementById('drawer');
  drawer.innerHTML = `
    <div class="dhead">
      <div class="dtitle"><span class="badge ${effStatus(t)}">${effStatus(t)}</span><h2 id="dtitle">${titleOf(t)}</h2>
        <button class="iconbtn" onclick="closeDrawer()" aria-label="Close details">✕</button></div>
      <div class="dmeta">
        ${t.file_title ? `<div><span>suite </span><b>${esc(t.file_title)}</b></div>` : ''}
        <div><span>file </span><b>${esc(t.file)}</b></div>
        <div><span>test </span><b>${esc(t.name)}</b></div>
        <div><span>duration </span><b>${fmtMs(t.duration_ms)}</b></div>
        <div><span>started </span><b>${t.started_at ? new Date(t.started_at).toLocaleTimeString() : '—'}</b></div>
        ${t.retries ? `<div><span>reruns </span><b>${t.retries}</b></div>` : ''}
        ${(t.markers||[]).length ? `<div><span>markers </span><b>${t.markers.map(esc).join(', ')}</b></div>` : ''}
      </div>
    </div>
    <div class="dbody">
      ${errorHtml(t)}
      <div id="d-rel">${hasDetail(t) ? relatedHtml(t) : ''}</div>
      ${healHtml(t)}
      <div class="sec"><h3>Steps</h3>${stepsHtml(t)}</div>
      <div class="sec">
        <div class="dtabs" role="tablist">
          <span class="dtab" role="tab" tabindex="0" data-t="d-con">Console (${counts.console})</span>
          <span class="dtab" role="tab" tabindex="0" data-t="d-net">Network (${counts.network})</span>
        </div>
        <div class="dpane" id="d-con">${hasDetail(t) ? consolePaneHtml(t) : loading}</div>
        <div class="dpane" id="d-net">${hasDetail(t) ? netPaneHtml(t) : loading}</div>
      </div>
    </div>`;
  const tabs = [...drawer.querySelectorAll('.dtab')];
  const activate = tab => {
    tabs.forEach(x => { x.classList.toggle('active', x === tab); x.setAttribute('aria-selected', x === tab); });
    drawer.querySelectorAll('.dpane').forEach(x => x.classList.toggle('active', x.id === tab.dataset.t));
    lastDtab = tab.dataset.t;   // keep the selected tab across tests
  };
  activate(tabs.find(x => x.dataset.t === lastDtab) || tabs[0]);
  tabs.forEach(tab => {
    tab.onclick = () => activate(tab);
    tab.onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); activate(tab); } };
  });
  if (hasDetail(t)) wireDrawerPanes(t);
  else {
    const seq = ++drawerSeq;
    loadDetail(i).then(
      () => {
        if (seq !== drawerSeq) return;
        document.getElementById('d-rel').innerHTML = relatedHtml(t);
        document.getElementById('d-con').innerHTML = consolePaneHtml(t);
        document.getElementById('d-net').innerHTML = netPaneHtml(t);
        wireDrawerPanes(t);
      },
      () => {
        if (seq !== drawerSeq) return;
        const miss = '<div class="empty" style="padding:14px 0">Detail data unavailable — this test\'s shard is missing from assets/data/.</div>';
        document.getElementById('d-con').innerHTML = miss;
        document.getElementById('d-net').innerHTML = miss;
      });
  }
  drawer.classList.add('show');
  document.getElementById('overlay').classList.add('show');
  drawer.querySelector('.iconbtn').focus();
}
function closeDrawer(){
  document.getElementById('drawer').classList.remove('show');
  document.getElementById('overlay').classList.remove('show');
}
document.getElementById('overlay').onclick = closeDrawer;

/* ── timeline ── */
(function timeline(){
  const withT = byStart.filter(i => T[i]._startMs != null);
  if (!withT.length){ document.getElementById('lanes').innerHTML = '<div class="empty">No timing data.</div>'; return; }
  const start = i => T[i]._startMs;
  const end = i => start(i) + T[i].duration_ms;
  let t0 = Infinity, t1 = -Infinity;
  withT.forEach(i => { t0 = Math.min(t0, start(i)); t1 = Math.max(t1, end(i)); });
  const span = Math.max(t1 - t0, 1);
  const lanes = [];  // greedy interval assignment ≈ xdist workers
  withT.forEach(i => {
    let L = lanes.find(l => l.end <= start(i) + 1);
    if (!L){ L = {end: 0, items: []}; lanes.push(L); }
    L.items.push(i); L.end = end(i);
  });
  document.getElementById('wallclock').textContent = 'wall clock ' + fmtMs(span);
  document.getElementById('lanes').innerHTML = lanes.map((l, n) => `
    <div class="lane"><span class="lb">w${n}</span><div class="track">${l.items.map(i => `
      <div class="tbar ${effStatus(T[i])}" onclick="openTest(${i})"
        title="${titleOf(T[i])} · ${fmtMs(T[i].duration_ms)}"
        style="left:${(start(i)-t0)/span*100}%;width:${Math.max(T[i].duration_ms/span*100, .4)}%"></div>`).join('')}</div></div>`).join('');
  document.getElementById('ticks').innerHTML =
    [0,.25,.5,.75,1].map(f => `<span>${fmtMs(span*f)}</span>`).join('');
})();

/* ── execution-level console & network (secondary, aggregated) ──
   Tab badges come from the precomputed counts; the entries themselves load
   on first open of either tab (all detail shards, rendered together). */
(function globalBadges(){
  let c = 0, n = 0;
  T.forEach(t => { c += t.counts.console; n += t.counts.network; });
  document.getElementById('ccount').textContent = c;
  document.getElementById('ncount').textContent = n;
  document.getElementById('gconlist').innerHTML = '<div class="empty">Loading detail data…</div>';
  document.getElementById('gnetlist').innerHTML = '<div class="empty">Loading detail data…</div>';
})();
let globalReady = null;
function ensureGlobalViews(){
  if (globalReady) return;
  globalReady = Promise.all(T.map((t, i) => loadDetail(i).then(() => 0, () => 1)))
    .then(fails => initGlobalViews(fails.reduce((a, b) => a + b, 0)));
}
function initGlobalViews(missing){
  const $ = id => document.getElementById(id);
  if (missing){
    const note = `<div class="dropnote">Detail for ${missing} test(s) could not be loaded (missing shard files).</div>`;
    $('gconlist').insertAdjacentHTML('beforebegin', note);
    $('gnetlist').insertAdjacentHTML('beforebegin', note);
  }
  const bySeq = (a, b) => (a.e.ts ?? 0) - (b.e.ts ?? 0) || (a.e.seq ?? 0) - (b.e.seq ?? 0);
  const CON = T.flatMap((t, i) => (t.console || []).map(e => ({e, i, t0: t.t0}))).sort(bySeq);
  const NET = T.flatMap((t, i) => (t.network || []).map(e => ({e, i, t0: t.t0}))).sort(bySeq);
  consoleView({items: CON, list: $('gconlist'), chipsHost: $('gconchips'), search: $('gconsearch'),
               group: false, pageSize: 200, cls: 'gcf'});
  $('gnetsum').innerHTML = netSummaryHtml(NET.map(x => x.e));
  networkView({items: NET, list: $('gnetlist'), chipsHost: $('gnetchips'), search: $('gnetsearch'),
               sortSel: null, ctx: 'global', pageSize: 150, withTest: true, cls: 'gnf'});
}
