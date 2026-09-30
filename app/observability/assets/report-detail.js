/* Per-test drawer. Loaded after report.js (esc, fmtMs, icon, badge, explain,
   T…) and report-logs.js (the Console / Network panes). The drawer reads top
   to bottom the way a reviewer asks: the facts, what went wrong, the warnings,
   the steps, then the technical detail an engineer needs — folded by default. */

const EV_KIND = {viewport: 'Screen at failure', full_page: 'Full page', element: 'Element'};
const section = (title, body, count, kind) => body ? `<section class="drawer-section${kind ? ' drawer-section-' + kind : ''}">
  <h3 class="drawer-section-title">${title}${count != null ? `<span class="count">${count}</span>` : ''}</h3>${body}</section>` : '';
// Label-over-value pairs in a wrapping row: the drawer summary, kept short.
const factStrip = rows => `<dl class="fact-strip">${rows.filter(r => r[1]).map(([k, v]) => `<div><dt>${k}</dt><dd>${v}</dd></div>`).join('')}</dl>`;
const facts = (rows, cls = '') => `<dl class="case-facts ${cls}">${rows.filter(r => r[1]).map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join('')}</dl>`;
const imgLink = (path, caption, size) => `<a class="drawer-image-link ${size}" href="${esc(path)}" target="_blank" rel="noopener"
  title="Open full size in a new tab"><img src="${esc(path)}" alt="${esc(caption)}" loading="lazy">${caption ? `<span>${esc(caption)}</span>` : ''}</a>`;

/* ── what went wrong ── */
const VERDICT = {application: ['Likely application defect', 'danger'], timing: ['Likely timing: page still loading', 'warning'],
  test: ['Likely test issue', 'warning'], environment: ['Likely environment or session', 'neutral'],
  framework: ['Flow or setup problem', 'neutral'], unclassified: ['Cause unclear', 'neutral']};
function diagnosisHtml(s){
  // The engine's likely cause for the failed step, with the signals behind it.
  const d = s && s.evidence && s.evidence.diagnosis;
  if (!d || !d.verdict) return '';
  const [label, kind] = VERDICT[d.verdict] || VERDICT.unclassified;
  const signals = (d.signals || []).map(x => `<li>${esc(x)}</li>`).join('');
  // Expected (from the step) against Observed (from the page), then the verdict.
  const seen = [d.expected ? ['Expected', esc(d.expected)] : null, d.observed ? ['Observed', esc(d.observed)] : null].filter(Boolean);
  return `<div class="drawer-diagnosis">${seen.length ? facts(seen, 'diagnosis-facts') : ''}
    <p>${badge(label, kind)} <span>${esc(d.summary || '')}</span></p>
    ${signals ? `<ul>${signals}</ul>` : ''}${aiHtml(d.ai)}</div>`;
}
// The explainer's answer when the deterministic verdict was unclear: a model's
// reading of the same evidence, labelled as such and never a result.
function aiHtml(ai){
  if (!ai || !ai.explanation) return '';
  const [label] = VERDICT[ai.cause] || VERDICT.unclassified;
  return `<p class="ai-diagnosis">${badge('AI diagnosis · unverified', 'neutral')} <span>${esc(label)}: ${esc(ai.explanation)}${ai.next_step ? ` <em>${esc(ai.next_step)}</em>` : ''}</span></p>`;
}
// "Step 3.5 · Test responsive layout" and the chain of groups it ran in.
const stepTitle = s => `${s.id ? `Step ${esc(s.id)} · ` : ''}${stepText(s)}`;
const asCheck = w => ({name: w.check, detail: w.detail, severity: w.severity});
// A finding merged across steps links each one: "Step 3.2 · 4.1 · 5".
const findingLinks = w => [w.step, ...(w.also || [])].map(id =>
  `<button class="link-btn" data-show-step="${esc(id)}">${id === w.step ? 'Step ' : ''}${esc(id)}</button>`).join('');
