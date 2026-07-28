const DATA = window.__WEBAGENT_DATA__;
const ART = p => p;  // artifact paths are relative to the report root
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
function catOf(n){
  const rt = n.resource_type || '';
  return rt === 'xhr' || rt === 'fetch' ? 'xhr' : rt === 'document' ? 'doc' :
    rt === 'script' ? 'js' : rt === 'stylesheet' ? 'css' :
    rt === 'image' || rt === 'media' || rt === 'font' ? 'img' : 'other';
}
const T = DATA.tests, TOT = DATA.totals, ENV = DATA.environment;
const flakyCount = T.filter(isFlaky).length;
const healCount = T.reduce((n,t) => n + (t.healings||[]).length, 0);
const byStart = T.map((t,i)=>i).sort((a,b) => (T[a].started_at||'').localeCompare(T[b].started_at||''));

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
document.getElementById('hdate').textContent = new Date(DATA.created_at).toLocaleString();
document.getElementById('hrunid').textContent = DATA.run_id;
document.getElementById('htrigger').textContent = triggeredBy;
document.getElementById('hbrowser').textContent = cap(ENV.browser) + (ENV.headless ? ' (headless)' : '');
document.getElementById('copyrun').onclick = function(){
  const done = () => { this.textContent = '✓'; setTimeout(() => this.textContent = '⧉', 1200); };
  try { navigator.clipboard.writeText(DATA.run_id).then(done.bind(this), () => {}); } catch(e){}
};
document.getElementById('tcount').textContent = TOT.total;
document.getElementById('pulse').innerHTML = byStart.map(i =>
  `<div class="px ${effStatus(T[i])}" title="${esc(T[i].title || T[i].name)} · ${effStatus(T[i])}" onclick="openTest(${i})"></div>`).join('');
document.querySelectorAll('.tabs button').forEach(b => b.onclick = () => showTab(b.dataset.tab));
function showTab(name){
  document.querySelectorAll('.tabs button').forEach(b => b.setAttribute('aria-selected', b.dataset.tab === name));
  document.querySelectorAll('.pane').forEach(p => p.classList.toggle('active', p.id === 'pane-' + name));
}
document.getElementById('foot').textContent =
  `Generated on ${new Date(DATA.created_at).toLocaleString()} · Web Agent ${ENV.framework}`;

/* ── overview ── */
if (DATA.ai_summary){
  document.getElementById('aibanner').style.display = 'block';
  document.getElementById('aisummary').textContent = DATA.ai_summary;
}
document.getElementById('cards').innerHTML = [
  ['Total tests', TOT.total, '', '▦'], ['Passed', TOT.passed, 'pass', '✓'],
  ['Failed', failing, failing ? 'fail' : '', '✕'], ['Flaky', flakyCount, flakyCount ? 'flaky' : '', '↻'],
  ['Skipped', TOT.skipped, 'skip', '»'], ['Pass rate', TOT.pass_rate + '%', '', '%'],
  ['Duration', fmtMs(TOT.duration_ms), '', '◷']
].map(([l,v,c,ico]) => `<div class="card ${c}"><div class="ico">${ico}</div><div><div class="lbl">${l}</div><div class="num">${v}</div></div></div>`).join('');

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
  const durs = T.map(t => t.duration_ms), max = Math.max(...durs, 1);
  const N = 12, buckets = Array(N).fill(0);
  durs.forEach(d => buckets[Math.min(N-1, Math.floor(d/max*N))]++);
  const bmax = Math.max(...buckets, 1);
  document.getElementById('histo').innerHTML =
    `<div class="histo">${buckets.map(b => `<div style="height:${b/bmax*100}%" title="${b} tests"></div>`).join('')}</div>
     <div class="axis"><span>0</span><span>${fmtMs(max)}</span></div>`;
})();

