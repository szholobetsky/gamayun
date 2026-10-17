// Gamayun UI — the module map: one layer of the code base at a time, a force layout in plain SVG.
// Nodes = modules (size: tasks, colour: leading zone of their own square), edges = coupling.
(() => {
  const SVGNS = 'http://www.w3.org/2000/svg';
  const W = 1000, H = 640;
  let state = null;                       // {res, nodes, edges, view, hover}
  let prefix = '';

  // "src/main/js/apps" -> "apps"; when two modules share the last name, one more folder is
  // kept ("app/components" vs "components"); the full id is in the tooltip and the side panel
  const short = n => n.short || n.label;
  function shortNames(nodes) {
    const tail = (n, k) => n.label.split('/').slice(-k).join('/');
    for (const n of nodes) n.short = n.own ? n.label : tail(n, 1);
    for (let k = 2; k <= 4; k++) {
      const count = new Map();
      nodes.forEach(n => count.set(n.short, (count.get(n.short) || 0) + 1));
      const dup = nodes.filter(n => !n.own && count.get(n.short) > 1);
      if (!dup.length) break;
      dup.forEach(n => { n.short = tail(n, k); });
    }
  }
  const SRC = () => (state && state.res.source) || 'ontology';
  // task history: the leading zone of the node's square; ontology: cohesion, one hue light -> dark
  const fill = n => n.zone ? `var(--z-${n.zone})`
    : n.cohesion == null ? 'var(--dim)'
    : `color-mix(in oklab, var(--z-evolution) ${Math.round(18 + 82 * n.cohesion)}%, var(--panel))`;
  const kindText = k => t('kind_' + k);
  const unitWord = (src = SRC()) => t('u_' + src);

  // ── layout: Fruchterman–Reingold with gravity and collision, deterministic start ──
  function hash(s) { let h = 2166136261; for (const c of s) h = Math.imul(h ^ c.charCodeAt(0), 16777619); return h >>> 0; }

  // linked modules get the force layout; modules with no link above the thresholds wait in a
  // band at the bottom instead of drifting to the edges and shrinking everything else
  function layout(nodes, edges) {
    const linked = new Set(edges.flatMap(e => [e.source, e.target]));
    const net = nodes.filter(d => linked.has(d.id)), lone = nodes.filter(d => !linked.has(d.id));
    const band = lone.length ? 34 + 34 * Math.ceil(lone.length / 22) : 0;
    const AH = H - band;
    const n = net.length;
    const k = Math.sqrt((W * AH) / Math.max(n, 1)) * 0.75;
    net.forEach(d => {
      const a = (hash(d.id) % 6283) / 1000, r = 60 + (hash(d.id + '#') % 220);
      d.x = W / 2 + r * Math.cos(a); d.y = AH / 2 + r * Math.sin(a) * 0.7;
    });
    const idx = new Map(net.map((d, i) => [d.id, i]));
    const E = edges.map(e => [idx.get(e.source), idx.get(e.target)]);
    let t = W / 10;
    for (let it = 0; it < 500; it++) {
      const dx = new Float64Array(n), dy = new Float64Array(n);
      for (let i = 0; i < n; i++) for (let j = i + 1; j < n; j++) {
        let x = net[i].x - net[j].x, y = net[i].y - net[j].y;
        const d = Math.hypot(x, y) || 0.01;
        let f = (k * k) / d;
        const min = net[i].r + net[j].r + 18;
        if (d < min) f += (min - d) * 6;                         // collision, room for a label
        x /= d; y /= d;
        dx[i] += x * f; dy[i] += y * f; dx[j] -= x * f; dy[j] -= y * f;
      }
      for (const [a, b] of E) {
        let x = net[a].x - net[b].x, y = net[a].y - net[b].y;
        const d = Math.hypot(x, y) || 0.01, f = (d * d) / k * 0.35;
        x /= d; y /= d;
        dx[a] -= x * f; dy[a] -= y * f; dx[b] += x * f; dy[b] += y * f;
      }
      for (let i = 0; i < n; i++) {
        dx[i] += (W / 2 - net[i].x) * 0.06;                      // gravity: small components stay near
        dy[i] += (AH / 2 - net[i].y) * 0.09;
        const d = Math.hypot(dx[i], dy[i]) || 1, s = Math.min(d, t) / d;
        net[i].x += dx[i] * s; net[i].y += dy[i] * s;
      }
      t = Math.max(0.5, t * 0.985);
    }
    if (n) {                                                     // fit into the upper area
      const xs = net.map(d => d.x), ys = net.map(d => d.y);
      const pad = 50, padX = 110, x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
      const s = Math.min((W - 2 * padX) / Math.max(x1 - x0, 1), (AH - 2 * pad) / Math.max(y1 - y0, 1), 1.4);
      net.forEach(d => { d.x = W / 2 + (d.x - (x0 + x1) / 2) * s; d.y = AH / 2 + (d.y - (y0 + y1) / 2) * s; });
    }
    lone.sort((a, b) => b.tasks - a.tasks).forEach((d, i) => {
      const per = 22, row = Math.floor(i / per), col = i % per;
      d.x = 40 + col * ((W - 80) / (per - 1)); d.y = AH + 30 + row * 34;
      d.lone = true;
      d.r = Math.min(d.r, 10);                                   // the band is one row high
    });
    return { band, AH };
  }

  // labels: biggest modules first, a label that would overlap one already placed waits for hover
  function pickLabels(nodes) {
    const boxes = [];
    for (const n of [...nodes].sort((a, b) => b.tasks - a.tasks)) {
      const w = short(n).length * 6.4 + 6, x = n.x - w / 2, y = n.y + n.r + 3;
      const hit = boxes.some(b => x < b.x + b.w && b.x < x + w && y < b.y + 14 && b.y < y + 14) ||
        nodes.some(m => m !== n && Math.hypot(m.x - n.x, m.y - (y + 7)) < m.r + 4);
      n.lab.classList.toggle('minor', hit);
      if (!hit) boxes.push({ x, y, w });
    }
  }

  // ── render ──
  function el(name, attrs, parent) {
    const e = document.createElementNS(SVGNS, name);
    for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
    if (parent) parent.appendChild(e);
    return e;
  }

  function render() {
    const { res, nodes, edges } = state;
    const box = $('m-chart');
    box.innerHTML = '';
    const svg = el('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img', class: 'map-svg',
      'aria-label': t('map_aria', { p: prefix || t('map_top'), n: nodes.length, e: edges.length }) }, box);
    const vp = el('g', {}, svg);
    const gE = el('g', {}, vp), gN = el('g', {}, vp), gL = el('g', { class: 'labels' }, vp);
    const maxE = Math.max(1, ...edges.map(e => e.tasks));
    const byId = new Map(nodes.map(n => [n.id, n]));
    edges.forEach(e => {
      e.a = byId.get(e.source); e.b = byId.get(e.target);
      e.el = el('line', { class: 'edge' + (e.new ? ' new' : '') + (e.kind ? ' k-' + e.kind : ''), 'stroke-width': (1 + 5 * Math.sqrt(e.tasks / maxE)).toFixed(2) }, gE);
    });
    edges.forEach(e => { e.hit = el('line', { class: 'edge-hit' }, gE); });   // wide, invisible: easy to hover
    nodes.forEach(n => {
      n.g = el('g', { class: 'node' + (n.drill ? ' drill' : ''), tabindex: 0 }, gN);
      if (n.drill) el('circle', { r: n.r + 4, class: 'ring' }, n.g);
      el('circle', { r: n.r, fill: fill(n), class: 'dot' }, n.g);
      n.lab = el('text', { class: 'lab', 'text-anchor': 'middle' }, gL);
      n.lab.textContent = short(n);
    });
    const place = () => {
      edges.forEach(e => {
        e.el.setAttribute('x1', e.a.x); e.el.setAttribute('y1', e.a.y);
        e.el.setAttribute('x2', e.b.x); e.el.setAttribute('y2', e.b.y);
        e.hit.setAttribute('x1', e.a.x); e.hit.setAttribute('y1', e.a.y);
        e.hit.setAttribute('x2', e.b.x); e.hit.setAttribute('y2', e.b.y);
      });
      nodes.forEach(n => {
        n.g.setAttribute('transform', `translate(${n.x},${n.y})`);
        n.lab.setAttribute('x', n.x); n.lab.setAttribute('y', n.y + n.r + 13);
      });
    };
    place();
    pickLabels(nodes);
    if (state.band) {
      const bandText = el('text', { x: 40, y: state.AH + 8, class: 'band' }, gE);
      bandText.textContent = t('no_link_band');
      el('line', { x1: 20, x2: W - 20, y1: state.AH - 4, y2: state.AH - 4, class: 'band-line' }, gE);
    }

    // hover: the module, its links and neighbours stay; the rest fades
    const nbr = new Map(nodes.map(n => [n.id, new Set()]));
    edges.forEach(e => { nbr.get(e.source).add(e.target); nbr.get(e.target).add(e.source); });
    const tip = document.createElement('div');
    tip.className = 'tip'; tip.hidden = true; box.appendChild(tip);
    const focus = n => {
      svg.classList.toggle('focus', !!n);
      nodes.forEach(m => {
        const on = n && (m === n || nbr.get(n.id).has(m.id));
        m.g.classList.toggle('on', !!on); m.lab.classList.toggle('on', !!on);
      });
      edges.forEach(e => e.el.classList.toggle('on', !!n && (e.a === n || e.b === n)));
    };
    const focusEdge = e => {
      svg.classList.toggle('focus', !!e);
      nodes.forEach(m => { const on = e && (m === e.a || m === e.b); m.g.classList.toggle('on', !!on); m.lab.classList.toggle('on', !!on); });
      edges.forEach(x => x.el.classList.toggle('on', x === e));
    };

    // zoom and pan through the viewBox
    let view = { x: 0, y: 0, w: W, h: H };
    const setView = () => svg.setAttribute('viewBox', `${view.x} ${view.y} ${view.w} ${view.h}`);
    const toSvg = (cx, cy) => {
      const bb = svg.getBoundingClientRect();
      return [view.x + (cx - bb.left) / bb.width * view.w, view.y + (cy - bb.top) / bb.height * view.h];
    };
    svg.addEventListener('wheel', ev => {
      ev.preventDefault();
      const [px, py] = toSvg(ev.clientX, ev.clientY), f = ev.deltaY > 0 ? 1.15 : 1 / 1.15;
      const w = Math.min(W * 3, Math.max(W / 8, view.w * f)), h = w * H / W;
      view = { x: px - (px - view.x) * w / view.w, y: py - (py - view.y) * h / view.h, w, h };
      setView();
    }, { passive: false });
    let drag = null;
    svg.addEventListener('pointerdown', ev => {
      const g = ev.target.closest('.node');
      const n = g && nodes.find(m => m.g === g);
      const h = !n && ev.target.closest('.edge-hit');
      const e = h && edges.find(x => x.hit === h);
      drag = { n, e, sx: ev.clientX, sy: ev.clientY, vx: view.x, vy: view.y, moved: false };
      svg.setPointerCapture(ev.pointerId);
    });
    svg.addEventListener('pointermove', ev => {
      if (!drag) return;
      const bb = svg.getBoundingClientRect();
      const ddx = (ev.clientX - drag.sx) / bb.width * view.w, ddy = (ev.clientY - drag.sy) / bb.height * view.h;
      if (Math.abs(ev.clientX - drag.sx) + Math.abs(ev.clientY - drag.sy) > 3) drag.moved = true;
      if (!drag.moved) return;
      if (drag.n) { const [x, y] = toSvg(ev.clientX, ev.clientY); drag.n.x = x; drag.n.y = y; place(); }
      else { tip.hidden = true; view.x = drag.vx - ddx; view.y = drag.vy - ddy; setView(); }
    });
    svg.addEventListener('pointerup', () => {
      const d = drag; drag = null;
      if (d && d.n && d.moved) pickLabels(nodes);
      if (d && d.n && !d.moved) {
        if (d.n.drill) runMap(d.n.id); else { state.pinned = true; side(d.n, nbr); }
      } else if (d && d.e && !d.moved) {
        showEdge(d.e);
      } else if (d && !d.moved) {                                  // a click on the background lets go
        state.pinned = false; hint();
      }
    });

    edges.forEach(e => {
      e.hit.addEventListener('mouseenter', () => { if (!drag) focusEdge(e); });
      e.hit.addEventListener('mousemove', ev => {
        if (drag) return;
        const bb = box.getBoundingClientRect();
        tip.innerHTML = edgeTip(e);
        tip.style.left = `${Math.min(ev.clientX - bb.left + 14, bb.width - 260)}px`;
        tip.style.top = `${ev.clientY - bb.top + 14}px`;
        tip.hidden = false;
      });
      e.hit.addEventListener('mouseleave', () => { tip.hidden = true; focusEdge(null); });
    });

    nodes.forEach(n => {
      n.g.addEventListener('mouseenter', () => { if (drag) return; focus(n); if (!state.pinned) side(n, nbr); });
      n.g.addEventListener('mousemove', ev => {
        const bb = box.getBoundingClientRect();
        tip.innerHTML = `<b>${esc(n.id)}</b><div>${n.tasks.toLocaleString()} ${esc(unitWord())}${n.outside ? ' · ' + esc(t('also_outside', { n: n.outside })) : ''}` +
          `${n.units != null ? ' · ' + esc(t('units_in_code', { n: n.units.toLocaleString() })) : ''}</div>` +
          (n.cohesion != null ? `<div>${esc(t('cohesion_x', { x: pct(n.cohesion) }))} <span class="dim">${esc(t('links_in_out', { i: n.links_in, o: n.links_out }))}</span></div>` : '') +
          (n.zone ? `<div class="row2"><span class="sw" style="background:${fill(n)}"></span>${esc(zname(n.zone))}</div>` : '') +
          (n.drill ? `<div class="dim">${esc(t('click_open_map'))}</div>` : '');
        tip.style.left = `${Math.min(ev.clientX - bb.left + 14, bb.width - 220)}px`;
        tip.style.top = `${ev.clientY - bb.top + 14}px`;
        tip.hidden = false;
      });
      n.g.addEventListener('mouseleave', () => { tip.hidden = true; focus(null); });
      n.g.addEventListener('keydown', ev => { if (ev.key === 'Enter' && n.drill) runMap(n.id); });
    });
  }

  function edgeTip(e) {
    const A = esc(short(e.a)), B = esc(short(e.b));
    let s = `<b>${A} ↔ ${B}</b>${e.new ? ` <span class="tag new">${esc(t('tag_new'))}</span>` : ''}`;
    const src = SRC();
    if (src === 'history') {
      s += `<div>${esc(t('et_shared_lift', { n: e.tasks, l: e.lift.toFixed(2) }))}</div>
        <div>${t('et_of_its', { a: A, b: B, x: pct(e.tasks / e.a.tasks) })}</div>
        <div>${t('et_of_its', { a: B, b: A, x: pct(e.tasks / e.b.tasks) })}</div>`;
    } else {
      if (e.kind) s += `<div class="row2"><span class="sw k-${e.kind}"></span>${esc(kindText(e.kind))}</div>`;
      if (e.pairs) s += `<div>${esc(t('et_pairs', { n: e.pairs, m: e.min_tasks }))}</div>`;
      if (e.ab || e.ba) s += `<div>${t('et_uses', { a: A, b: B, n: e.ab })}</div><div>${t('et_uses', { a: B, b: A, n: e.ba })}</div>`;
    }
    return s + `<div class="dim">${esc(t('click_details'))}</div>`;
  }

  // side panel: the module's square in short, its links, and where to go next
  function side(n, nbr, pinned) {
    const { edges } = state;
    const links = edges.filter(e => e.source === n.id || e.target === n.id)
      .map(e => ({ other: e.source === n.id ? e.target : e.source, ...e })).sort((a, b) => b.tasks - a.tasks);
    const zones = n.zone ? ZONES.map(z =>
      `<div class="row2"><span class="sw" style="background:var(--z-${z})"></span>${esc(zname(z))}<span class="v">${pct(n[z])}</span></div>`).join('') : '';
    const col = SRC() === 'history' ? t('th_tasks') : SRC() === 'code' ? t('th_identifiers') : t('th_pairs');
    $('m-side').innerHTML = `<h3>${esc(short(n))}</h3><div class="dim mono">${esc(n.id)}</div>
      <div class="kpis"><span><b>${n.tasks.toLocaleString()}</b> ${esc(unitWord())}</span>${n.cohesion != null ? `<span>${esc(t('k_cohesion'))} <b>${pct(n.cohesion)}</b></span>` : ''}${n.outside ? `<span><b>${n.outside}</b> ${esc(t('k_also_outside'))}</span>` : ''}
        ${n.zone ? `<span>${esc(t('k_zone'))} <b>${esc(zname(n.zone).toLowerCase())}</b></span>` : ''}</div>
      ${zones}
      <div class="row">${n.drill ? `<button class="small" data-open="${esc(n.id)}">${esc(t('open_its_map'))}</button>` : ''}
        ${n.own || SRC() === 'code' ? '' : `<button class="small" data-health="${esc(n.id)}">${esc(t('health_square'))}</button>`}</div>
      <h3>${esc(t('links_n', { n: links.length }))}</h3>
      ${links.length ? `<table class="h"><tr><th>${esc(t('th_with'))}</th><th>${esc(col)}</th><th>${SRC() === 'history' ? esc(t('th_lift')) : ''}</th></tr>${links.map(l =>
        `<tr><td>${l.kind ? `<span class="sw k-${l.kind}"></span> ` : ''}<a class="ent" data-edge="${esc(l.source)}|${esc(l.target)}">${esc(state.byId.get(l.other) ? short(state.byId.get(l.other)) : l.other)}</a>${l.new ? ` <span class="tag new">${esc(t('tag_new'))}</span>` : ''}</td>
         <td>${l.tasks}</td><td>${SRC() === 'history' ? l.lift.toFixed(1) : ''}</td></tr>`).join('')}</table>` : `<p class="dim">${esc(t('no_link'))}</p>`}`;
    $('m-side').querySelectorAll('[data-open]').forEach(b => b.onclick = () => runMap(b.dataset.open));
    $('m-side').querySelectorAll('[data-edge]').forEach(a => a.onclick = () => {
      const [x, y] = a.dataset.edge.split('|');
      const e = state.edges.find(z => z.source === x && z.target === y);
      if (e) showEdge(e);
    });
    $('m-side').querySelectorAll('[data-health]').forEach(b => b.onclick = () => {
      $('h-scope').value = 'unit'; $('h-target').hidden = false; $('h-target').value = b.dataset.health;
      $('h-since').value = $('m-since').value; $('h-until').value = $('m-until').value;
      showTab('health'); runHealth();
    });
  }

  function hint() { if (state) state.edge = null; $('m-side').innerHTML = `<p class="dim">${esc(t('m_hint'))}</p>`; }

  const base = f => f.split('/').pop();
  const fileLink = f => `<span class="mono" title="${esc(f)}">${esc(base(f))}</span>`;

  // one series over the years: plain columns, rounded top, a title per column for hover
  function yearsSvg(years) {
    if (!years.length) return '';
    const W2 = 300, H2 = 70, B = 14, max = Math.max(...years.map(y => y.tasks));
    const ys = []; for (let y = +years[0].year; y <= +years[years.length - 1].year; y++) ys.push(String(y));
    const m = new Map(years.map(y => [y.year, y.tasks])), step = W2 / ys.length, bw = Math.max(3, Math.min(18, step - 2));
    let s = `<svg width="${W2}" height="${H2}" class="years" role="img" aria-label="${esc(t('years_aria'))}">`;
    s += `<line x1="0" x2="${W2}" y1="${H2 - B}" y2="${H2 - B}" stroke="var(--axis)"/>`;
    ys.forEach((y, i) => {
      const v = m.get(y) || 0, h = (H2 - B - 4) * v / max, x = i * step + (step - bw) / 2;
      if (v) s += `<path d="M${x},${H2 - B} v${-Math.max(0, h - 2)} q0,-2 2,-2 h${bw - 4} q2,0 2,2 v${Math.max(0, h - 2)} z" fill="var(--accent)"><title>${esc(t('year_tip', { y, n: v }))}</title></path>`;
      if (i === 0 || i === ys.length - 1 || ys.length <= 8) s += `<text x="${x + bw / 2}" y="${H2 - 2}" text-anchor="middle">${y}</text>`;
    });
    return s + '</svg>';
  }

  function ontoEdgeHtml(d, e, A, B) {
    const chips = (list, tipOf) => `<div class="terms">${list.map(x => `<span class="chip" title="${esc(tipOf(x))}">${esc(x.word || x.ident)}${x.used_in ? ` <span class="dim">${x.used_in}</span>` : ''}</span>`).join('')}</div>`;
    let h = `<h3>${esc(A)} ↔ ${esc(B)}</h3><div class="dim mono">${esc(d.a)}<br>${esc(d.b)}</div>`;
    if (e.kind) h += `<div class="verdict"><span class="sw k-${e.kind}"></span>${esc(kindText(e.kind))}</div>`;
    const k = [];
    if (d.pairs_total != null) k.push(`<span>${t('e_sig_pairs', { n: d.pairs_total })}</span>`, `<span>${t('e_at_least', { n: d.min_tasks })}</span>`, `<span>ΣG² <b>${d.g2}</b></span>`);
    if (d.a_uses_b != null) k.push(`<span>${t('e_idents_between', { n: d.a_uses_b + d.b_uses_a })}</span>`);
    h += `<div class="kpis">${k.join('')}</div>`;
    if (d.depends_on && d.depends_on.length) h += `<h4>${esc(t('e_imports'))}</h4>${d.depends_on.map(x => `<div>${esc(x.from)} → ${esc(x.to)} <span class="dim">${esc(t('e_importing', { n: x.importing_files }))}</span></div>`).join('')}`;
    if (d.a_uses_b != null) {
      const way = (x, y, n, of) => `<div class="way"><div>${t('e_uses_n', { a: esc(x), b: esc(y), n })}</div>
        <div class="meter"><span style="width:${of ? 100 * n / of : 0}%;background:var(--accent)"></span></div></div>`;
      const tot = d.a_uses_b + d.b_uses_a;
      h += `<h4>${esc(t('e_who_uses'))}</h4>${way(A, B, d.a_uses_b, tot)}${way(B, A, d.b_uses_a, tot)}
        <p class="dim">${esc(t('e_idents_note'))}</p>`;
      if (d.idents_ab.length) h += `<div class="dim">${esc(t('e_uses_from', { a: A, b: B }))}</div>${chips(d.idents_ab, x => t('e_used_in', { n: x.used_in, a: A }))}`;
      if (d.idents_ba.length) h += `<div class="dim">${esc(t('e_uses_from', { a: B, b: A }))}</div>${chips(d.idents_ba, x => t('e_used_in', { n: x.used_in, a: B }))}`;
    }
    if (d.words && d.words.length) h += `<h4>${esc(t('e_words_both'))}</h4><p class="dim">${esc(t('e_words_both_note'))}</p>
      ${chips(d.words, x => `G² ${x.g2_a} / ${x.g2_b}`)}`;
    if (d.pairs && d.pairs.length) h += `<h4>${esc(t('e_pairs_change'))}</h4>
      <table class="h pairs"><tr><th>${esc(A)}</th><th>${esc(B)}</th><th>${esc(t('th_tasks'))}</th></tr>${d.pairs.map(x => `<tr><td>${fileLink(x.a)}</td><td>${fileLink(x.b)}</td><td title="G² ${x.g2} · lift ${x.lift}">${x.tasks}</td></tr>`).join('')}</table>`;
    const files = (fa, fb, title) => fa && (fa.length || fb.length) ? `<h4>${title}</h4>
      <div class="two"><div><div class="dim">${esc(A)}</div>${fa.map(f => `<div>${fileLink(f.file)} <span class="dim">${f.n}</span></div>`).join('')}</div>
        <div><div class="dim">${esc(B)}</div>${fb.map(f => `<div>${fileLink(f.file)} <span class="dim">${f.n}</span></div>`).join('')}</div></div>` : '';
    h += files(d.files_a, d.files_b, esc(t('e_files_change'))) + files(d.code_files_a, d.code_files_b, esc(t('e_files_use')));
    return h + `<div class="row"><button class="small" id="m-unpin">${esc(t('back'))}</button></div>`;
  }

  async function showEdge(e) {
    const p = project();
    state.pinned = true;
    const A = short(e.a), B = short(e.b);
    $('m-side').innerHTML = `<h3>${esc(A)} ↔ ${esc(B)}</h3><p class="dim">${esc(t('reading'))}</p>`;
    try {
      const d = await api('/api/edge', { project: p, prefix: state.res.prefix, a: e.source, b: e.target,
        source: SRC() === 'history' ? 'history' : 'ontology', compare: SRC() === 'overlay' ? $('m-compare').value : '',
        since: $('m-since').value.trim(), until: $('m-until').value.trim() });
      if (project() !== p || !state.pinned) return;
      state.edge = { d, e };
      drawEdge();
    } catch (err) {
      if (project() === p) $('m-side').innerHTML = `<p class="err">${esc(err.message)}</p>`;
    }
  }

  // the detail of the open link, from the answer in hand (redrawn on a new language)
  function drawEdge() {
    const { d, e } = state.edge;
    const A = short(e.a), B = short(e.b);
    if (d.source !== 'history') {
      $('m-side').innerHTML = ontoEdgeHtml(d, e, A, B);
      $('m-unpin').onclick = () => { state.pinned = false; state.edge = null; hint(); };
      return;
    }
    const way = (x, y, v, n, of) => `<div class="way"><div>${t('e_when_changes', { a: esc(x), b: esc(y), x: pct(v) })}
      <span class="dim">${esc(t('e_n_of', { n, of }))}</span></div><div class="meter"><span style="width:${100 * v}%;background:var(--accent)"></span></div></div>`;
    const zbar = d.cross_pairs ? `<div class="stack">
        <span style="width:${100 * d.disruption}%;background:var(--z-disruption)"></span><span style="width:${100 * d.stagnation}%;background:var(--z-stagnation)"></span></div>
      <div class="legend"><span><span class="sw" style="background:var(--z-disruption)"></span>${esc(t('e_new_pairs', { x: pct(d.disruption) }))}</span>
        <span><span class="sw" style="background:var(--z-stagnation)"></span>${esc(t('e_same_pairs', { x: pct(d.stagnation) }))}</span></div>` : '';
    $('m-side').innerHTML = `<h3>${esc(A)} ↔ ${esc(B)}</h3>
      <div class="dim mono">${esc(d.a)}<br>${esc(d.b)}</div>
      <div class="kpis"><span>${t('e_shared_tasks', { n: d.tasks })}</span><span>${esc(t('th_lift'))} <b>${d.lift.toFixed(2)}</b></span>
        <span>${t('e_files_per_task', { n: d.avg_files })}</span>${d.first ? `<span>${esc(d.first)} … ${esc(d.last)}</span>` : ''}</div>
      <h4>${esc(t('e_both_ways'))}</h4>
      ${way(A, B, d.p_b_given_a, d.tasks, d.a_tasks)}${way(B, A, d.p_a_given_b, d.tasks, d.b_tasks)}
      <h4>${esc(t('e_years'))}</h4>${yearsSvg(d.years)}
      <h4>${esc(t('e_character'))}</h4>
      <p class="dim">${esc(t('e_character_note', { n: d.cross_pairs }))}</p>${zbar}
      ${d.words.length ? `<h4>${esc(t('e_what_for'))}</h4><p class="dim">${esc(t('e_what_for_note'))}</p>
        <div class="terms">${d.words.map(w => `<span class="chip" title="${esc(t('e_word_tip', { s: w.shared, o: w.one_side, g: w.g2 }))}">${esc(w.word)} <span class="dim">${w.shared}</span></span>`).join('')}</div>` : ''}
      <h4>${esc(t('e_pairs_carry'))}</h4>
      <table class="h pairs">${d.pairs.map(x => `<tr><td>${fileLink(x.a)}</td><td>${fileLink(x.b)}</td><td>${x.tasks}</td></tr>`).join('')}</table>
      <h4>${esc(t('e_files_side'))}</h4>
      <div class="two"><div><div class="dim">${esc(A)}</div>${d.files_a.map(f => `<div>${fileLink(f.file)} <span class="dim">${f.tasks}</span></div>`).join('')}</div>
        <div><div class="dim">${esc(B)}</div>${d.files_b.map(f => `<div>${fileLink(f.file)} <span class="dim">${f.tasks}</span></div>`).join('')}</div></div>
      <h4>${esc(t('e_latest'))}</h4>
      ${d.recent.map(x => `<div class="task"><b>${esc(x.task)}</b> <span class="dim">${esc(t('e_task_files', { d: x.date, n: x.files }))}</span><div>${esc(x.title)}</div></div>`).join('')}
      <div class="row"><button class="small" id="m-unpin">${esc(t('back'))}</button></div>`;
    $('m-unpin').onclick = () => { state.pinned = false; state.edge = null; hint(); };
  }

  function crumbs(res) {
    const p = project();
    const parts = [`<a class="ent" data-p="">${esc(p)}</a>`];
    res.crumbs.forEach(c => parts.push(`<a class="ent" data-p="${esc(c)}">${esc(c.split('/').pop())}</a>`));
    $('m-crumbs').innerHTML = parts.join(' <span class="dim">›</span> ');
    $('m-crumbs').querySelectorAll('a').forEach(a => a.onclick = () => runMap(a.dataset.p));
  }

  function legend(res) {
    const hasNew = res.edges.some(e => e.new);
    const ring = `<span><svg width="18" height="18"><circle cx="9" cy="9" r="5" fill="var(--dim)"/><circle cx="9" cy="9" r="8" class="ring"/></svg>${esc(t('lg_ring'))}</span>`;
    const line = (cls, text) => `<span><svg width="26" height="10"><line x1="0" y1="5" x2="26" y2="5" class="edge ${cls}" stroke-width="3"/></svg>${esc(text)}</span>`;
    if (res.source !== 'history') {
      const coh = `<span><span class="sw" style="background:color-mix(in oklab, var(--z-evolution) 18%, var(--panel))"></span>…<span class="sw" style="background:var(--z-evolution)"></span>
        ${esc(t(res.source === 'code' ? 'lg_cohesion_code' : 'lg_cohesion_pairs'))}</span>`;
      const links = res.source === 'overlay'
        ? ['both', 'history', 'code', 'gone'].filter(k => res.edges.some(e => e.kind === k)).map(k => line('k-' + k, kindText(k))).join('')
        : line('', t(res.source === 'code' ? 'lg_link_code' : 'lg_link_onto'));
      $('m-legend').innerHTML = coh + links + ring + `<span>${esc(t('lg_size', { u: unitWord(res.source) }))}</span>`;
      return;
    }
    $('m-legend').innerHTML = ZONES.map(z =>
        `<span><span class="sw" style="background:var(--z-${z})"></span>${esc(zname(z))} — ${esc(t('zd_' + z))}</span>`).join('') +
      line('', t('lg_link_history')) +
      (hasNew || res.params.since ? line('new', t('lg_new_since', { d: res.params.since || '' })) : '') +
      ring + `<span>${esc(t('lg_size_history'))}</span>`;
  }

  function tables(res) {
    const nm = id => esc(id);
    if (res.source !== 'history') {
      $('m-tables').innerHTML = `<details><summary class="dim">${esc(t('tbl_summary', { n: res.nodes.length, e: res.edges.length }))}</summary>
        <table class="h"><tr><th>${esc(t('th_module'))}</th><th>${esc(unitWord(res.source))}</th><th>${esc(t('k_cohesion'))}</th>${res.source === 'overlay' ? `<th>${esc(t('th_units_code'))}</th>` : ''}</tr>
        ${[...res.nodes].sort((a, b) => b.tasks - a.tasks).map(n => `<tr><td>${nm(n.id)}</td><td>${n.tasks}</td>
          <td>${n.cohesion == null ? '' : pct(n.cohesion)}</td>${res.source === 'overlay' ? `<td>${n.units}</td>` : ''}</tr>`).join('')}</table>
        <table class="h"><tr><th>${esc(t('th_module'))}</th><th>${esc(t('th_module'))}</th>${res.source === 'overlay' ? `<th>${esc(t('th_kind'))}</th>` : ''}<th>${esc(t('th_file_pairs'))}</th><th>${esc(t('th_ge_tasks'))}</th><th>${esc(t('th_a_uses_b'))}</th><th>${esc(t('th_b_uses_a'))}</th></tr>
        ${[...res.edges].sort((a, b) => b.tasks - a.tasks).map(e => `<tr><td>${nm(e.source)}</td><td>${nm(e.target)}</td>
          ${res.source === 'overlay' ? `<td>${esc(t('kname_' + e.kind))}</td>` : ''}<td>${e.pairs ?? ''}</td><td>${e.min_tasks || ''}</td><td>${e.ab ?? ''}</td><td>${e.ba ?? ''}</td></tr>`).join('')}</table></details>`;
      return;
    }
    $('m-tables').innerHTML = `<details><summary class="dim">${esc(t('tbl_summary', { n: res.nodes.length, e: res.edges.length }))}</summary>
      ${zoneTable([...res.nodes].filter(n => n.zone).sort((a, b) => b.tasks - a.tasks), n => nm(n.id), t('th_module'))}
      <table class="h"><tr><th>${esc(t('th_module'))}</th><th>${esc(t('th_module'))}</th><th>${esc(t('th_tasks'))}</th><th>${esc(t('th_lift'))}</th><th>${esc(t('th_new'))}</th></tr>
      ${[...res.edges].sort((a, b) => b.tasks - a.tasks).map(e => `<tr><td>${nm(e.source)}</td><td>${nm(e.target)}</td>
        <td>${e.tasks}</td><td>${e.lift.toFixed(2)}</td><td>${e.new ? esc(t('yes')) : ''}</td></tr>`).join('')}</table></details>`;
  }

  async function runMap(pre, edge) {
    if (!project()) { $('m-status').textContent = t('choose_project_first'); return; }
    const p = project();
    const source = $('m-source').value, compare = source === 'ontology' ? $('m-compare').value : '';
    $('m-status').textContent = t(source === 'history' ? 'computing_history' : 'computing');
    try {
      const t0 = performance.now();
      const res = await api('/api/map', { project: p, prefix: pre ?? prefix, source, compare, since: $('m-since').value.trim(),
        until: $('m-until').value.trim(), min_tasks: +$('m-min').value || 3, per_node: +$('m-per').value || 6 });
      if (project() !== p) return;
      prefix = res.prefix;
      const u = new URL(location.href);
      u.searchParams.set('tab', 'map');
      if (prefix) u.searchParams.set('prefix', prefix); else u.searchParams.delete('prefix');
      u.searchParams.set('source', source);
      if (compare) u.searchParams.set('compare', compare); else u.searchParams.delete('compare');
      history.replaceState(null, '', u);
      crumbs(res); legend(res); tables(res);
      if (!res.nodes.length) { $('m-chart').innerHTML = `<p class="dim">${esc(t('map_empty'))}</p>`; return; }
      const maxT = Math.max(1, ...res.nodes.map(n => n.tasks));
      const nodes = res.nodes.map(n => ({ ...n, r: 5 + 26 * Math.sqrt(n.tasks / maxT) }));
      const edges = res.edges.map(e => ({ ...e }));
      shortNames(nodes);
      const { band, AH } = layout(nodes, edges);
      state = { res, nodes, edges, band, AH, byId: new Map(nodes.map(n => [n.id, n])) };
      state.ms = Math.round(performance.now() - t0);
      render();
      status();
      hint();
      const ed = edge && state.edges.find(z => [z.source + '|' + z.target, z.target + '|' + z.source].includes(edge));
      if (ed) showEdge(ed);
    } catch (e) {
      if (project() === p) $('m-status').innerHTML = `<span class="err">${esc(e.message)}</span>`;
    }
  }

  function status() {
    const res = state.res;
    const extra = res.source === 'overlay' ? ' (' + Object.entries(res.counts).map(([k, v]) => `${v} ${t('kname_' + k)}`).join(', ') + ')'
      : res.edges.some(e => e.new) ? t('st_new', { n: res.edges.filter(e => e.new).length }) : '';
    $('m-status').textContent = t('ms_status', { ms: state.ms }) +
      (res.source === 'history' ? t('st_tasks', { n: res.window_tasks }) : res.source === 'code' ? '' : t('st_ontology', { n: res.window_tasks })) +
      t('st_modules_links', { n: res.nodes.length, e: res.edges.length }) + extra;
  }

  // a new language: redraw from what is in hand — layout and positions stay
  langHooks.push(() => {
    syncControls();
    if (!state) return;
    legend(state.res); tables(state.res); render(); status();
    if (state.edge) drawEdge(); else hint();
  });

  // the source of the map: the ontology (small, fast, no dates) or the task history (time window)
  function syncControls() {
    const hist = $('m-source').value === 'history';
    document.querySelectorAll('.m-time').forEach(x => { x.hidden = !hist; });
    $('m-compare-box').hidden = hist;
    const keep = $('m-compare').value;
    const others = (typeof projects !== 'undefined' ? projects : []).filter(x => x.project !== project());
    $('m-compare').innerHTML = `<option value="">${esc(t('m_none'))}</option>` +
      others.map(x => `<option value="${esc(x.project)}">${esc(x.project)}</option>`).join('');
    if (others.some(x => x.project === keep)) $('m-compare').value = keep;
  }
  $('m-source').onchange = () => { syncControls(); runMap(); };
  $('m-compare').onchange = () => runMap();
  window.mapFromUrl = u => {
    syncControls();
    if (u.get('source')) $('m-source').value = u.get('source');
    if (u.get('since')) $('m-since').value = u.get('since');
    syncControls();
    if (u.get('compare')) $('m-compare').value = u.get('compare');
    runMap(u.get('prefix') || '', u.get('edge') || '');
  };
  document.querySelector('.tab[data-tab="map"]').addEventListener('click', syncControls);

  $('m-go').onclick = () => runMap();
  $('project').addEventListener('change', () => {
    prefix = ''; state = null;
    ['m-chart', 'm-crumbs', 'm-legend', 'm-tables'].forEach(id => { $(id).innerHTML = ''; });
    $('m-status').textContent = '';
    $('m-compare').value = '';
    syncControls();
  });
  window.runMap = runMap;
})();
