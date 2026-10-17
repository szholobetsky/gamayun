// Gamayun UI — vanilla JS, no build step. Strings of the interface come from t() (i18n.js).
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

async function api(path, body) {
  const res = await fetch(path, body === undefined ? {} : {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.error) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

function project() { return $('project').value; }

// ── tabs ─────────────────────────────────────────────
function showTab(name) {
  document.querySelectorAll('.tab').forEach(b => b.classList.toggle('active', b.dataset.tab === name));
  document.querySelectorAll('.panel').forEach(p => p.classList.toggle('active', p.id === 'tab-' + name));
  if (name === 'projects') loadProjects();
}
document.querySelectorAll('.tab').forEach(b => b.onclick = () => showTab(b.dataset.tab));

// ── theme ────────────────────────────────────────────
// The same eight themes as vyrii and alkonost (ui/themes/*.css); "Gamayun" is the default
// palette of style.css, light or dark with the system.
const THEMES = ['gamayun', 'ocean', 'dark', 'light', 'soft', 'summer', 'beach', 'mono-dark', 'mono-light'];
const themeTitle = n => n === 'gamayun' ? t('theme_auto') : n.split('-').map(w => w[0].toUpperCase() + w.slice(1)).join(' ');
function setTheme(name) {
  const link = $('theme-link');
  if (name === 'gamayun') { link.disabled = true; link.removeAttribute('href'); document.documentElement.removeAttribute('data-theme'); }
  else { link.href = `/ui/themes/${name}.css`; link.disabled = false; document.documentElement.setAttribute('data-theme', name); }
  try { localStorage.setItem('gamayun-theme', name === 'gamayun' ? '' : name); } catch {}
  $('theme').value = name;
}
function fillThemes() {
  let cur = '';
  try { cur = localStorage.getItem('gamayun-theme') || ''; } catch {}
  $('theme').innerHTML = THEMES.map(n => `<option value="${n}">${esc(themeTitle(n))}</option>`).join('');
  $('theme').value = THEMES.includes(cur) ? cur : 'gamayun';
}
fillThemes();
$('theme').onchange = () => setTheme($('theme').value);

// ── language ─────────────────────────────────────────
$('lang').innerHTML = LANGS.map(([c, label]) => `<option value="${c}">${esc(label)}</option>`).join('');
$('lang').value = LANG;
$('lang').onchange = () => setLang($('lang').value);

// ── projects ─────────────────────────────────────────
// One project at a time: every tab asks the server about the chosen project only, and
// switching clears whatever the previous project left on screen.
let projects = [];
let startDir = '';
async function loadProjects() {
  const data = await api('/api/projects');
  projects = data.projects;
  startDir = data.start || '';
  renderProjects();
}

function renderProjects() {
  const sel = $('project');
  let keep = sel.value;
  if (!keep) { try { keep = localStorage.getItem('gamayun.project') || ''; } catch {} }
  sel.innerHTML = `<option value="">${esc(t('select_project'))}</option>` +
    projects.map(p => `<option value="${esc(p.project)}">${esc(p.project)}${p.where === 'home' ? esc(t('home_suffix')) : ''}</option>`).join('');
  sel.value = projects.some(p => p.project === keep) ? keep : '';
  $('project-list').innerHTML = projects.length ? projects.map(projectCard).join('')
    : `<p class="dim">${t('no_projects')}</p>`;
  renderScope();
}

function renderScope() {
  const p = projects.find(x => x.project === project());
  $('scope').innerHTML = p
    ? t('scope_on', { p: esc(p.project), dir: esc(p.dir) }) +
      (p.where === 'home' ? ` <span class="tag">${esc(t('tag_home'))}</span>` : '')
    : (startDir ? t('scope_choose_start', { dir: esc(startDir) }) : t('scope_choose'));
  document.querySelectorAll('#project-list .card').forEach(c => c.classList.toggle('current', c.dataset.p === project()));
  if (typeof renderGuideCounts === 'function') renderGuideCounts();
}

function clearProjectViews() {
  ['terms', 'modules', 'files', 'symbols', 'entity-out', 'comp-out', 'h-out', 'h-units'].forEach(id => { $(id).innerHTML = ''; });
  ['search-status', 'comp-status', 'h-status'].forEach(id => { $(id).textContent = ''; });
  $('compass').hidden = true; $('compass').innerHTML = '';
  $('symbols-box').hidden = true;
  $('entity-guide').open = true;
}

function selectProject(name) {
  if ($('project').value !== name) $('project').value = name;
  try { localStorage.setItem('gamayun.project', name); } catch {}
  const u = new URL(location.href);
  if (name) u.searchParams.set('project', name); else u.searchParams.delete('project');
  u.searchParams.delete('q');
  history.replaceState(null, '', u);
  clearProjectViews();
  renderScope();
}
$('project').onchange = () => selectProject(project());
$('refresh').onclick = () => loadProjects();

function projectCard(p) {
  const st = p.stats || {}, preds = st.predicates || {};
  const total = Object.values(preds).reduce((a, b) => a + b, 0);
  const r = p.results && p.results.test;
  const metrics = r ? `<table class="metrics"><tr><th>${esc(t('th_test', { n: p.results.test_tasks }))}</th>
      <th>MAP</th><th>MRR</th><th>P@1</th><th>R@10</th><th>hit@10</th></tr>` +
    Object.entries(r).map(([k, m]) => `<tr><td>${esc(k)}</td><td>${m.AP}</td><td>${m.RR}</td>
      <td>${m['P@1']}</td><td>${m['R@10']}</td><td>${m['hit@10'] ?? ''}</td></tr>`).join('') + '</table>' : '';
  const params = p.results && p.results.params
    ? `<div class="dim">${esc(t('tuned', { m: JSON.stringify(p.results.params.module), f: JSON.stringify(p.results.params.file) }))}</div>` : '';
  const size = st.train_tasks != null ? t('n_tasks', { n: st.train_tasks }) : t('n_units', { n: st.units });
  return `<div class="card${p.project === project() ? ' current' : ''}" data-p="${esc(p.project)}">
    <h3>${esc(p.project)}${p.where === 'home' ? `<span class="tag">${esc(t('tag_home'))}</span>` : ''}
      <button class="small" onclick="selectProject(${esc(JSON.stringify(p.project))}); showTab('search')">${esc(t('open'))}</button></h3>
    <div class="dim">${esc(t('kept_in', { dir: p.dir }))}</div>
    <div class="dim">${esc(t('card_line', { size, tr: total, m: st.modules, f: st.files,
      params: p.tuned ? t('tuned_params') : t('default_params') }))}</div>
    <div class="dim">${esc(p.source.db || p.source.files || '')} ${p.source.repo ? '· ' + esc(p.source.repo) : ''}
      ${p.source.built ? esc(t('built_at', { d: p.source.built })) : ''}</div>
    <div class="dim">${Object.entries(preds).map(([k, v]) => `${esc(k)} ${v}`).join(' · ')}</div>
    ${params}${metrics}
    <div class="row" ${p.source.files ? 'hidden' : ''}><button class="small" onclick="runEval('${esc(p.project)}')"
      ${p.busy ? 'disabled' : ''}>${esc(p.busy ? t('running') : t('evaluate'))}</button></div>
  </div>`;
}

async function pollJob(jid) {
  const log = $('job-log');
  log.hidden = false;
  while (true) {
    const j = await api('/api/jobs/' + jid);
    log.textContent = j.log.join('\n') + (j.error ? '\n' + j.error : '');
    log.scrollTop = log.scrollHeight;
    if (j.status !== 'running') { loadProjects(); return j; }
    await new Promise(r => setTimeout(r, 1000));
  }
}

$('b-go').onclick = async () => {
  try {
    const name = $('b-project').value.trim();
    const { job } = await api('/api/build', { project: name,
      db: $('b-db').value.trim(), repo: $('b-repo').value.trim(), files: $('b-files').value.trim(),
      root: $('b-root').value.trim() });
    const j = await pollJob(job);
    if (j.status === 'done') selectProject(name);
  } catch (e) { $('job-log').hidden = false; $('job-log').textContent = e.message; }
};

async function runEval(name) {
  try { const { job } = await api('/api/eval', { project: name, test: true }); loadProjects(); await pollJob(job); }
  catch (e) { $('job-log').hidden = false; $('job-log').textContent = e.message; }
}

// ── search ───────────────────────────────────────────
function entLink(name) {
  return `<a class="ent" onclick="openEntity(${esc(JSON.stringify(name))})">${esc(name)}</a>`;
}

function evidenceTable(ev) {
  if (!ev.length) return `<div class="dim">${esc(t('no_term_evidence'))}</div>`;
  return `<table class="ev">${ev.map(e => `<tr>
    <td class="v ${e.value < 0 ? 'neg' : 'pos'}">${e.value > 0 ? '+' : ''}${e.value.toFixed(3)}</td>
    <td>${esc(e.kind)}</td><td>${entLink('term:' + e.term)}</td><td><code>${esc(e.triple)}</code></td></tr>`).join('')}</table>`;
}

function resultItem(r, prefix) {
  const why = r.evidence.slice(0, 4).map(e => `${e.term}${prefix === 'file:' ? '/' + e.kind : ''} ` +
    `${e.value > 0 ? '+' : ''}${e.value.toFixed(2)}`).join(', ');
  const extra = r.co_change_bonus ? `<div class="dim">${esc(t('cochange_bonus', { n: r.co_change_bonus }))}</div>` : '';
  return `<li><details class="res"><summary><span class="target">${esc(r.target)}</span>
      <span class="score">${r.score ?? ''}</span></summary>
      <div class="dim">${r.prior != null ? esc(t('prior', { p: r.prior, n: r.task_count })) + ' · ' : ''}${entLink(prefix + r.target)}</div>
      ${extra}${evidenceTable(r.evidence)}</details>
      <div class="why">${esc(why)}</div></li>`;
}

// ── compass ──────────────────────────────────────────
const fileName = f => f.split('/').pop();
let lastCompass = null;

function renderCompass(c) {
  lastCompass = c;
  const box = $('compass');
  box.hidden = false;
  box.className = 'compass ' + c.confidence;
  let head;
  if (c.source === 'anchor') {
    head = t(c.anchor_files === 1 ? 'compass_anchor_1' : 'compass_anchor_n', { a: esc(c.anchor), n: c.anchor_files });
  } else if (c.source === 'ontology') {
    head = esc(t('compass_ontology'));
  } else {
    head = esc(t('compass_none'));
  }
  const repoNote = c.repo ? '' : ` <span class="dim">${esc(t('compass_no_repo'))}</span>`;
  const items = (c.candidates || []).map(x => `<li>${entLink('file:' + x.file)}
      ${x.line ? `<div class="line">${esc(t('compass_line', { n: x.line, text: x.text }))}</div>` : `<div class="why">${esc(x.why)}</div>`}</li>`).join('');
  const comp = (c.companions || []).length
    ? `<div class="why">${esc(t('compass_with_first'))} ${c.companions.map(f =>
        `<a class="ent" title="${esc(f)}" onclick="openEntity(${esc(JSON.stringify('file:' + f))})">${esc(fileName(f))}</a>`).join(', ')}</div>` : '';
  const area = c.area ? `<div class="why">${esc(t('compass_area'))} <code>${esc(c.area.dir)}</code></div>` : '';
  const low = c.confidence === 'low' ? `<div class="why">${esc(t('compass_low'))}</div>` : '';
  box.innerHTML = `<div class="head"><b>${esc(t('compass'))}</b><span class="badge ${esc(c.confidence)}">${esc(t('conf_' + c.confidence))}</span>
      <span>${head}</span>${repoNote}</div>${items ? `<ol>${items}</ol>` : ''}${comp}${area}${low}`;
}

async function runCompass(text) {
  const p = project();
  try {
    const res = await api('/api/compass', { project: p, text, k: 5 });
    if (project() === p) renderCompass(res);                // the user may have switched meanwhile
  } catch (e) {
    if (project() !== p) return;
    $('compass').hidden = false;
    $('compass').className = 'compass';
    $('compass').innerHTML = `<b>${esc(t('compass'))}</b> <span class="err">${esc(e.message)}</span>`;
  }
}

// ── health ───────────────────────────────────────────
const ZONES = ['evolution', 'maintenance', 'disruption', 'stagnation'];
const zname = z => t('zn_' + z);
const zc = z => `var(--z-${z})`;
const pct = x => `${(100 * x).toFixed(1)}%`;

$('h-scope').onchange = () => { $('h-target').hidden = $('h-scope').value === 'all'; };

function squareHtml(s) {
  const cell = z => `<div class="cell ${s.zone === z ? 'lead' : ''}">
      <div class="name"><span class="sw" style="background:${zc(z)}"></span>${esc(zname(z))} <span>· ${esc(t('zs_' + z))}</span></div>
      <div class="pct">${pct(s[z])}</div><div class="meter"><span style="width:${100 * s[z]}%;background:${zc(z)}"></span></div></div>`;
  return `<div class="square">
      <div></div><div class="ax">${esc(t('ax_across'))}</div><div class="ax">${esc(t('ax_inside'))}</div>
      <div class="ax">${esc(t('ax_novel'))}</div>${cell('disruption')}${cell('evolution')}
      <div class="ax">${esc(t('ax_known'))}</div>${cell('stagnation')}${cell('maintenance')}
    </div>
    <div class="kpis"><span>${esc(t('k_zone'))} <b>${esc(zname(s.zone).toLowerCase())}</b></span><span>${esc(t('k_novelty'))} <b>${s.novelty.toFixed(2)}</b></span>
      <span>${esc(t('k_structurality'))} <b>${s.structurality.toFixed(2)}</b></span><span>SES <b>${s.ses.toFixed(2)}</b></span>
      <span>HES <b>${s.hes.toFixed(2)}</b></span><span>${esc(t('k_tasks_pairs', { t: s.tasks, p: s.pairs.toLocaleString() }))}</span></div>`;
}

// 100% stacked columns, one per period: 2px surface gaps between segments, rounded top end,
// recessive grid, hover tooltip per column; the table below carries every value too
function barsSvg(periods) {
  const W = Math.max(560, periods.length * 26), H = 220, L = 34, B = 26, T = 8;
  const bw = Math.max(6, Math.min(32, (W - L - 8) / periods.length - 4)), step = (W - L - 8) / periods.length;
  const y = v => T + (1 - v) * (H - T - B);
  let s = `<svg width="${W}" height="${H}" role="img" aria-label="${esc(t('chart_aria'))}">`;
  for (const g of [0, 0.25, 0.5, 0.75, 1]) {
    s += `<line x1="${L}" x2="${W - 4}" y1="${y(g)}" y2="${y(g)}" stroke="var(--${g === 0 ? 'axis' : 'grid'})"/>` +
         `<text x="${L - 6}" y="${y(g) + 4}" text-anchor="end">${g * 100}%</text>`;
  }
  const every = Math.ceil(periods.length / Math.floor((W - L) / 56));
  periods.forEach((p, i) => {
    const x = L + i * step + (step - bw) / 2;
    let acc = 0;
    ZONES.forEach((z, k) => {
      const v = p[z];
      if (v <= 0) return;
      const y0 = y(acc + v), h = Math.max(0, y(acc) - y(acc + v) - (acc > 0 ? 2 : 0));
      const top = k === ZONES.length - 1 || ZONES.slice(k + 1).every(zz => p[zz] <= 0);
      s += top ? `<path d="M${x},${y0 + h} v${-(h - 4)} q0,-4 4,-4 h${bw - 8} q4,0 4,4 v${h - 4} z" fill="${zc(z)}"/>`
               : `<rect x="${x}" y="${y0}" width="${bw}" height="${h}" fill="${zc(z)}"/>`;
      acc += v;
    });
    s += `<rect x="${L + i * step}" y="${T}" width="${step}" height="${H - T - B}" fill="transparent" data-i="${i}" class="hit"/>`;
    if (i % every === 0) s += `<text x="${x + bw / 2}" y="${H - 8}" text-anchor="middle">${esc(p.period)}</text>`;
  });
  return s + '</svg>';
}

function bindTips(box, periods) {
  const tip = document.createElement('div');
  tip.className = 'tip';
  tip.hidden = true;
  box.appendChild(tip);
  box.querySelectorAll('.hit').forEach(r => {
    r.addEventListener('mousemove', e => {
      const p = periods[+r.dataset.i];
      tip.innerHTML = t('tip_period', { p: esc(p.period), n: p.tasks }) + ZONES.map(z =>
        `<div class="row2"><span class="sw" style="background:${zc(z)}"></span>${esc(zname(z))} ${pct(p[z])}</div>`).join('');
      const bb = box.getBoundingClientRect();
      tip.style.left = `${Math.min(e.clientX - bb.left + box.scrollLeft + 12, box.scrollWidth - 170)}px`;
      tip.style.top = `${e.clientY - bb.top + 12}px`;
      tip.hidden = false;
    });
    r.addEventListener('mouseleave', () => { tip.hidden = true; });
  });
}

function zoneTable(rows, first, label) {
  return `<table class="h"><tr><th>${esc(label)}</th><th>${esc(t('th_tasks'))}</th>${ZONES.map(z => `<th>${esc(zname(z).toLowerCase())}</th>`).join('')}
      <th>${esc(t('k_novelty'))}</th><th>${esc(t('k_structurality'))}</th><th>${esc(t('th_zone'))}</th></tr>` +
    rows.map(r => `<tr><td>${first(r)}</td><td>${r.tasks}</td>${ZONES.map(z => `<td>${pct(r[z])}</td>`).join('')}
      <td>${r.novelty.toFixed(2)}</td><td>${r.structurality.toFixed(2)}</td><td>${esc(zname(r.zone).toLowerCase())}</td></tr>`).join('') + '</table>';
}

let lastHealth = null;
async function runHealth() {
  if (!project()) { $('h-status').textContent = t('choose_project_first'); return; }
  const p = project(), scope = $('h-scope').value, target = $('h-target').value.trim();
  if (scope !== 'all' && !target) { $('h-status').textContent = t(scope === 'unit' ? 'name_the_unit' : 'name_the_file'); return; }
  $('h-status').textContent = t('computing_history');
  try {
    const t0 = performance.now();
    const res = await api('/api/health', { project: p, by: $('h-by').value, depth: +$('h-depth').value,
      unit: scope === 'unit' ? target : '', file: scope === 'file' ? target : '',
      since: $('h-since').value.trim(), until: $('h-until').value.trim() });
    if (project() !== p) return;                          // switched meanwhile
    lastHealth = { res, scope, target, ms: Math.round(performance.now() - t0) };
    drawHealth();
  } catch (e) {
    if (project() === p) $('h-status').innerHTML = `<span class="err">${esc(e.message)}</span>`;
  }
}

function drawHealth() {
  const { res, scope, target, ms } = lastHealth;
  $('h-status').textContent = t('health_status', { ms, a: res.first, b: res.last, n: res.excluded_large, max: res.params.max_files });
  $('h-units').innerHTML = res.units.map(u => `<option value="${esc(u.unit)}">`).join('');
  const out = $('h-out');
  if (!res.total) { out.innerHTML = `<p class="dim">${esc(t('health_empty'))}</p>`; return; }
  const title = scope === 'all' ? esc(t('whole_code_base')) : esc(t(scope === 'unit' ? 'unit_x' : 'file_x', { x: target }));
  out.innerHTML = `<h2>${title}</h2>${squareHtml(res.total)}
    <h2>${esc(t('by_' + res.params.by))}</h2>
    <div class="legend">${ZONES.map(z => `<span><span class="sw" style="background:${zc(z)}"></span>${esc(zname(z))} — ${esc(t('zd_' + z))}</span>`).join('')}</div>
    <div class="chart" id="h-chart">${barsSvg(res.periods)}</div>
    <details><summary class="dim">${esc(t('table'))}</summary>${zoneTable(res.periods, r => esc(r.period), t('th_period_' + res.params.by))}</details>
    <h2>${esc(res.params.since ? t('units_by_stagnation_since', { d: res.params.since }) : t('units_by_stagnation'))}</h2>
    <p class="dim">${esc(t('units_help'))}</p>
    ${zoneTable(res.units.slice(0, 25), r => `<a class="ent" data-unit="${esc(r.unit)}">${esc(r.unit)}</a>`, t('th_unit'))}
    <h2>${esc(t('snapshots'))}</h2>
    ${res.snapshots.length ? `<table class="h"><tr><th>${esc(t('th_built'))}</th><th>${esc(t('th_history_to'))}</th><th>${esc(t('th_tasks'))}</th>
      <th>${esc(t('k_novelty'))}</th><th>${esc(t('k_structurality'))}</th><th>${esc(t('th_zone'))}</th></tr>${res.snapshots.map(s => `<tr><td>${esc(s.built)}</td><td>${esc(s.last)}</td>
      <td>${s.tasks}</td><td>${s.novelty.toFixed(2)}</td><td>${s.structurality.toFixed(2)}</td><td>${esc(zname(s.zone).toLowerCase())}</td></tr>`).join('')}</table>`
      : `<p class="dim">${t('snapshots_none')}</p>`}`;
  bindTips($('h-chart'), res.periods);
  out.querySelectorAll('a[data-unit]').forEach(a => a.onclick = () => {
    $('h-scope').value = 'unit'; $('h-target').hidden = false; $('h-target').value = a.dataset.unit;
    runHealth(); window.scrollTo({ top: 0, behavior: 'smooth' });
  });
}
$('h-go').onclick = runHealth;

// ── companions ───────────────────────────────────────
let lastComp = null;
async function runCompanions() {
  const text = $('comp-text').value.trim();
  if (!project()) { $('comp-status').textContent = t('choose_project_first'); return; }
  if (!text) return;
  $('comp-status').textContent = t('looking');
  try {
    const t0 = performance.now();
    const p = project();
    const res = await api('/api/companions', { project: p, text, k: +$('comp-k').value || 10 });
    if (project() !== p) return;                          // switched meanwhile: not this project's answer
    lastComp = { res, ms: Math.round(performance.now() - t0) };
    drawCompanions();
  } catch (e) {
    $('comp-status').innerHTML = `<span class="err">${esc(e.message)}</span>`;
  }
}

function drawCompanions() {
  const { res, ms } = lastComp, out = $('comp-out');
  $('comp-status').textContent = t('ms', { n: ms });
  if (!res.chosen.length) { out.innerHTML = `<p class="dim">${esc(t('comp_unknown'))}</p>`; return; }
  const chosen = `<h2>${esc(t('comp_yours', { n: res.chosen.length }))}</h2><ol class="results">${res.chosen.map(f =>
    `<li>${entLink('file:' + f)}</li>`).join('')}</ol>`;
  const list = res.companions.length
    ? `<h2>${esc(t('comp_together'))}</h2><ol class="results">${res.companions.map(r =>
        `<li><details class="res"><summary><span class="target">${esc(r.target)}</span>
           <span class="score">${esc(t('comp_with_of', { n: r.with.length, m: res.chosen.length, g: r.g2 }))}</span></summary>
           <div class="dim">${entLink('file:' + r.target)}</div>
           <table class="ev">${r.triples.map(x => `<tr><td><code>${esc(x)}</code></td></tr>`).join('')}</table></details>
         <div class="why">${esc(t('comp_with', { list: r.with.map(fileName).join(', ') }))}</div></li>`).join('')}</ol>`
    : `<p class="dim">${esc(t('comp_none'))}</p>`;
  out.innerHTML = chosen + list;
}
$('comp-go').onclick = runCompanions;
$('comp-text').addEventListener('keydown', e => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) runCompanions(); });