(function healsum(){
  const healed = T.filter(t => (t.healings||[]).length);
  document.getElementById('healsum').innerHTML = healed.length
    ? healed.map(t => {
        const i = T.indexOf(t);
        return `<div class="rowline"><span class="sdot ${effStatus(t)}"></span>
          <span class="nm" onclick="openTest(${i})">${esc(t.title || t.name)}</span>
          <span class="val" style="color:var(--skip)">🩹 ${t.healings.length} L${Math.max(...t.healings.map(h=>h.layer))}</span></div>`;
      }).join('') + `<div class="axis" style="margin-top:10px"><span>${healCount} heal${healCount===1?'':'s'} — update these page objects</span></div>`
    : `<div class="estate"><div class="ecirc">✓</div>
       <div class="ehead">No locators needed healing 🎉</div>
       <div class="esub">Great job! No unstable locators detected.</div></div>`;
})();

(function failures(){
  const fails = T.filter(t => failedLike(t.status));
  document.getElementById('failures').innerHTML = fails.length
    ? fails.map(t => `<div class="failcard" onclick="openTest(${T.indexOf(t)})">
        <div class="fname">${esc(t.title || t.name)} ${(t.markers||[]).map(m=>`<span class="chiplet">${esc(m)}</span>`).join(' ')}</div>
        <div class="ferr">${esc((t.error && t.error.message || '').split('\n')[0])}</div>
        <div class="ffile">${esc(t.file)}</div></div>`).join('')
    : `<div class="estate"><div class="ecirc">🛡</div>
       <div class="ehead">No failures 🎉</div>
       <div class="esub">All tests passed successfully.</div></div>`;
})();

