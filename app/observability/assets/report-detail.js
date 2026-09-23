/* Per-test drawer and the console/network views. Loaded after report.js and
   uses its helpers (esc, fmtMs, icon, badge, explain, T…). The drawer reads top
   to bottom the way a reviewer asks: what went wrong, the facts, the steps,
   then the technical detail an engineer needs — folded away by default. */

const EV_KIND = {viewport: 'Screen at failure', full_page: 'Full page', element: 'Element'};
const NET_CATS = [['','All'], ['bad','Failed'], ['xhr','XHR'], ['doc','Doc'], ['js','JS'], ['css','CSS'], ['img','Img'], ['other','Other']];
const CON_LEVELS = [['error','Errors'], ['warning','Warnings'], ['info','Info'], ['debug','Debug']];
function catOf(n){
  const rt = n.resource_type || '';
  return rt === 'xhr' || rt === 'fetch' ? 'xhr' : rt === 'document' ? 'doc' :
    rt === 'script' ? 'js' : rt === 'stylesheet' ? 'css' :
    rt === 'image' || rt === 'media' || rt === 'font' ? 'img' : 'other';
}
const section = (title, body, count) => body ? `<section class="drawer-section">
  <h3 class="drawer-section-title">${title}${count != null ? `<span class="count">${count}</span>` : ''}</h3>${body}</section>` : '';
// Label-over-value pairs in a wrapping row: the drawer summary, kept short.
const factStrip = rows => `<dl class="fact-strip">${rows.filter(r => r[1]).map(([k, v]) => `<div><dt>${k}</dt><dd>${v}</dd></div>`).join('')}</dl>`;
const facts = rows => `<dl class="case-facts">${rows.filter(r => r[1]).map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join('')}</dl>`;
const imgLink = (path, caption, size) => `<a class="drawer-image-link ${size}" href="${esc(path)}" target="_blank" rel="noopener"
  title="Open full size in a new tab"><img src="${esc(path)}" alt="${esc(caption)}" loading="lazy">${caption ? `<span>${esc(caption)}</span>` : ''}</a>`;

/* ── what went wrong ── */
function wentWrongHtml(t){
  const s = failedStep(t);
  const ev = (s && s.evidence) || {};
  const shots = Object.entries(ev.screenshots || {}).filter(([, p]) => p);
  if (!shots.length && failureShot(t)) shots.push(['viewport', failureShot(t)]);
  const main = shots.find(([k]) => k === 'viewport') || shots[0];
  const rest = shots.filter(x => x !== main);
  return section('What went wrong', `
    ${s ? `<div class="drawer-step-callout"><p class="drawer-step-label">Failed step</p>
      <p class="drawer-step-name">${icon('x')}<span title="${esc(s.action || '')}">${esc(s.action ? actionLabel(s.action) : s.name)}
        ${s.args ? `<span class="args mono">${esc(s.args)}</span>` : ''}</span></p></div>` : ''}
    <p class="drawer-why">${esc(explain(t))}</p>
    ${main ? `<div class="drawer-shots">${imgLink(main[1], EV_KIND[main[0]] || main[0], 'main')}
      ${rest.map(([k, p]) => imgLink(p, EV_KIND[k] || k, 'small')).join('')}</div>`
      : '<p class="note">No screenshot was captured for this failure.</p>'}`);
}
function factsHtml(t){
  const p = t.profile || {};
  return section('Summary', factStrip([
    ['Result', statusBadge(effStatus(t))], ['Duration', esc(fmtMs(t.duration_ms))],
    ['Started', t.started_at ? esc(new Date(t.started_at).toLocaleTimeString()) : ''],
    ['Suite', esc(suiteTitle(t))], ['Area', esc(areaLabel(areaOf(t)))],
    ['Device', esc(p.label || p.name || '')], ['Reruns', t.retries ? String(t.retries) : ''],
    ['Tags', (t.markers||[]).map(m => badge(esc(m))).join(' ')],
  ]));
}
function agentHtml(t){
  // Autonomous run facts (test_page / explore_page): what the agent saw,
  // planned, skipped, and left behind. Lists are data from the run.
  const a = t.agent;
  if (!a) return '';
  const list = (items, cls) => items && items.length ? `<ul class="${cls || ''}">${items.map(x => `<li>${esc(x)}</li>`).join('')}</ul>` : '';
  return section('Autonomous run', `<dl class="case-facts agent-facts">${[
    ['Page type', a.page_type ? esc(a.page_type) + (a.classification ? ` <span class="tech-hint">(${esc(a.classification)})</span>` : '') : ''],
    ['Components', list(a.components)],
    ['Plan', a.plan && a.plan.length ? `<ol>${a.plan.map(x => `<li>${esc(x)}</li>`).join('')}</ol>` : ''],
    ['Rejected plan steps', list(a.plan_rejected, 'bad')], ['Skipped for safety', list(a.skipped, 'warn')],
    ['Actions executed', a.actions && a.actions.length ? `${a.actions.length} — ` + esc(a.actions.slice(0, 8).join(' · ')) + (a.actions.length > 8 ? ' …' : '') : ''],
    ['AI calls', a.ai_calls != null ? String(a.ai_calls) : ''],
    ['Generated flow', a.generated ? `<a href="${esc(a.generated)}" target="_blank">${esc(a.generated)}</a> <span class="tech-hint">— review it, then add it to the suite</span>` : ''],
  ].filter(r => r[1]).map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join('')}</dl>`);
}