let lastSearch = null;
async function runSearch() {
  const text = $('query').value.trim();
  if (!project()) { $('search-status').textContent = t('choose_project_first'); return; }
  if (!text) return;
  $('search-status').textContent = t('searching');
  runCompass(text);
  try {
    const t0 = performance.now();
    const p = project();
    const res = await api('/api/search', { project: p, text, k: +$('k').value || 10 });
    if (project() !== p) return;                          // switched meanwhile: not this project's answer
    lastSearch = { res, ms: Math.round(performance.now() - t0) };
    drawSearch();
  } catch (e) {
    $('search-status').innerHTML = `<span class="err">${esc(e.message)}</span>`;
  }
}

function drawSearch() {
  const { res, ms } = lastSearch;
  $('terms').innerHTML = res.terms.map(x =>
    `<span class="chip" onclick="openEntity('term:${esc(x)}')">${esc(x)}</span>`).join('');
  $('modules').innerHTML = res.modules.map(m => resultItem(m, 'module:')).join('');
  $('files').innerHTML = res.files.map(f => resultItem(f, 'file:')).join('');
  $('symbols-box').hidden = !res.symbols;
  $('symbols').innerHTML = (res.symbols || []).map(y => resultItem(y, 'sym:')).join('');
  $('search-status').textContent = t('ms', { n: ms });
}
$('go').onclick = runSearch;
$('query').addEventListener('keydown', e => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) runSearch(); });