// A finding as a scannable block: severity icon · headline and one row per affected
// element (selector in monospace, then what the evidence shows) · the step link in
// its own column, so it never reads as part of the sentence.
function findingBlock(c, kind, links){
  const f = describeFinding(c);
  const rows = f.rows.map(r => `<li>${r.code ? badge(esc(r.code), 'info') : ''}${r.text ? `<span>${esc(r.text)}</span>` : ''}</li>`).join('')
    + (f.more ? `<li class="fmore">+${f.more} more</li>` : '');
  return `<div class="finding ${kind}">${icon(kind === 'error' ? 'x' : kind === 'info' ? 'info' : 'warn', 'ficon')}
    <div class="fbody"><p class="ftitle">${esc(f.title)}</p>${rows ? `<ul class="frows">${rows}</ul>` : ''}</div>
    ${links ? `<div class="flink">${links}</div>` : ''}</div>`;
}
function stepPath(t, s){
  const by = (t._byId ||= Object.fromEntries((t.steps || []).map(x => [x.id, x]))), names = [];   // steps never change
  for (let p = by[s.parent]; p; p = by[p.parent]) names.unshift(p.action ? actionLabel(p.action) : p.name);
  return names.join(' › ');
}
function reasonHtml(t, s){
  // What happened, in plain words: each failed check as a finding block, else
  // the step's own error explained. Never reworded to hide a failure.
  const checks = failedChecks(s);
  if (!checks.length) return `<p class="drawer-why">${esc(explain(t, s))}</p>`;
  return `<div class="fail-checks">${checks.slice(0, 5).map(c => findingBlock(c, 'error', '')).join('')}
    ${checks.length > 5 ? `<p class="note">+${checks.length - 5} more under Diagnostics</p>` : ''}</div>`;
}
// A step's screenshots as [kind, path]: evidence shots, else the step's attachment.
const shotList = s => { const e = Object.entries((s.evidence || {}).screenshots || {}).filter(([, p]) => p);
  return e.length ? e : s.attachment ? [['viewport', s.attachment]] : []; };