/* ── steps ── */
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
function checksHtml(s){
  // Oracle checks after a step, or a skill's findings: collapsed one-liner,
  // rows on expand. info rows are observations, never flagged.
  const cs = s.checks || [];
  if (!cs.length) return '';
  const flagged = cs.filter(c => !c.passed);
  const bad = flagged.filter(c => c.severity === 'error').length, warn = flagged.length - bad;
  const counted = cs.filter(c => c.severity !== 'info').length;
  const head = bad ? `${bad} of ${counted} checks failed${warn ? `, ${plural(warn, 'warning')}` : ''}`
    : warn ? `${plural(warn, 'warning')} in ${counted} checks` : counted ? `${counted} checks passed` : plural(cs.length, 'observation');
  const kind = bad ? ['danger', 'x'] : warn ? ['warning', 'warn'] : counted ? ['success', 'check'] : ['neutral', 'info'];
  const rows = cs.map(c => {
    const r = c.severity === 'info' ? ['info', 'info'] : c.passed ? ['ok', 'check'] : c.severity === 'error' ? ['bad', 'x'] : ['warn', 'warn'];
    return `<div class="chkrow ${r[0]}">${icon(r[1])}<span class="chkname">${esc(c.name)}</span>${c.detail ? `<span class="chkdetail">${esc(c.detail)}</span>` : ''}</div>`;
  }).join('');
  return `<details class="chk"><summary>${badge(icon(kind[1]) + head, kind[0])}</summary><div class="chk-list">${rows}</div></details>`;
}
function stepShots(s, errStep){
  // The failure's own screenshots are shown under "What went wrong".
  if (s === errStep) return '';
  const paths = s.evidence ? Object.values(s.evidence.screenshots || {}) : s.attachment ? [s.attachment] : [];
  return paths.length ? `<div class="sthumbs">${paths.map(p => `<a href="${esc(p)}" target="_blank" rel="noopener"><img src="${esc(p)}" alt="Step screenshot" loading="lazy"></a>`).join('')}</div>` : '';
}
function stepLine(s, n){
  const heal = s.layer > 1 && s.status === 'passed'
    ? iconBadge('zap', 'warning', `Self-healed: found by the ${s.layer === 3 ? 'AI' : 'fuzzy-match'} fallback (layer ${s.layer})`) : '';
  const what = s.action ? `<span class="sverb" title="${esc(s.action)}">${esc(actionLabel(s.action))}</span>${s.args ? `<span class="sargs">${esc(s.args)}</span>` : ''}`
    : `<span class="sverb">${esc(s.name)}</span>`;
  return `<div class="sline"><span class="slabel">Step ${n}</span>${what}${heal}<span class="sdur">${fmtMs(s.duration_ms)}</span></div>`;
}
function stepErr(t, n, errStep){
  const s = n.step;
  // Ancestors carry a copy of the child's error — render only at the site.
  if (s.status !== 'failed' || n.children.some(c => c.step.status === 'failed')) return '';
  const text = s === errStep ? explain(t) : cleanError(s.error);
  return text ? `<div class="serr">${esc(text)}</div>` : '';
}
function stepNodes(t, nodes, errStep, fail){
  return nodes.map((n, i) => {
    const s = n.step, st = s.status;
    const ico = icon(st === 'failed' ? 'x' : st === 'skipped' ? 'skip' : 'check', `sicon ${st}`);
    const extras = checksHtml(s) + stepShots(s, errStep);
    if (n.children.length){
      // In a failing test, passing groups fold so the failing one stands out.
      const open = st === 'failed' || !fail;
      return `<details class="sgroup ${st}"${open ? ' open' : ''}><summary class="srow">${icon('chev', 'toggle-icon')}${ico}
        <div class="smain">${stepLine(s, i + 1)}</div></summary>
        <div class="sgroup-body">${extras}<div class="steps">${stepNodes(t, n.children, errStep, fail)}</div>${stepErr(t, n, errStep)}</div></details>`;
    }
    return `<div class="srow ${st}">${ico}<div class="smain">${stepLine(s, i + 1)}${stepErr(t, n, errStep)}${extras}</div></div>`;
  }).join('');
}
function stepsHtml(t){
  if (!(t.steps||[]).length) return '<p class="empty-inline">No steps recorded for this test.</p>';
  return `<div class="steps">${stepNodes(t, stepTree(t.steps), failedStep(t), failedLike(t.status))}</div>`;
}