// ── entity ───────────────────────────────────────────
function openEntity(name) {
  $('entity-name').value = name;
  showTab('entity');
  loadEntity();
}

let lastEntity = null;
async function loadEntity() {
  const name = $('entity-name').value.trim();
  const out = $('entity-out');
  if (!project()) { out.innerHTML = `<p class="dim">${esc(t('choose_project_first'))}</p>`; return; }
  if (!name) return;
  out.innerHTML = `<p class="dim">${esc(t('loading'))}</p>`;
  try {
    const p = project();
    const res = await api(`/api/entity?project=${encodeURIComponent(p)}&name=${encodeURIComponent(name)}`);
    if (project() !== p) return;                          // switched meanwhile: not this project's answer
    lastEntity = { res, name };
    drawEntity();
    $('entity-guide').open = !res.triples.length;
  } catch (e) { out.innerHTML = `<p class="err">${esc(e.message)}</p>`; }
}

function drawEntity() {
  const { res, name } = lastEntity;
  $('entity-out').innerHTML = res.triples.length
    ? `<p class="dim">${esc(t('triples_n', { n: res.triples.length }))}</p><table class="triples">` +
      res.triples.map(x => `<tr><td>${x.s === name ? esc(x.s) : entLink(x.s)}</td><td class="p">${esc(x.p)}</td>
        <td>${x.o === name || !x.o.includes(':') ? esc(x.o) : entLink(x.o)}</td>
        <td class="src">${esc(x.src)}</td></tr>`).join('') + '</table>'
    : `<p class="dim">${esc(t('no_triples', { x: name }))}</p>`;
}
$('entity-go').onclick = loadEntity;
document.querySelectorAll('#entity-guide a.ex').forEach(a => a.onclick = () => openEntity(a.textContent));