function shotsHtml(s){
  const shots = shotList(s);
  const main = shots.find(([k]) => k === 'viewport') || shots[0];
  if (!main) return '<p class="note">No screenshot was captured for this step.</p>';
  return `<div class="drawer-shots">${imgLink(main[1], EV_KIND[main[0]] || main[0], 'main')}
    ${shots.filter(x => x !== main).map(([k, p]) => imgLink(p, EV_KIND[k] || k, 'small')).join('')}</div>`;
}
function wentWrongHtml(t){
  // One card per failure site (a failed step with nothing failed inside), in the order they ran.
  const sites = failureSites(t);
  if (!sites.length) return section('What went wrong', `<p class="drawer-why">${esc(explain(t))}</p>`, null, 'bad');
  return section('What went wrong', sites.map(s => {
    const path = stepPath(t, s);
    return `<div class="fail-card">
      <p class="fail-where">${icon('x')}<span>${stepTitle(s)}${path ? `<span class="fail-path">in ${esc(path)}</span>` : ''}</span></p>
      ${reasonHtml(t, s)}${diagnosisHtml(s)}${shotsHtml(s)}
      ${s.id ? `<p class="fail-links"><button class="link-btn" data-show-step="${esc(s.id)}">Show in steps</button>
        <button class="link-btn" data-show-tech="${esc(s.id)}">Error details</button></p>` : ''}</div>`;
  }).join(''), sites.length > 1 ? sites.length : null, 'bad');
}
function warningsHtml(t){
  // Findings that did not fail the test (warn checks, automatic checks in warn
  // mode), each linked to the step that recorded it.
  // An error-severity check only recorded (ORACLE=warn) is marked red: the
  // closest thing to a failure; the rest are amber.
  const ws = t.warnings || [];
  if (!ws.length) return '';
  return section('Warnings', `<div class="warn-list">${ws.map(w =>
    findingBlock(asCheck(w), w.severity === 'error' ? 'error' : 'warn', findingLinks(w))).join('')}</div>`, ws.length, 'warn');
}
function unverifiedHtml(t){
  // Checks the agent could not judge (a control it could not press, a page it
  // could not read, a time limit): coverage gaps, not application defects.
  const us = t.unverified || [];
  if (!us.length) return '';
  return `<div><h4 class="sub-title">Not verified</h4>
    <p class="note">The agent could not judge these — gaps in coverage, not defects in the application.</p>
    <div class="warn-list unverified">${us.map(u => `<div class="finding skip">${icon('skip', 'ficon')}
      <div class="fbody"><p class="ftitle">Could not verify ${esc(u.check)}</p>${u.detail ? `<ul class="frows"><li><span>${esc(u.detail)}</span></li></ul>` : ''}</div>
      <div class="flink">${findingLinks(u)}</div></div>`).join('')}</div></div>`;
}
function factsHtml(t){   // the result is the header badge; the device leads with its profile icon
  const p = t.profile || {}, rest = String(p.label || '').split(' · ').filter(x => x && x !== p.name).join(' · ');
  const device = p.name ? `<span class="fact-device">${deviceIcon(p.name)}${esc(rest)}</span>` : '';
  return `<section class="drawer-section">${factStrip([
    ['Duration', esc(fmtMs(t.duration_ms))],
    ['Started', t.started_at ? esc(new Date(t.started_at).toLocaleTimeString()) : ''],
    ['Suite', esc(suiteTitle(t))], ['Area', esc(areaLabel(areaOf(t)))],
    ['Device', device], ['Reruns', t.retries ? String(t.retries) : ''],
    ['Not verified', (t.unverified || []).length ? `${(t.unverified || []).length} <span class="tech-hint">see Diagnostics</span>` : ''],
    ['First attempt', t.retry_error ? `${t.retry_verdict ? badge((VERDICT[t.retry_verdict] || VERDICT.unclassified)[0], (VERDICT[t.retry_verdict] || VERDICT.unclassified)[1]) + ' ' : ''}<span class="tech-hint">${esc(t.retry_error)}</span>` : ''],
    ['Tags', (t.markers||[]).map(m => badge(esc(m))).join(' ')],
  ])}${goalHtml(t)}</section>`;
}
// The flow's `## Expected Outcome`: what the test is meant to prove, read before the steps.
function goalHtml(t){
  const lines = t.expected || [];
  if (!lines.length) return '';
  return `<dl class="case-facts goal-facts"><dt>Expected outcome</dt><dd><ul>${lines.map(x => `<li>${esc(x)}</li>`).join('')}</ul></dd></dl>`;
}
function agentHtml(t){
  // Autonomous run facts (test_page / explore_page): what the agent saw,
  // planned, skipped, and left behind. Same label-and-value layout as the
  // rest of the drawer; each value is compact rows — a name, a count, the
  // controls or steps in monospace — instead of a paragraph. Lists are data
  // from the run.
  const a = t.agent;
  if (!a) return '';
  const codes = xs => xs.map(x => badge(esc(x), 'info')).join('');
  const rows = (items, row, cls = '') => items && items.length ? `<ul class="arows ${cls}">${items.map(row).join('')}</ul>` : '';
  // "buttons: 3 (Request Info, LOG IN)" / "form 'Contact': 3 fields" / "tables: 1"
  const component = x => {
    let m;
    if ((m = x.match(/^form '(.*)': (\d+) fields?$/))) return `<li><span class="akey">form</span>${badge(esc(m[1]), 'info')}<span class="anum">${esc(m[2])} fields</span></li>`;
    if ((m = x.match(/^([\w ]+?): (\d+)(?: \((.*)\))?$/))) return `<li><span class="akey">${esc(m[1])}</span><span class="anum">${esc(m[2])}</span>${m[3] ? codes(m[3].split(', ')) : ''}</li>`;
    return `<li><span>${esc(x)}</span></li>`;
  };
  const planStep = x => { const ai = /^\[ai\]\s*/.test(x); return `<li>${ai ? badge('AI', 'neutral', 'A step the planner added') : ''}<span>${esc(x.replace(/^\[ai\]\s*/, ''))}</span></li>`; };
  // "Delete member — name contains 'delete'" → the control, then the policy's reason
  const heldBack = x => { const m = x.match(/^(.*?) — (.*)$/s); return `<li>${icon('skip', 'aicon')}${m ? `${badge(esc(m[1]), 'info')}<span>${esc(m[2])}</span>` : `<span>${esc(x)}</span>`}</li>`; };
  const rejected = x => { const m = x.match(/^(\w+): (.*)$/s); return `<li>${icon('x', 'aicon')}${m ? `${badge(esc(m[1]), 'info')}<span>${esc(m[2])}</span>` : `<span>${esc(x)}</span>`}</li>`; };
  const actions = a.actions || [], shown = actions.slice(0, 8);
  return section('Autonomous run', facts([
    ['Page type', a.page_type ? badge(esc(a.page_type)) + (a.classification ? ` <span class="tech-hint">${esc(a.classification)}</span>` : '') : ''],
    ['Components', rows(a.components, component)],
    ['Plan', rows(a.plan, planStep, 'plan')],
    ['Rejected plan steps', rows(a.plan_rejected, rejected, 'bad')],
    ['Skipped for safety', rows(a.skipped, heldBack, 'warn')],
    ['Suggested assertions', rows(a.assertions, x => `<li>${badge(esc(x), 'info')}</li>`)],
    ['Actions executed', actions.length ? `<div class="arows"><span class="anum">${actions.length}</span>${codes(shown)}${actions.length > shown.length ? `<span class="amore">+${actions.length - shown.length} more</span>` : ''}</div>` : ''],
    ['AI calls', a.ai_calls != null ? String(a.ai_calls) : ''],
    ['Generated flow', a.generated ? `<a href="${esc(a.generated)}" target="_blank" rel="noopener">${esc(a.generated)}</a> <span class="tech-hint">— review it, then add it to the suite</span>` : ''],
  ], 'agent-facts'));
}