(function slowest(){
  const top = [...T].sort((a,b) => b.duration_ms - a.duration_ms).slice(0, 7);
  const max = Math.max(...top.map(t => t.duration_ms), 1);
  document.getElementById('slowest').innerHTML = top.map(t => `
    <div class="rowline" style="border-bottom:none;padding-bottom:2px">
      <span class="nm" onclick="openTest(${T.indexOf(t)})">${esc(t.title || t.name)}</span>
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
document.getElementById('fchips').outerHTML = FILTERS.map(([s,c,n]) =>
  `<div class="fchip" data-f="${s}"><span class="sw" style="background:${c}"></span>${s[0].toUpperCase()+s.slice(1)}<span class="n">${n}</span></div>`).join('');
document.querySelectorAll('.fchip').forEach(ch => ch.onclick = () => {
  statusFilter = statusFilter === ch.dataset.f ? '' : ch.dataset.f;
  document.querySelectorAll('.fchip').forEach(x => x.classList.toggle('on', x.dataset.f === statusFilter));
  renderTests();
});
const markers = [...new Set(T.flatMap(t => t.markers || []))].sort();
document.getElementById('marker').innerHTML += markers.map(m => `<option>${esc(m)}</option>`).join('');
const suiteNames = [...new Set(T.map(suiteOf))].sort();
document.getElementById('suite').innerHTML += suiteNames.map(s => `<option>${esc(s)}</option>`).join('');
['search','marker','suite'].forEach(id => document.getElementById(id).addEventListener(id==='search'?'input':'change', renderTests));
document.addEventListener('keydown', e => {
  if (e.key === '/' && !e.target.matches('input,select')) { e.preventDefault(); showTab('tests'); document.getElementById('search').focus(); }
  if (e.key === 'Escape') closeDrawer();
});

function chips(t){
  const cerr = (t.console||[]).filter(c => lvlOf(c) === 'error').length;
  const cwarn = (t.console||[]).filter(c => lvlOf(c) === 'warning').length;
  const nbad = (t.network||[]).filter(n => !n.ok).length;
  return [
    cerr ? `<span class="chiplet cbad" title="console errors">⚠ ${cerr}</span>` : '',
    cwarn ? `<span class="chiplet cwarn" title="console warnings">⚠ ${cwarn}</span>` : '',
    nbad ? `<span class="chiplet cbad" title="failed requests">⇅ ${nbad}</span>` : '',
    t.retries ? `<span class="chiplet" style="color:var(--skip)" title="reruns">↻ ${t.retries}</span>` : '',
    (t.healings||[]).length ? `<span class="chiplet" style="color:var(--skip)" title="healed locators">🩹 ${t.healings.length}</span>` : '',
    t.ai ? '<span class="chiplet" style="color:var(--accent)">✦ AI</span>' : '',
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
    if (q){
      const hay = [t.title, t.name, t.file, t.error && t.error.message, ...(t.markers||[])].join(' ').toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
  const groups = {};
  keep.forEach(t => (groups[t.file] ||= []).push(t));
  document.getElementById('tests').innerHTML = keep.length ? Object.entries(groups).map(([file, ts]) => {
    const ok = ts.filter(t => !failedLike(t.status)).length, ko = ts.length - ok;
    const time = ts.reduce((n,t) => n + t.duration_ms, 0);
    return `<div class="filegrp">
      <div class="filehead" onclick="this.parentElement.classList.toggle('closed')">
        <span class="arrow">▼</span><span class="fp">${esc(file)}</span>
        <span class="sum"><span class="ok">✓ ${ok}</span>${ko ? `<span class="ko">✕ ${ko}</span>` : ''}<span class="t">${fmtMs(time)}</span></span>
      </div>
      <div class="trows">${ts.map(t => `
        <div class="trow" onclick="openTest(${T.indexOf(t)})">
          <span class="sdot ${effStatus(t)}"></span>
          <span class="tt">${esc(t.title || t.name)}${t.title && t.title !== t.name ? `<span class="fn">${esc(t.name)}</span>` : ''}</span>
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
  return s.attachment
    ? `<a href="${ART(s.attachment)}" target="_blank"><img class="sthumb" src="${ART(s.attachment)}" loading="lazy"></a>`
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
      <div class="smain">${label}${nested ? '<span class="hook">↳</span>' : ''}<span class="sname">${esc(s.name)}</span>${dur}${shotThumb(s)}${err}</div>
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
  const kv = [['Expected', e.expected], ['Actual', e.actual],
              ['Timeout', e.timeout_ms ? e.timeout_ms + 'ms' : null]]
    .filter(([,v]) => v != null && v !== '')
    .map(([k,v]) => `<div class="kv"><span class="k">${k}</span><code>${esc(v)}</code></div>`).join('');
  const log = (e.call_log || []).join('\n');
  return `<div class="errcard${instep ? ' instep' : ''}">
    <div class="errhead">${e.kind ? `<span class="ekind">${esc(e.kind)}</span>` : ''}<span class="msg">${esc(headline)}</span></div>
    ${kv ? `<div class="kvs">${kv}</div>` : ''}
    ${log ? `<div class="sublbl">Call log</div><pre class="codebox">${esc(log)}</pre>` : ''}
    ${e.traceback ? `<details class="fullout"><summary>Full output</summary><pre class="codebox tall">${esc(e.traceback)}</pre></details>` : ''}
  </div>`;
}
function errorHtml(t){
  // Failures inside a step render at the step itself; this section only
  // covers failures outside any step (fixture setup, bare asserts).
  if (!t.error || failedStep(t)) return '';
  return `<div class="sec"><h3>Error</h3>${errCard(t.error, false)}</div>`;
}
function aiHtml(a){
  if (!a) return '';
  const sugg = (a.locator_suggestions || []).map(s =>
    `<li>${s.original ? `<code>${esc(s.original)}</code> → ` : ''}<code>${esc(s.suggestion)}</code> — ${esc(s.reason)}</li>`).join('');
  const recs = (a.recommendations || []).map(r => `<li>${esc(r)}</li>`).join('');
  return `<div class="sec"><h3>✦ AI analysis</h3><div class="aibox">
    <span class="cat">${esc(a.category)}</span><span class="conf">confidence ${(a.confidence*100).toFixed(0)}% · ${esc(a.provider)}/${esc(a.model)}</span>
    <p>${esc(a.summary)}</p><p><b>Root cause:</b> ${esc(a.root_cause)}</p>
    ${sugg ? `<p><b>Locator suggestions:</b></p><ul>${sugg}</ul>` : ''}
    ${recs ? `<p><b>Recommendations:</b></p><ul>${recs}</ul>` : ''}</div></div>`;
}
function healHtml(t){
  const h = t.healings || [];
  if (!h.length) return '';
  return `<div class="sec"><h3>🩹 Healed locators</h3><div class="healbox">
    Resolved by the fallback chain at runtime — update the page object.
    <ul>${h.map(e => `<li><span class="layer">L${e.layer}</span>'${esc(e.description)}'
      ${e.original ? `<br>stale: <code>${esc(e.original)}</code>` : ''}
      <br>healed by <code>${esc(e.healed_by)}</code> → <code>${esc(e.resolved)}</code></li>`).join('')}</ul></div></div>`;
}
function artsHtml(t){
  const a = t.artifacts || {}, parts = [];
  if (a.screenshot) parts.push(`<div><a href="${ART(a.screenshot)}" target="_blank">📸 Screenshot</a><a href="${ART(a.screenshot)}" target="_blank"><img src="${ART(a.screenshot)}" loading="lazy"></a></div>`);
  (a.screenshots || []).forEach(s => {
    const label = s.split('/').pop().replace(/\.png$/, '').replace(/^\d+_/, '');
    parts.push(`<div><a href="${ART(s)}" target="_blank">📸 ${esc(label)}</a><a href="${ART(s)}" target="_blank"><img src="${ART(s)}" loading="lazy"></a></div>`);
  });
  if (a.video) parts.push(`<div><a href="${ART(a.video)}" target="_blank">🎬 Video</a><video src="${ART(a.video)}" controls preload="none"></video></div>`);
  return parts.length ? `<div class="arts">${parts.join('')}</div>` : '<div class="empty" style="padding:14px 0">No artifacts captured.</div>';
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
    ${ti != null ? `<span class="cfrom" onclick="openTest(${ti})">${esc(T[ti].title || T[ti].name)}</span>` : ''}
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
let NET_CTX = [];   // entries behind the currently rendered network rows
window.copyIdx = (kind, i, btn) => {
  const n = NET_CTX[i]; if (!n) return;
  const txt = kind === 'curl' ? curlOf(n) : n.url;
  try { navigator.clipboard.writeText(txt).then(() => { btn.textContent = '✓'; setTimeout(() => btn.textContent = kind === 'curl' ? 'Copy cURL' : 'Copy URL', 900); }, () => {}); } catch(e) {}
};
const fmtKv = o => Object.entries(o || {}).map(([k, v]) => `${k}: ${v}`).join('\n');
function netRowHtml(n, t0, idx, ti){
  let host = '', path = n.url;
  try { const u = new URL(n.url); host = u.host; path = u.pathname + u.search; } catch(e) {}
  const status = n.status != null
    ? `<span class="nstat ${n.status >= 400 ? 'sbad' : n.status >= 300 ? 'swarn' : 'sok'}">${n.status}</span>`
    : `<span class="nstat ${n.method === 'WS' ? 'swarn' : 'sbad'}">${n.method === 'WS' ? 'WS' : 'ERR'}</span>`;
  const slow = (n.duration_ms || 0) > 2000;
  const summary = `<span class="nmethod">${esc(n.method)}</span>${status}
    <span class="nurl" title="${esc(n.url)}"><span class="nhost">${esc(host)}</span>${esc(path)}</span>
    ${ti != null ? `<span class="cfrom" onclick="event.preventDefault();openTest(${ti})">${esc(T[ti].title || T[ti].name)}</span>` : ''}
    ${n.failure ? `<span class="nfailure">${esc(n.failure)}</span>` : ''}
    <span class="ntime">${relTime(n.ts, t0)}</span>
    <span class="ndur${slow ? ' slow' : ''}"${slow ? ' title="slow request (>2s)"' : ''}>${n.duration_ms != null ? fmtMs(n.duration_ms) : ''}</span>
    <span class="nsize">${fmtBytes(n.size)}</span>
    ${n.resource_type ? `<span class="ntype">${esc(n.resource_type)}</span>` : ''}`;
  let qp = '';
  try { qp = [...new URL(n.url).searchParams].map(([k, v]) => `${k} = ${v}`).join('\n'); } catch(e) {}
  const detail = `<div class="ndetail">
    <div class="nbtns">
      <button class="minibtn" onclick="copyIdx('curl',${idx},this)">Copy cURL</button>
      <button class="minibtn" onclick="copyIdx('url',${idx},this)">Copy URL</button>
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
function netSummaryHtml(net){
  const failed = net.filter(n => !n.ok).length;
  const bytes = net.reduce((s, n) => s + (n.size || 0), 0);
  const withD = net.filter(n => n.duration_ms != null);
  const slowest = withD.length ? Math.max(...withD.map(n => n.duration_ms)) : null;
  const withT = net.filter(n => n.ts != null);
  const span = withT.length ? Math.max(...withT.map(n => n.ts + (n.duration_ms || 0))) - Math.min(...withT.map(n => n.ts)) : null;
  return `<div class="netsum">
    <span><b>${net.length}</b> requests</span>
    <span class="${failed ? 'ko' : ''}"><b>${failed}</b> failed</span>
    <span><b>${fmtBytes(bytes) || '0 B'}</b> transferred</span>
    ${slowest != null ? `<span>slowest <b>${fmtMs(slowest)}</b></span>` : ''}
    ${span != null ? `<span>span <b>${fmtMs(span)}</b></span>` : ''}</div>`;
}

/* ── drawer panes ── */
function consolePaneHtml(t){
  const logs = t.console || [];
  if (!logs.length && !t.console_dropped)
    return '<div class="empty" style="padding:14px 0">No console messages captured.</div>';
  const n = l => logs.filter(c => lvlOf(c) === l).length;
  const chips = [['error','Errors'], ['warning','Warnings'], ['info','Info'], ['debug','Debug']]
    .map(([l, lbl]) => `<span class="fchip cf" data-cf="${l}">${lbl}<span class="n">${n(l)}</span></span>`).join('');
  return `<div class="minibar"><input class="minisearch" id="consearch" placeholder="Search messages…">${chips}</div>
    <div class="loglist" id="conlist"></div>
    ${t.console_dropped ? `<div class="dropnote">${t.console_dropped} more entries were not captured (flow limit).</div>` : ''}`;
}
function wireConsolePane(t){
  const list = document.getElementById('conlist');
  if (!list) return;
  const groups = groupConsole(t.console || []);
  let lvl = '', q = '';
  const render = () => {
    const keep = groups.filter(c => (!lvl || lvlOf(c) === lvl) &&
      (!q || (c.text + ' ' + (c.location || '')).toLowerCase().includes(q)));
    list.innerHTML = keep.map(c => conRowHtml(c, t.t0)).join('') ||
      '<div class="empty" style="padding:10px 0">No matching messages.</div>';
  };
  document.querySelectorAll('.cf').forEach(ch => ch.onclick = () => {
    lvl = lvl === ch.dataset.cf ? '' : ch.dataset.cf;
    document.querySelectorAll('.cf').forEach(x => x.classList.toggle('on', x.dataset.cf === lvl));
    render();
  });
  document.getElementById('consearch').addEventListener('input', e => { q = e.target.value.toLowerCase(); render(); });
  render();
}
function netPaneHtml(t){
  const net = t.network || [];
  if (!net.length && !t.network_dropped)
    return '<div class="empty" style="padding:14px 0">No network activity recorded.</div>';
  const cnt = c => c === '' ? net.length : c === 'bad' ? net.filter(n => !n.ok).length : net.filter(n => catOf(n) === c).length;
  const chips = NET_CATS.filter(([c]) => cnt(c)).map(([c, lbl]) =>
    `<span class="fchip nf${c === '' ? ' on' : ''}" data-nf="${c}">${lbl}<span class="n">${cnt(c)}</span></span>`).join('');
  return `${netSummaryHtml(net)}
    <div class="minibar"><input class="minisearch" id="netsearch" placeholder="Search URL or endpoint…">
      <select class="minisel" id="netsort"><option value="time">By time</option><option value="dur">By duration</option><option value="status">By status</option><option value="size">By size</option></select>
      ${chips}</div>
    <div class="netlist" id="netlist"></div>
    ${t.network_dropped ? `<div class="dropnote">${t.network_dropped} more requests were not captured (flow limit).</div>` : ''}`;
}
function wireNetPane(t){
  const list = document.getElementById('netlist');
  if (!list) return;
  const net = t.network || [];
  let cat = '', q = '', sort = 'time', shown = 100;
  const render = () => {
    let keep = net.filter(n => (cat === '' || (cat === 'bad' ? !n.ok : catOf(n) === cat)) &&
      (!q || n.url.toLowerCase().includes(q)));
    if (sort === 'dur') keep = [...keep].sort((a, b) => (b.duration_ms || 0) - (a.duration_ms || 0));
    else if (sort === 'status') keep = [...keep].sort((a, b) => (b.status || 999) - (a.status || 999));
    else if (sort === 'size') keep = [...keep].sort((a, b) => (b.size || 0) - (a.size || 0));
    NET_CTX = keep;
    list.innerHTML = keep.slice(0, shown).map((n, i) => netRowHtml(n, t.t0, i)).join('') ||
      '<div class="empty" style="padding:10px 0">No matching requests.</div>';
    if (keep.length > shown)
      list.innerHTML += `<button class="showmore" id="netmore">Show more (${keep.length - shown} hidden)</button>`;
    const more = document.getElementById('netmore');
    if (more) more.onclick = () => { shown += 200; render(); };
  };
  document.querySelectorAll('.nf').forEach(ch => ch.onclick = () => {
    cat = ch.dataset.nf;
    document.querySelectorAll('.nf').forEach(x => x.classList.toggle('on', x === ch));
    render();
  });
  document.getElementById('netsearch').addEventListener('input', e => { q = e.target.value.toLowerCase(); shown = 100; render(); });
  document.getElementById('netsort').addEventListener('change', e => { sort = e.target.value; render(); });
  render();
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
  return `<div class="sec"><h3>Likely related activity</h3><div class="relbox">
    <div class="relnote">Browser activity near the failure — troubleshooting hints, not a confirmed root cause.</div>
    ${cons.map(c => conRowHtml(c, t.t0)).join('')}
    ${net.map(n => `<div class="crow error"><span class="ctime">${relTime(n.ts, t.t0)}</span><span class="clvl error">net</span><span class="ctext">${esc(n.method)} ${esc(n.url)} — ${n.failure ? esc(n.failure) : 'HTTP ' + n.status}</span></div>`).join('')}
  </div></div>`;
}
function dtlPaneHtml(t){
  const leaves = (t.steps || []).filter((s, i, a) => !(a[i + 1] && a[i + 1].depth > s.depth));
  const timed = leaves.filter(s => s.ts != null);
  if (t.t0 == null || !timed.length)
    return '<div class="empty" style="padding:14px 0">No timing data for this test.</div>';
  const span = Math.max(t.duration_ms, 1);
  const trunc = s => s.length > 34 ? s.slice(0, 32) + '…' : s;
  const bars = timed.map(s => `<div class="tlrow"><span class="tllbl" title="${esc(s.name)}">${esc(trunc(s.name))}</span>
    <div class="tltrack"><div class="tlbar ${s.status}" style="left:${(s.ts - t.t0)/span*100}%;width:${Math.max((s.duration_ms || 0)/span*100, .6)}%"></div>
    ${s.attachment ? `<a class="tlshot" href="${ART(s.attachment)}" target="_blank" style="left:${Math.min((s.ts - t.t0 + (s.duration_ms || 0))/span*100, 98)}%" title="screenshot">📸</a>` : ''}</div></div>`).join('');
  const dots = (t.console || []).filter(c => c.ts != null && (lvlOf(c) === 'error' || lvlOf(c) === 'warning'))
      .map(c => `<i class="tldot ${lvlOf(c)}" style="left:${(c.ts - t.t0)/span*100}%" title="${esc(String(c.text).slice(0, 80))}"></i>`).join('')
    + (t.network || []).filter(n => !n.ok && n.ts != null)
      .map(n => `<i class="tldot net" style="left:${(n.ts - t.t0)/span*100}%" title="${esc(n.method + ' ' + n.url)}"></i>`).join('');
  return `<div class="tlwrap">${bars}
    ${dots ? `<div class="tlrow"><span class="tllbl">console / network</span><div class="tltrack">${dots}</div></div>` : ''}
    <div class="axis"><span>0</span><span>${fmtMs(span)}</span></div></div>`;
}
let lastDtab = 'd-art';
function openTest(i){
  const t = T[i];
  document.getElementById('drawer').innerHTML = `
    <div class="dhead">
      <div class="dtitle"><span class="badge ${effStatus(t)}">${effStatus(t)}</span><h2>${esc(t.title || t.name)}</h2>
        <button class="iconbtn" onclick="closeDrawer()">✕</button></div>
      <div class="dmeta">
        <div><span>file </span><b>${esc(t.file)}</b></div>
        ${t.flow ? `<div><span>flow </span><b>${esc(t.flow)}</b></div>` : `<div><span>test </span><b>${esc(t.name)}</b></div>`}
        <div><span>duration </span><b>${fmtMs(t.duration_ms)}</b></div>
        <div><span>started </span><b>${t.started_at ? new Date(t.started_at).toLocaleTimeString() : '—'}</b></div>
        ${t.retries ? `<div><span>reruns </span><b>${t.retries}</b></div>` : ''}
        ${(t.markers||[]).length ? `<div><span>markers </span><b>${t.markers.map(esc).join(', ')}</b></div>` : ''}
      </div>
    </div>
    <div class="dbody">
      ${errorHtml(t)}
      ${relatedHtml(t)}
      ${aiHtml(t.ai)}${healHtml(t)}
      <div class="sec"><h3>Steps</h3>${stepsHtml(t)}</div>
      <div class="sec">
        <div class="dtabs">
          <span class="dtab" data-t="d-art">Artifacts</span>
          <span class="dtab" data-t="d-con">Console (${(t.console||[]).length})</span>
          <span class="dtab" data-t="d-net">Network (${(t.network||[]).length})</span>
          <span class="dtab" data-t="d-tl">Timeline</span>
        </div>
        <div class="dpane" id="d-art">${artsHtml(t)}</div>
        <div class="dpane" id="d-con">${consolePaneHtml(t)}</div>
        <div class="dpane" id="d-net">${netPaneHtml(t)}</div>
        <div class="dpane" id="d-tl">${dtlPaneHtml(t)}</div>
      </div>
    </div>`;
  const tabs = [...document.querySelectorAll('.dtab')];
  const activate = tab => {
    tabs.forEach(x => x.classList.toggle('active', x === tab));
    document.querySelectorAll('.dpane').forEach(x => x.classList.toggle('active', x.id === tab.dataset.t));
    lastDtab = tab.dataset.t;   // keep the selected tab across tests
  };
  activate(tabs.find(x => x.dataset.t === lastDtab) || tabs[0]);
  tabs.forEach(tab => tab.onclick = () => activate(tab));
  wireConsolePane(t); wireNetPane(t);
  document.getElementById('drawer').classList.add('show');
  document.getElementById('overlay').classList.add('show');
}
function closeDrawer(){
  document.getElementById('drawer').classList.remove('show');
  document.getElementById('overlay').classList.remove('show');
}
document.getElementById('overlay').onclick = closeDrawer;

/* ── timeline ── */
(function timeline(){
  const withT = byStart.filter(i => T[i].started_at);
  if (!withT.length){ document.getElementById('lanes').innerHTML = '<div class="empty">No timing data.</div>'; return; }
  const start = i => new Date(T[i].started_at).getTime();
  const end = i => start(i) + T[i].duration_ms;
  const t0 = Math.min(...withT.map(start)), t1 = Math.max(...withT.map(end));
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
        title="${esc(T[i].title || T[i].name)} · ${fmtMs(T[i].duration_ms)}"
        style="left:${(start(i)-t0)/span*100}%;width:${Math.max(T[i].duration_ms/span*100, .4)}%"></div>`).join('')}</div></div>`).join('');
  document.getElementById('ticks').innerHTML =
    [0,.25,.5,.75,1].map(f => `<span>${fmtMs(span*f)}</span>`).join('');
})();
