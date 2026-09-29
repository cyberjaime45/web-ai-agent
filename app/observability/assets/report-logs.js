/* Console and network views: row renderers, filters and paging, the drawer's
   Console / Network panes and the execution-level tabs. Loaded after report.js
   (esc, T, loadDetail…) and before report-detail.js, which calls into it. */

const NET_CATS = [['','All'], ['bad','Failed'], ['xhr','XHR'], ['doc','Doc'], ['js','JS'], ['css','CSS'], ['img','Img'], ['other','Other']];
const CON_LEVELS = [['error','Errors'], ['warning','Warnings'], ['info','Info'], ['debug','Debug']];
function catOf(n){
  const rt = n.resource_type || '';
  return rt === 'xhr' || rt === 'fetch' ? 'xhr' : rt === 'document' ? 'doc' :
    rt === 'script' ? 'js' : rt === 'stylesheet' ? 'css' :
    rt === 'image' || rt === 'media' || rt === 'font' ? 'img' : 'other';
}

// Host and path only: tracking beacons carry kilobytes of query string.
const shortUrl = u => { try { const x = new URL(u); return x.host + x.pathname + (x.search ? '?…' : ''); } catch(e) { return u; } };
const netAsConsole = n => ({level: 'net', ts: n.ts, text: `${n.method} ${shortUrl(n.url)} — ${n.failure ? n.failure : 'HTTP ' + n.status}`});

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
  const status = n.status != null ? `<span class="nstat ${n.status >= 400 ? 'sbad' : n.status >= 300 ? 'swarn' : 'sok'}">${n.status}</span>`
    : `<span class="nstat ${n.method === 'WS' ? 'swarn' : failedReq(n) ? 'sbad' : 'sskip'}">${n.method === 'WS' ? 'WS' : failedReq(n) ? 'ERR' : 'CANCEL'}</span>`;
  const slow = (n.duration_ms || 0) > 2000;
  const block = (label, body, cls = '') => body ? `<div class="sub-title">${label}</div><pre class="codebox ${cls}">${esc(body)}</pre>` : '';
  return `<details class="netrow ${failedReq(n) ? 'bad' : 'ok'}"><summary><span class="nmethod">${esc(n.method)}</span>${status}
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
    if (failedReq(n)) failed++;
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
  items.forEach(x => { if (failedReq(x.e)) tally.bad++; tally[x.c] = (tally[x.c] || 0) + 1; });
  chipsHost.innerHTML = NET_CATS.filter(([c]) => tally[c]).map(([c, lbl]) => chipHtml(c, lbl, tally[c], c === '')).join('');
  let cat = '', q = '', sort = 'time', shown = pageSize;
  const render = () => {
    const keep = items.filter(x => (cat === '' || (cat === 'bad' ? failedReq(x.e) : x.c === cat)) && (!q || x.q.includes(q)));
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

/* ── the drawer's Console / Network panes ── */
function consolePaneHtml(t){
  if (!(t.console || []).length && !t.console_dropped) return '<p class="empty-inline">No console messages captured.</p>';
  return `<div class="minibar"><input class="form-control" id="consearch" placeholder="Search messages…"><span class="chips" id="conchips"></span></div>
    <div class="loglist" id="conlist"></div>
    ${t.console_dropped ? `<div class="dropnote">${t.console_dropped} more entries were not captured (flow limit).</div>` : ''}`;
}
function netPaneHtml(t){
  const net = t.network || [], u = t.network_untracked || {};
  const skipped = [u.other_site && plural(u.other_site, 'request') + ' to other sites', u.prefetch && plural(u.prefetch, 'prefetch', 'prefetches')].filter(Boolean);
  const note = skipped.length ? `<div class="dropnote">Not recorded: ${skipped.join(', ')} (only the site under test is tracked; the count covers the whole flow).</div>` : '';
  if (!net.length && !t.network_dropped) return (note || '') + '<p class="empty-inline">No network activity recorded.</p>';
  return `${note}${netSummaryHtml(net)}
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