/* ── steps ── */
function stepTree(steps){
  // flat depth-annotated list → nested tree
  const root = {children: []}, stack = [root];
  steps.forEach(s => {
    while (stack.length - 1 > (s.depth || 0)) stack.pop();
    const node = {step: s, children: []};
    stack[stack.length - 1].children.push(node);
    stack.push(node);
  });
  return root.children;
}
function stepShots(s){
  // A passed step's own screenshots (a `screenshot` step, a skill's viewports);
  // a failed step's are on its card under What went wrong.
  if (s.status === 'failed') return '';
  const paths = shotList(s).map(([, p]) => p);
  return paths.length ? `<div class="sthumbs">${paths.map(p => `<a href="${esc(p)}" target="_blank" rel="noopener"><img src="${esc(p)}" alt="Step screenshot" loading="lazy"></a>`).join('')}</div>` : '';
}
function stepLine(s, kids){
  const heal = s.layer > 1 && s.status === 'passed'
    ? iconBadge('zap', 'warning', `Self-healed: found by the ${s.layer === 3 ? 'AI' : 'fuzzy-match'} fallback (layer ${s.layer})`) : '';
  const what = s.action ? `<span class="sverb" title="${esc(s.action)}">${esc(actionLabel(s.action))}</span>${s.args ? `<span class="sargs">${esc(s.args)}</span>` : ''}`
    : `<span class="sverb">${esc(s.name)}</span>`;
  return `<div class="sline">${what}${heal}${kids ? `<span class="skids">${plural(kids, 'step')}</span>` : ''}</div>`;
}
// Every step row shares one grid: expand control · status · step number · action
// and details · duration. A leaf keeps an empty expand cell so the columns line
// up whether or not the step can open; children indent under the row, not in it.
function stepRow(s, st, site, body, expandable){
  const ico = icon(st === 'failed' ? 'x' : st === 'skipped' ? 'skip' : st === 'warned' ? 'warn' : 'check', `sicon ${st}`);
  const toggle = expandable ? icon('chev', 'toggle-icon stoggle') : '<span class="stoggle"></span>';
  return `${toggle}${ico}<span class="slabel">Step ${esc(s.id || '')}</span><div class="smain">${body}</div><span class="sdur">${fmtMs(s.duration_ms)}</span>`;
}
function stepNode(t, n, look){
  const s = n.step, site = look.sites.has(s);
  // A passed step with warnings shows them under it (the same entries as the
  // Warnings section); its status stays passed.
  const warns = look.warns.get(s.id) || [];
  const st = s.status === 'passed' && warns.length ? 'warned' : s.status;
  const at = s.id ? ` data-step="${esc(s.id)}"` : '';
  // The failure site says why in one line; its parents are failed only because of it.
  const reason = site ? explain(t, s) : '';
  const why = (site ? `<div class="serr" title="${esc(reason)}">${esc(reason)}</div>` : '')
    + warns.map(w => { const f = findingLine(asCheck(w));
        return `<div class="swarn${w.severity === 'error' ? ' err' : ''}" title="${esc(findingText(asCheck(w)))}">${esc(f)}</div>`; }).join('');
  if (n.children.length){
    // Open on the way to a failure or a warning inside; everything else folds.
    const open = (st === 'failed' && !site) || look.under.has(s.id);
    return `<details class="sgroup ${st}${site ? ' site' : ''}"${at}${open ? ' open' : ''}>
      <summary class="srow">${stepRow(s, st, site, stepLine(s, n.children.length) + why, true)}</summary>
      <div class="sgroup-body">${stepShots(s)}<div class="steps">${n.children.map(c => stepNode(t, c, look)).join('')}</div></div></details>`;
  }
  return `<div class="srow ${st}${site ? ' site' : ''}"${at}>${stepRow(s, st, site, stepLine(s, 0) + why + stepShots(s), false)}</div>`;
}
function stepsHtml(t){
  if (!(t.steps||[]).length) return '<p class="empty-inline">No steps recorded for this test.</p>';
  // Lookups built once per drawer: failure sites, warnings by step, and the
  // groups a warning sits under (they open) — O(1) per step afterwards.
  const look = {sites: new Set(failureSites(t)), warns: new Map(), under: new Set()};
  for (const w of t.warnings || []) for (const id of [w.step, ...(w.also || [])]){
    look.warns.set(id, [...(look.warns.get(id) || []), w]);
    const parts = String(id).split('.');
    for (let i = 1; i < parts.length; i++) look.under.add(parts.slice(0, i).join('.'));
  }
  return `<div class="steps">${stepTree(t.steps).map(n => stepNode(t, n, look)).join('')}</div>`;
}