/* ── technical details ── */
function errorOutputHtml(t){
  const s = failedStep(t), e = t.error || {};
  const msg = (s && s.error) || e.message;
  if (!msg && !e.traceback) return '';
  return `<div><h4 class="sub-title">Error output</h4><pre class="drawer-error">${esc(msg || '')}</pre>
    ${e.traceback && e.traceback !== msg ? `<details class="chk"><summary>${badge('Full output')}</summary><pre class="drawer-error">${esc(e.traceback)}</pre></details>` : ''}</div>`;
}
function evidenceHtml(ev){
  // What each layer did, where the page was, and what the browser logged
  // while the step ran.
  if (!ev) return '';
  const layers = Object.entries(ev.layers || {}).map(([k, v]) =>
    badge(`${esc(k)}: ${esc(v)}`, v === 'failed' ? 'danger' : /^(ok|passed|resolved)/.test(v) ? 'success' : 'neutral')).join('');
  const links = [ev.trace ? `<a href="${esc(ev.trace)}" download title="Open with: npx playwright show-trace <file>">${icon('download')}Playwright trace</a>` : '',
    ...Object.entries(ev.files || {}).map(([k, p]) => `<a href="${esc(p)}" target="_blank">${icon('file')}${esc(k)}</a>`)].join('');
  const cons = ev.console || [], net = ev.network || [];
  const rows = [...cons.map(c => conRowHtml(c, null)), ...net.map(netAsConsole).map(c => conRowHtml(c, null).replace('>error<', '>net<'))];
  return `${layers ? `<div><h4 class="sub-title">How the step was attempted</h4><div class="layer-list">${layers}</div></div>` : ''}
    ${ev.url || ev.title ? `<div><h4 class="sub-title">Page at the failure</h4>${facts([
      ['Address', ev.url ? `<a href="${esc(ev.url)}" target="_blank" rel="noopener">${esc(ev.url)}</a>` : ''],
      ['Title', esc(ev.title || '')], ['Device', esc(ev.profile || '')]])}</div>` : ''}
    ${links ? `<div class="links">${links}</div>` : ''}
    ${rows.length ? `<div><h4 class="sub-title">Logged during the step</h4><div class="loglist">${rows.join('')}</div></div>` : ''}`;
}
// Host and path only: tracking beacons carry kilobytes of query string.
const shortUrl = u => { try { const x = new URL(u); return x.host + x.pathname + (x.search ? '?…' : ''); } catch(e) { return u; } };
const netAsConsole = n => ({level: 'error', ts: n.ts, text: `${n.method} ${shortUrl(n.url)} — ${n.failure ? n.failure : 'HTTP ' + n.status}`});
function relatedHtml(t){
  if (!failedLike(t.status)) return '';
  const fs = failedStep(t);
  const from = fs && fs.ts != null ? fs.ts - 2000 : t.t0 != null ? t.t0 + Math.max(t.duration_ms - 10000, 0) : null;
  if (from == null) return '';
  const end = t.t0 != null ? t.t0 + t.duration_ms + 2000 : Infinity;
  const cons = (t.console || []).filter(c => lvlOf(c) === 'error' && c.ts >= from && c.ts <= end).slice(-5);
  const net = (t.network || []).filter(n => !n.ok && n.ts >= from && n.ts <= end).slice(-5);
  if (!cons.length && !net.length) return '';
  // failed requests reuse the console row shape: level "net", text = request + outcome
  return `<div><h4 class="sub-title">Browser activity near the failure</h4>
    <p class="note">Hints for troubleshooting, not a confirmed cause.</p><div class="relbox">
    ${cons.map(c => conRowHtml(c, t.t0)).join('')}${net.map(netAsConsole).map(c => conRowHtml(c, t.t0).replace('>error<', '>net<')).join('')}</div></div>`;
}
function healHtml(t){
  const h = t.healings || [];
  if (!h.length) return '';
  return `<div><h4 class="sub-title">Self-healed steps</h4><p class="note">Resolved by a fallback locator at runtime — update the flow.</p>
    ${facts(h.map(e => [`Layer ${e.layer}`, `${esc(e.description)}<br><span class="tech-hint">${esc(e.healed_by)} → ${esc(e.resolved)}</span>`]))}</div>`;
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
  const lvl = lvlOf(c), lines = String(c.text ?? '').split('\n');
  const main = `<span class="ctime">${relTime(c.ts, t0)}</span><span class="clvl ${lvl}">${esc(c.level)}</span>
    <span class="ctext">${esc(lines[0])}${c.count > 1 ? `<span class="cxn">×${c.count}</span>` : ''}</span>
    ${ti != null ? `<button class="cfrom" data-open="${ti}">${titleOf(T[ti])}</button>` : ''}
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
document.addEventListener('click', e => {
  const b = e.target.closest('[data-copy]');
  const n = b && (NET_CTX[b.dataset.ctx] || [])[+b.dataset.idx];
  if (!n) return;
  const label = b.textContent;
  try { navigator.clipboard.writeText(b.dataset.copy === 'curl' ? curlOf(n) : n.url)
    .then(() => { b.textContent = 'Copied'; setTimeout(() => b.textContent = label, 900); }, () => {}); } catch(err) {}
});
const fmtKv = o => Object.entries(o || {}).map(([k, v]) => `${k}: ${v}`).join('\n');
function netRowHtml(n, t0, ctx, idx, ti){
  let host = '', path = n.url, qp = '';
  try { const u = new URL(n.url); host = u.host; path = u.pathname + u.search; qp = [...u.searchParams].map(([k, v]) => `${k} = ${v}`).join('\n'); } catch(e) {}
  const status = n.status != null
    ? `<span class="nstat ${n.status >= 400 ? 'sbad' : n.status >= 300 ? 'swarn' : 'sok'}">${n.status}</span>`
    : `<span class="nstat ${n.method === 'WS' ? 'swarn' : 'sbad'}">${n.method === 'WS' ? 'WS' : 'ERR'}</span>`;
  const slow = (n.duration_ms || 0) > 2000;
  const block = (label, body, cls = '') => body ? `<div class="sub-title">${label}</div><pre class="codebox ${cls}">${esc(body)}</pre>` : '';
  return `<details class="netrow ${n.ok ? 'ok' : 'bad'}"><summary><span class="nmethod">${esc(n.method)}</span>${status}
    <span class="nurl" title="${esc(n.url)}"><span class="nhost">${esc(host)}</span>${esc(path)}${n.failure ? ` <span class="nfailure">${esc(n.failure)}</span>` : ''}</span>
    ${ti != null ? `<button class="cfrom" data-open="${ti}">${titleOf(T[ti])}</button>` : ''}
    <span class="ntime">${relTime(n.ts, t0)}</span>
    <span class="ndur${slow ? ' slow' : ''}"${slow ? ' title="slow request (>2s)"' : ''}>${n.duration_ms != null ? fmtMs(n.duration_ms) : ''}</span>
    <span class="nsize">${fmtBytes(n.size)}</span>
    <span class="ntype"${n.resource_type ? ` title="${esc(n.resource_type)}"` : ''}>${esc(n.resource_type || '')}</span><span class="nchev">▸</span></summary>
    <div class="ndetail"><div class="nbtns">
      <button class="btn" data-copy="curl" data-ctx="${ctx}" data-idx="${idx}">Copy cURL</button>
      <button class="btn" data-copy="url" data-ctx="${ctx}" data-idx="${idx}">Copy URL</button>
      ${n.step ? `<span class="cstep" title="active step">during: ${esc(n.step)}</span>` : ''}</div>
      ${block('Query parameters', qp)}${block('Request headers', fmtKv(n.request_headers))}${block('Request body', n.post_data)}
      ${block('Response headers', fmtKv(n.response_headers))}${block('Response body', n.body)}</div></details>`;
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
  return `<div class="netsum"><span><b>${net.length}</b> requests</span><span class="${failed ? 'ko' : ''}"><b>${failed}</b> failed</span>
    <span><b>${fmtBytes(bytes) || '0 B'}</b> transferred</span>${slowest != null ? `<span>slowest <b>${fmtMs(slowest)}</b></span>` : ''}
    ${first != null ? `<span>span <b>${fmtMs(last - first)}</b></span>` : ''}</div>`;
}

/* ── one console view and one network view, used by the drawer and the
   execution-level tabs. Items are {e, t0, i?}: the entry, the owning test's
   t0 for offsets, and (aggregated views only) the test index. ── */
const chipHtml = (key, label, n, on) => `<button class="qa-tab-btn${on ? ' active' : ''}" data-k="${key}">${label}<span class="count">${n}</span></button>`;
function wireChips(host, onPick){
  host.querySelectorAll('[data-k]').forEach(ch => ch.onclick = () => {
    const picked = onPick(ch.dataset.k);
    host.querySelectorAll('[data-k]').forEach(x => x.classList.toggle('active', x.dataset.k === picked));
  });
}
function showMore(list, hidden, onClick){
  if (hidden <= 0) return;
  list.insertAdjacentHTML('beforeend', `<button class="showmore">Show more (${hidden} hidden)</button>`);
  list.lastElementChild.onclick = onClick;
}
function consoleView({items, list, chipsHost, search, group, pageSize}){
  // group: collapse identical messages (drawer); aggregated view keeps every row
  const t0 = items.length ? items[0].t0 : null;
  const rows = group ? groupConsole(items.map(x => x.e)).map(e => ({e, t0})) : items;
  rows.forEach(x => { x.q = (x.e.text + ' ' + (x.e.location || '')).toLowerCase(); });
  const tally = {};
  rows.forEach(x => { const l = lvlOf(x.e); tally[l] = (tally[l] || 0) + 1; });
  chipsHost.innerHTML = CON_LEVELS.map(([l, lbl]) => chipHtml(l, lbl, tally[l] || 0, false)).join('');
  let lvl = '', q = '', shown = pageSize;
  const render = () => {
    const keep = rows.filter(x => (!lvl || lvlOf(x.e) === lvl) && (!q || x.q.includes(q)));
    list.innerHTML = keep.slice(0, shown).map(x => conRowHtml(x.e, x.t0, x.i)).join('') || '<p class="empty-inline" style="padding:.6rem">No matching messages.</p>';
    showMore(list, keep.length - shown, () => { shown += 2 * pageSize; render(); });
  };
  wireChips(chipsHost, k => { lvl = lvl === k ? '' : k; render(); return lvl; });
  search.addEventListener('input', debounce(e => { q = e.target.value.toLowerCase(); shown = pageSize; render(); }));
  render();
}
function networkView({items, list, chipsHost, search, sortSel, ctx, pageSize, withTest}){
  items.forEach(x => { x.q = x.e.url.toLowerCase(); x.c = catOf(x.e); });
  const tally = {'': items.length, bad: 0};
  items.forEach(x => { if (!x.e.ok) tally.bad++; tally[x.c] = (tally[x.c] || 0) + 1; });
  chipsHost.innerHTML = NET_CATS.filter(([c]) => tally[c]).map(([c, lbl]) => chipHtml(c, lbl, tally[c], c === '')).join('');
  let cat = '', q = '', sort = 'time', shown = pageSize;
  const render = () => {
    const keep = items.filter(x => (cat === '' || (cat === 'bad' ? !x.e.ok : x.c === cat)) && (!q || x.q.includes(q)));
    if (sort === 'dur') keep.sort((a, b) => (b.e.duration_ms || 0) - (a.e.duration_ms || 0));
    else if (sort === 'status') keep.sort((a, b) => (b.e.status || 999) - (a.e.status || 999));
    else if (sort === 'size') keep.sort((a, b) => (b.e.size || 0) - (a.e.size || 0));
    NET_CTX[ctx] = keep.map(x => x.e);
    const rows = keep.slice(0, shown).map((x, i) => netRowHtml(x.e, x.t0, ctx, i, withTest ? x.i : undefined)).join('');
    list.innerHTML = rows ? netHeadHtml(withTest) + rows : '<p class="empty-inline" style="padding:.6rem">No matching requests.</p>';
    showMore(list, keep.length - shown, () => { shown += 2 * pageSize; render(); });
  };
  wireChips(chipsHost, k => { cat = k; render(); return cat; });
  search.addEventListener('input', debounce(e => { q = e.target.value.toLowerCase(); shown = pageSize; render(); }));
  if (sortSel) sortSel.addEventListener('change', e => { sort = e.target.value; render(); });
  render();
}

/* ── drawer ── */
function consolePaneHtml(t){
  if (!(t.console || []).length && !t.console_dropped) return '<p class="empty-inline">No console messages captured.</p>';
  return `<div class="minibar"><input class="form-control" id="consearch" placeholder="Search messages…"><span class="chips" id="conchips"></span></div>
    <div class="loglist" id="conlist"></div>
    ${t.console_dropped ? `<div class="dropnote">${t.console_dropped} more entries were not captured (flow limit).</div>` : ''}`;
}
function netPaneHtml(t){
  const net = t.network || [];
  if (!net.length && !t.network_dropped) return '<p class="empty-inline">No network activity recorded.</p>';
  return `${netSummaryHtml(net)}
    <div class="minibar"><input class="form-control" id="netsearch" placeholder="Search URL or endpoint…">
      <select class="form-select" id="netsort"><option value="time">By time</option><option value="dur">By duration</option><option value="status">By status</option><option value="size">By size</option></select>
      <span class="chips" id="netchips"></span></div>
    <div class="netlist" id="netlist"></div>
    ${t.network_dropped ? `<div class="dropnote">${t.network_dropped} more requests were not captured (flow limit).</div>` : ''}`;
}
function wireDrawerPanes(t){
  if ($('conlist')) consoleView({items: (t.console || []).map(e => ({e, t0: t.t0})), list: $('conlist'), chipsHost: $('conchips'),
    search: $('consearch'), group: true, pageSize: 200});
  if ($('netlist')) networkView({items: (t.network || []).map(e => ({e, t0: t.t0})), list: $('netlist'), chipsHost: $('netchips'),
    search: $('netsearch'), sortSel: $('netsort'), ctx: 'drawer', pageSize: 100, withTest: false});
}
let lastDtab = 'd-con', techOpen = false, lastFocus = null;
let drawerSeq = 0;   // ignore shard arrivals for a test the user has left
function openTest(i){
  const t = T[i], st = effStatus(t), fail = failedLike(t.status), fs = failedStep(t);
  const loading = '<p class="empty-inline">Loading…</p>';
  const drawer = $('drawer');
  if (!drawer.classList.contains('show')) lastFocus = document.activeElement;
  drawer.innerHTML = `
    <header class="side-drawer-head">
      <div class="side-drawer-tags">${statusBadge(st)}${t.profile && t.profile.name ? badge(esc(cap(t.profile.name)), 'primary') : ''}${badge(esc(areaLabel(areaOf(t))))}</div>
      <h2 class="side-drawer-title" id="dtitle">${titleOf(t)}</h2>
      <p class="side-drawer-path">${esc(t.file)}${t.name !== (t.title || t.name) ? ' › ' + esc(t.name) : ''}</p>
      <button class="side-drawer-close" aria-label="Close details">${icon('close')}</button>
    </header>
    <div class="side-drawer-body">
      ${fail ? wentWrongHtml(t) : ''}
      ${factsHtml(t)}
      ${agentHtml(t)}
      ${section('Steps', stepsHtml(t), (t.steps || []).filter(s => !s.depth).length || null)}
      <section class="drawer-section"><details class="tech"${techOpen ? ' open' : ''}>
        <summary>${icon('chev', 'toggle-icon')}<h3 class="drawer-section-title">Technical details</h3>
          <span class="tech-hint">For engineers: error output, locator attempts, console and network</span></summary>
        <div class="tech-body">
          ${fail ? errorOutputHtml(t) : ''}
          ${fs ? evidenceHtml(fs.evidence) : ''}
          <div id="d-rel">${hasDetail(t) ? relatedHtml(t) : ''}</div>
          ${healHtml(t)}
          <div><div class="subtabs" role="tablist">
            <button class="qa-tab-btn" role="tab" data-t="d-con">Console<span class="count">${t.counts.console}</span></button>
            <button class="qa-tab-btn" role="tab" data-t="d-net">Network<span class="count">${t.counts.network}</span></button></div>
            <div class="dpane" id="d-con">${hasDetail(t) ? consolePaneHtml(t) : loading}</div>
            <div class="dpane" id="d-net">${hasDetail(t) ? netPaneHtml(t) : loading}</div></div>
        </div></details></section>
    </div>`;
  drawer.querySelector('.tech').addEventListener('toggle', e => { techOpen = e.target.open; });
  const tabs = [...drawer.querySelectorAll('[data-t]')];
  const activate = tab => {
    tabs.forEach(x => { x.classList.toggle('active', x === tab); x.setAttribute('aria-selected', x === tab); });
    drawer.querySelectorAll('.dpane').forEach(x => x.classList.toggle('active', x.id === tab.dataset.t));
    lastDtab = tab.dataset.t;   // keep the selected tab across tests
  };
  activate(tabs.find(x => x.dataset.t === lastDtab) || tabs[0]);
  tabs.forEach(tab => tab.onclick = () => activate(tab));
  drawer.querySelector('.side-drawer-close').onclick = closeDrawer;
  if (hasDetail(t)) wireDrawerPanes(t);
  else {
    const seq = ++drawerSeq;
    loadDetail(i).then(() => {
      if (seq !== drawerSeq) return;
      $('d-rel').innerHTML = relatedHtml(t);
      $('d-con').innerHTML = consolePaneHtml(t);
      $('d-net').innerHTML = netPaneHtml(t);
      wireDrawerPanes(t);
    }, () => {
      if (seq !== drawerSeq) return;
      const miss = '<p class="empty-inline">Detail data unavailable — this test\'s file is missing from assets/data/.</p>';
      $('d-con').innerHTML = miss; $('d-net').innerHTML = miss;
    });
  }
  drawer.classList.add('show');
  $('overlay').classList.add('show');
  document.body.classList.add('drawer-open');
  drawer.querySelector('.side-drawer-body').scrollTop = 0;
  drawer.querySelector('.side-drawer-close').focus();
}
function closeDrawer(){
  if (!$('drawer').classList.contains('show')) return;
  $('drawer').classList.remove('show');
  $('overlay').classList.remove('show');
  document.body.classList.remove('drawer-open');
  if (lastFocus && lastFocus.focus) lastFocus.focus();
}
$('overlay').onclick = closeDrawer;

/* ── execution-level console & network (secondary, aggregated) ──
   Entries load on first open of either tab (all detail shards, rendered together). */
let globalReady = null;
function ensureGlobalViews(){
  if (globalReady) return;
  globalReady = Promise.all(T.map((t, i) => loadDetail(i).then(() => 0, () => 1)))
    .then(fails => initGlobalViews(fails.reduce((a, b) => a + b, 0)));
}
function initGlobalViews(missing){
  if (missing){
    const note = `<div class="dropnote">Detail for ${missing} test(s) could not be loaded (missing files).</div>`;
    $('gconlist').insertAdjacentHTML('beforebegin', note);
    $('gnetlist').insertAdjacentHTML('beforebegin', note);
  }
  const bySeq = (a, b) => (a.e.ts ?? 0) - (b.e.ts ?? 0) || (a.e.seq ?? 0) - (b.e.seq ?? 0);
  const CON = T.flatMap((t, i) => (t.console || []).map(e => ({e, i, t0: t.t0}))).sort(bySeq);
  const NET = T.flatMap((t, i) => (t.network || []).map(e => ({e, i, t0: t.t0}))).sort(bySeq);
  consoleView({items: CON, list: $('gconlist'), chipsHost: $('gconchips'), search: $('gconsearch'), group: false, pageSize: 200});
  $('gnetsum').innerHTML = netSummaryHtml(NET.map(x => x.e));
  networkView({items: NET, list: $('gnetlist'), chipsHost: $('gnetchips'), search: $('gnetsearch'),
    sortSel: null, ctx: 'global', pageSize: 150, withTest: true});
}