// what the chosen project actually holds: triples per relation, from its build statistics
function renderGuideCounts() {
  const p = projects.find(x => x.project === project());
  const box = $('guide-counts');
  if (!p) { box.textContent = t('choose_project'); return; }
  const st = p.stats || {}, preds = Object.entries(st.predicates || {}).sort((a, b) => b[1] - a[1]);
  const size = st.train_tasks != null ? t('n_tasks', { n: st.train_tasks }) : t('n_units', { n: st.units ?? '?' });
  box.innerHTML = `<p>${esc(t('eg_counts', { p: p.project, src: p.source.db || p.source.files || '?', size,
      m: st.modules ?? '?', f: st.files ?? '?', repo: p.source.repo ? t('eg_repo', { r: p.source.repo }) : '' }))}</p>` +
    (preds.length ? `<table class="guide-t"><tr><th>${esc(t('eg_th_relation'))}</th><th>${esc(t('eg_th_triples'))}</th></tr>${preds.map(([k, v]) =>
      `<tr><td><code>${esc(k)}</code></td><td>${v.toLocaleString()}</td></tr>`).join('')}</table>` : '');
}
$('project').addEventListener('change', renderGuideCounts);
$('entity-name').addEventListener('keydown', e => { if (e.key === 'Enter') loadEntity(); });