/* ── technical details ── */
function failureTechHtml(t){
  // Per failed step: its full error and what each layer, the page and the
  // browser showed — headed with the same "Step 3.5" as its card and row.
  return failureSites(t).map(s => `<div class="tech-step" data-tech="${esc(s.id)}">
    <h4 class="sub-title">${stepTitle(s)}</h4>
    ${(text => text ? `<pre class="drawer-error">${esc(text)}</pre>` : '')([s.error || '', ...failedChecks(s).map(findingText)].filter(Boolean).join('\n'))}
    ${evidenceHtml(s.evidence)}</div>`).join('');
}
function outputHtml(t){
  const e = t.error || {};
  return e.traceback ? `<details class="fullout"><summary>${badge('Full test output')}</summary><pre class="drawer-error">${esc(e.traceback)}</pre></details>` : '';
}
function evidenceHtml(ev){
  // What each layer did, where the page was, and what the browser logged
  // while the step ran.
  if (!ev) return '';
  const layers = Object.entries(ev.layers || {}).map(([k, v]) =>
    badge(`${esc(k)}: ${esc(v)}`, v === 'failed' ? 'danger' : /^(ok|passed|resolved)/.test(v) ? 'success' : 'neutral')).join('');
  const links = [ev.trace ? `<a href="${esc(ev.trace)}" download title="Open with: npx playwright show-trace <file>">${icon('download')}Playwright trace</a>` : '',
    ...Object.entries(ev.files || {}).map(([k, p]) => `<a href="${esc(p)}" target="_blank" rel="noopener">${icon('file')}${esc(k)}</a>`)].join('');
  const cons = ev.console || [], net = ev.network || [];
  const rows = [...cons, ...net.map(netAsConsole)].map(c => conRowHtml(c, null));
  return `${layers ? `<div><h4 class="sub-title">How the step was attempted</h4><div class="layer-list">${layers}</div></div>` : ''}
    ${ev.url || ev.title ? `<div><h4 class="sub-title">Page at the failure</h4>${facts([
      ['Address', ev.url ? `<a href="${esc(ev.url)}" target="_blank" rel="noopener">${esc(ev.url)}</a>` : ''],
      ['Title', esc(ev.title || '')], ['Device', esc(ev.profile || '')]])}</div>` : ''}
    ${links ? `<div class="links">${links}</div>` : ''}
    ${rows.length ? `<div><h4 class="sub-title">Logged during the step</h4><div class="loglist">${rows.join('')}</div></div>` : ''}`;
}
function relatedHtml(t){
  if (!failedLike(t.status)) return '';
  const fs = failedStep(t);
  const from = fs && fs.ts != null ? fs.ts - 2000 : t.t0 != null ? t.t0 + Math.max(t.duration_ms - 10000, 0) : null;
  if (from == null) return '';
  const end = t.t0 != null ? t.t0 + t.duration_ms + 2000 : Infinity;
  const cons = (t.console || []).filter(c => lvlOf(c) === 'error' && c.ts >= from && c.ts <= end).slice(-5);
  const net = (t.network || []).filter(n => failedReq(n) && n.ts >= from && n.ts <= end).slice(-5);
  if (!cons.length && !net.length) return '';
  // failed requests reuse the console row shape: level "net", text = request + outcome
  return `<div><h4 class="sub-title">Browser activity near step ${esc(fs && fs.id || '')}</h4>
    <p class="note">Hints for troubleshooting, not a confirmed cause.</p><div class="relbox">
    ${[...cons, ...net.map(netAsConsole)].map(c => conRowHtml(c, t.t0)).join('')}</div></div>`;
}
function healHtml(t){
  const h = t.healings || [];
  if (!h.length) return '';
  return `<div><h4 class="sub-title">Self-healed steps</h4><p class="note">Resolved by a fallback locator at runtime — update the flow.</p>
    ${facts(h.map(e => [`Layer ${e.layer}`, `${esc(e.description)}<br><span class="tech-hint">${esc(e.healed_by)} → ${esc(e.resolved)}</span>`]))}</div>`;
}

let lastFocus = null;
let drawerSeq = 0;   // ignore shard arrivals for a test the user has left
function openTest(i){
  const seq = ++drawerSeq;   // a shard still loading for the previous test must not land here
  const t = T[i], st = effStatus(t), fail = failedLike(t.status);
  const loading = '<p class="empty-inline">Loading…</p>';
  const drawer = $('drawer');
  if (!drawer.classList.contains('show')) lastFocus = document.activeElement;
  drawer.innerHTML = `
    <header class="side-drawer-head">
      <div class="side-drawer-tags">${statusBadge(st)}${badge(esc(areaLabel(areaOf(t))))}</div>
      <h2 class="side-drawer-title" id="dtitle">${titleOf(t)}</h2>
      <p class="side-drawer-path">${esc(t.file)}${t.name !== (t.title || t.name) ? ' › ' + esc(t.name) : ''}</p>
      <button class="side-drawer-close" aria-label="Close details">${icon('close')}</button>
    </header>
    <div class="side-drawer-body">
      ${factsHtml(t)}
      ${fail ? wentWrongHtml(t) : ''}
      ${warningsHtml(t)}
      ${agentHtml(t)}
      ${section('Steps', stepsHtml(t), (t.steps || []).filter(s => !s.depth).length || null)}
      ${section('Diagnostics', [fail ? failureTechHtml(t) + outputHtml(t) : '', unverifiedHtml(t),
        fail ? `<div id="d-rel">${hasDetail(t) ? relatedHtml(t) : ''}</div>` : '', healHtml(t)].filter(Boolean).join(''), null, 'tech')}
      <section class="drawer-section"><div class="subtabs" role="tablist">
          <button class="qa-tab-btn" role="tab" data-t="d-con">Console<span class="count">${(t.counts || {}).console || 0}</span></button>
          <button class="qa-tab-btn" role="tab" data-t="d-net">Network<span class="count">${(t.counts || {}).network || 0}</span></button></div>
        <div class="dpane" id="d-con">${hasDetail(t) ? consolePaneHtml(t) : loading}</div>
        <div class="dpane" id="d-net">${hasDetail(t) ? netPaneHtml(t) : loading}</div></section>
    </div>`;
  // Console shows first; Network on its tab. Both are there as soon as the drawer opens.
  const tabs = [...drawer.querySelectorAll('[data-t]')];
  const activate = tab => {
    tabs.forEach(x => { x.classList.toggle('active', x === tab); x.setAttribute('aria-selected', x === tab); });
    drawer.querySelectorAll('.dpane').forEach(x => x.classList.toggle('active', x.id === tab.dataset.t));
  };
  activate(tabs[0]);
  tabs.forEach(tab => tab.onclick = () => activate(tab));
  drawer.querySelector('.side-drawer-close').onclick = closeDrawer;
  drawer.querySelectorAll('[data-show-step]').forEach(b => b.onclick = () => focusIn(drawer, `[data-step="${CSS.escape(b.dataset.showStep)}"]`));
  drawer.querySelectorAll('[data-show-tech]').forEach(b => b.onclick = () => focusIn(drawer, `[data-tech="${CSS.escape(b.dataset.showTech)}"]`));
  if (hasDetail(t)) wireDrawerPanes(t);
  else {
    loadDetail(i).then(() => {
      if (seq !== drawerSeq) return;
      if ($('d-rel')) $('d-rel').innerHTML = relatedHtml(t);
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
function focusIn(drawer, selector){
  // Unfold the way to the element (a step row, a step's technical details) and show it.
  const target = drawer.querySelector(selector);
  if (!target) return;
  // open the groups around it, not the target's own body
  for (let d = target.parentElement.closest('details'); d; d = d.parentElement.closest('details')) d.open = true;
  drawer.querySelectorAll('.step-focus').forEach(x => x.classList.remove('step-focus'));
  target.classList.add('step-focus');
  target.tabIndex = -1;
  target.focus({preventScroll: true});      // keyboard users land where they were sent
  target.scrollIntoView({block: 'center', behavior: 'smooth'});
}
function closeDrawer(){
  if (!$('drawer').classList.contains('show')) return;
  drawerSeq++;
  $('drawer').classList.remove('show');
  $('overlay').classList.remove('show');
  document.body.classList.remove('drawer-open');
  if (lastFocus && lastFocus.focus) lastFocus.focus();
}
$('overlay').onclick = closeDrawer;