// a new language: redraw what JS drew, from the answers already in hand (no new requests)
langHooks.push(() => {
  fillThemes();
  renderProjects();
  if (lastSearch && $('modules').innerHTML) drawSearch();
  if (lastCompass && !$('compass').hidden) renderCompass(lastCompass);
  if (lastHealth && $('h-out').innerHTML) drawHealth();
  if (lastComp && $('comp-out').innerHTML) drawCompanions();
  if (lastEntity && $('entity-out').innerHTML) drawEntity();
});

// ?project=sonar&q=... opens straight to a search (shareable links)
loadProjects().then(() => {
  const u = new URLSearchParams(location.search);
  if (u.get('project') && projects.some(p => p.project === u.get('project'))) $('project').value = u.get('project');
  renderScope();
  if (u.get('q') && project()) { $('query').value = u.get('q'); runSearch(); }
  if (u.get('tab') === 'health' && project()) {            // ?project=sonar&tab=health[&by=month&unit=...]
    showTab('health');
    if (u.get('by')) $('h-by').value = u.get('by');
    if (u.get('unit') || u.get('file')) {
      $('h-scope').value = u.get('unit') ? 'unit' : 'file';
      $('h-target').hidden = false;
      $('h-target').value = u.get('unit') || u.get('file');
    }
    runHealth();
  }
  if (u.get('tab') === 'map' && project()) {               // ?project=sonar&tab=map[&prefix=server&since=2022]
    showTab('map');
    mapFromUrl(u);
  }
  if (['entity', 'companions', 'projects', 'search'].includes(u.get('tab'))) showTab(u.get('tab'));
}).catch(e => { $('search-status').innerHTML = `<span class="err">${esc(e.message)}</span>`; });
