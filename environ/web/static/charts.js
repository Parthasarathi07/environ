/* charts.js — a ~200 line interactive SVG chart helper.
 *
 * Why hand-written: the sandbox has no internet, so a CDN-loaded charting
 * library would render a blank page. It is also a genuinely good thing to be
 * able to say in an interview: "the charts are 200 lines of my own SVG code,
 * which is why the whole thing works offline and loads instantly."
 *
 * Every function takes (container, config) and writes an <svg> plus a tooltip
 * div. No globals, no dependencies.
 */
(function (global) {
  'use strict';

  const INK = '#16181d', MUTED = '#6b7280', GRID = '#e5e7eb';
  const SEQ = ['#8c9bab', '#5f8fb3', '#3f7fa6', '#2f6f74', '#1f5c46'];

  const el = (t, a, txt) => {
    const n = document.createElementNS('http://www.w3.org/2000/svg', t);
    for (const k in a) n.setAttribute(k, a[k]);
    if (txt !== undefined) n.textContent = txt;
    return n;
  };
  const fmt = (v, nd) => (v === null || v === undefined || Number.isNaN(v)) ? '—'
    : Number(v).toFixed(nd === undefined ? 1 : nd);
  const signed = (v, nd) => (v > 0 ? '+' : '') + fmt(v, nd);

  function frame(host, W, H, m) {
    host.innerHTML = '';
    const wrap = document.createElement('div');
    wrap.className = 'chartbox';
    const svg = el('svg', { viewBox: `0 0 ${W} ${H}`, width: '100%', height: 'auto', role: 'img' });
    const tip = document.createElement('div');
    tip.className = 'tip';
    wrap.appendChild(svg); wrap.appendChild(tip); host.appendChild(wrap);
    const M = m || { t: 16, r: 16, b: 34, l: 46 };
    return {
      svg, tip, wrap, W, H, M,
      x0: M.l, y0: M.t, x1: W - M.r, y1: H - M.b,
      get pw() { return this.x1 - this.x0 }, get ph() { return this.y1 - this.y0 },
    };
  }

  function niceTicks(lo, hi, n) {
    n = n || 5;
    if (hi === lo) { hi = lo + 1; }
    const raw = (hi - lo) / n, mag = Math.pow(10, Math.floor(Math.log10(Math.abs(raw) || 1)));
    let step = 10 * mag;
    for (const c of [1, 2, 2.5, 5, 10]) { if (raw / (c * mag) <= 1.0001) { step = c * mag; break; } }
    const out = [];
    for (let v = Math.ceil(lo / step) * step; v <= hi + step * 1e-9; v += step) out.push(+v.toFixed(8));
    return out;
  }

  function axes(f, lo, hi, opts) {
    const o = opts || {};
    const pad = (hi - lo) * (o.pad || 0.08);
    const ymin = lo - pad, ymax = hi + pad;
    const yv = v => f.y1 - (v - ymin) / (ymax - ymin) * f.ph;
    niceTicks(ymin, ymax, o.ticks || 5).forEach(t => {
      const y = yv(t);
      f.svg.appendChild(el('line', { x1: f.x0, y1: y, x2: f.x1, y2: y, stroke: GRID }));
      f.svg.appendChild(el('text', { x: f.x0 - 7, y: y + 3.5, 'text-anchor': 'end',
        'font-size': 10.5, fill: MUTED }, (o.signed ? signed(t, o.nd) : fmt(t, o.nd)) + (o.suffix || '')));
    });
    if (ymin < 0 && ymax > 0) {
      f.svg.appendChild(el('line', { x1: f.x0, y1: yv(0), x2: f.x1, y2: yv(0), stroke: '#aeb4be', 'stroke-width': 1.3 }));
    }
    f.svg.appendChild(el('line', { x1: f.x0, y1: f.y1, x2: f.x1, y2: f.y1, stroke: '#c3c8d1', 'stroke-width': 1.2 }));
    return { yv, ymin, ymax };
  }

  /* ------------------------------------------------------------ line chart */
  function lines(host, cfg) {
    const W = cfg.w || 760, H = cfg.h || 300;
    const f = frame(host, W, H, cfg.m);
    const labels = cfg.labels || [];
    const allv = cfg.series.flatMap(s => s.values.filter(v => v !== null && v !== undefined));
    if (!allv.length) { host.textContent = 'no data'; return; }
    let lo = Math.min(...allv), hi = Math.max(...allv);
    if (cfg.includeZero) { lo = Math.min(lo, 0); hi = Math.max(hi, 0); }
    const ax = axes(f, lo, hi, cfg);
    const n = labels.length;
    const xv = i => f.x0 + (n < 2 ? f.pw / 2 : (i / (n - 1)) * f.pw);

    // year separators
    let lastYear = null;
    labels.forEach((d, i) => {
      const y = String(d).slice(0, 4);
      if (y !== lastYear) {
        if (lastYear !== null) {
          f.svg.appendChild(el('line', { x1: xv(i), y1: f.y0, x2: xv(i), y2: f.y1, stroke: GRID }));
        }
        if (i > 0 && y % (cfg.yearEvery || 1) === 0) {
          f.svg.appendChild(el('text', { x: xv(i), y: f.y1 + 15, 'text-anchor': 'middle',
            'font-size': 10, fill: MUTED }, y));
        }
        lastYear = y;
      }
    });

    const hit = el('rect', { x: f.x0, y: f.y0, width: f.pw, height: f.ph, fill: 'transparent' });
    f.svg.appendChild(hit);
    const focus = el('line', { x1: 0, y1: f.y0, x2: 0, y2: f.y1, stroke: '#16181d', 'stroke-width': 1,
      'stroke-dasharray': '3,3', opacity: 0 });
    f.svg.appendChild(focus);
    const pts = cfg.series.map(s => el('circle', { r: 3.6, fill: s.color || '#000', opacity: 0 }));
    pts.forEach(p => f.svg.appendChild(p));

    cfg.series.forEach((s, si) => {
      let d = '', started = false;
      s.values.forEach((v, i) => {
        if (v === null || v === undefined) { started = false; return; }
        d += (started ? ' L' : ' M') + xv(i).toFixed(1) + ',' + ax.yv(v).toFixed(1);
        started = true;
      });
      if (s.fill) {
        const area = d + ` L${xv(s.values.length - 1).toFixed(1)},${f.y1} L${xv(0).toFixed(1)},${f.y1} Z`;
        f.svg.insertBefore(el('path', { d: area, fill: s.color, 'fill-opacity': 0.09, stroke: 'none' }), hit);
      }
      f.svg.insertBefore(el('path', { d, fill: 'none', stroke: s.color || INK, 'stroke-width': s.width || 2.2,
        'stroke-linejoin': 'round', 'stroke-linecap': 'round', opacity: s.opacity || 1 }), hit);
    });

    // legend
    if (cfg.legend !== false) {
      let lx = f.x0, ly = f.y0 - 4;
      if (cfg.legendAt === 'top-right') lx = f.x1;
      cfg.series.slice().reverse().forEach(s => {
        const g = el('g', { 'text-anchor': 'end' });
        const t = el('text', { x: lx, y: ly, 'font-size': 11, fill: s.color || INK, 'text-anchor': 'end',
          'font-weight': 600 }, s.name);
        g.appendChild(t); f.svg.appendChild(g);
        const w = (s.name || '').length * 5.9 + 14;
        f.svg.appendChild(el('rect', { x: lx - w + 4, y: ly - 8, width: 9, height: 9, rx: 2, fill: s.color }));
        lx -= w + 12;
      });
    }

    hit.addEventListener('mousemove', ev => {
      const r = f.wrap.getBoundingClientRect();
      const rel = (ev.clientX - r.left) / r.width * W;
      let i = Math.round((rel - f.x0) / f.pw * (n - 1));
      i = Math.max(0, Math.min(n - 1, i));
      focus.setAttribute('x1', xv(i)); focus.setAttribute('x2', xv(i)); focus.setAttribute('opacity', .5);
      let html = `<b>${cfg.labelFmt ? cfg.labelFmt(labels[i]) : labels[i]}</b>`;
      cfg.series.forEach((s, si) => {
        const v = s.values[i];
        pts[si].setAttribute('cx', xv(i)); pts[si].setAttribute('cy', v == null ? -99 : ax.yv(v));
        pts[si].setAttribute('opacity', v == null ? 0 : 1);
        html += `<br><span style="color:${s.color}">■</span> ${s.name}: <b>${cfg.valFmt ? cfg.valFmt(v, s) : signed(v, 1) + (cfg.suffix || '')}</b>`;
      });
      f.tip.innerHTML = html;
      f.tip.style.left = (xv(i) / W * r.width) + 'px';
      f.tip.style.top = (f.y1 / H * r.height) + 'px';
      f.tip.classList.add('on');
    });
    hit.addEventListener('mouseleave', () => { f.tip.classList.remove('on'); focus.setAttribute('opacity', 0);
      pts.forEach(p => p.setAttribute('opacity', 0)); });
  }

  /* -------------------------------------------------------- grouped columns */
  function bars(host, cfg) {
    const W = cfg.w || 760, H = cfg.h || 280;
    const f = frame(host, W, H, cfg.m || { t: 14, r: 14, b: 46, l: 48 });
    const cats = cfg.cats, groups = cfg.groups;
    const allv = groups.flatMap(g => g.values.filter(v => v !== null));
    let lo = Math.min(0, ...allv), hi = Math.max(0, ...allv);
    const ax = axes(f, lo, hi, cfg);
    const slot = f.pw / cats.length;
    const bw = Math.min(26, slot / (groups.length + 1));
    cats.forEach((c, i) => {
      const cx = f.x0 + slot * (i + 0.5);
      f.svg.appendChild(el('text', { x: cx, y: f.y1 + 16, 'text-anchor': 'middle', 'font-size': 11,
        fill: INK, 'font-weight': cfg.boldCats ? 650 : 400 }, c));
      groups.forEach((g, gi) => {
        const v = g.values[i];
        if (v === null || v === undefined) return;
        const x = cx - (bw * groups.length) / 2 + gi * bw;
        const y = ax.yv(v), y0 = ax.yv(0);
        const rect = el('rect', { x, y: Math.min(y, y0), width: bw - 2, height: Math.abs(y0 - y),
          fill: g.color || INK, rx: 1.5, opacity: g.opacity || 1 });
        rect.style.cursor = 'pointer';
        const show = () => {
          f.tip.innerHTML = `<b>${c}</b><br>${g.name}: <b>${cfg.valFmt ? cfg.valFmt(v) : signed(v, 1) + (cfg.suffix || '')}</b>`
            + (g.notes && g.notes[i] ? `<br><span style="opacity:.75">${g.notes[i]}</span>` : '');
          const r = f.wrap.getBoundingClientRect();
          f.tip.style.left = ((x + bw / 2) / W * r.width) + 'px';
          f.tip.style.top = (Math.min(y, y0) / H * r.height) + 'px';
          f.tip.classList.add('on');
          rect.setAttribute('opacity', 1);
        };
        rect.addEventListener('mouseenter', show);
        rect.addEventListener('mouseleave', () => { f.tip.classList.remove('on'); rect.setAttribute('opacity', g.opacity || 1); });
        f.svg.appendChild(rect);
        if (cfg.showValues) {
          f.svg.appendChild(el('text', { x: x + (bw - 2) / 2, y: (v >= 0 ? y - 5 : y0 + 13),
            'text-anchor': 'middle', 'font-size': 9.5, fill: MUTED }, fmt(v, cfg.nd)));
        }
      });
    });
  }

  /* --------------------------------------------------- horizontal bar list */
  function hbars(host, cfg) {
    const cats = cfg.cats, rows = cfg.rows;   // rows: [{name, values:[..], colors, notes}]
    const W = cfg.w || 760, rowH = cfg.rowH || 30;
    const H = rowH * cats.length + (cfg.m ? cfg.m.t + cfg.m.b : 62);
    const f = frame(host, W, H, cfg.m || { t: 24, r: 90, b: 30, l: cfg.labelW || 150 });
    const flat = rows.flatMap(r => r.values);
    let lo = Math.min(0, ...flat), hi = Math.max(0, ...flat);
    const pad = (hi - lo) * 0.08 || 1; lo -= pad; hi += pad;
    const plotX0 = f.x0, plotX1 = f.x1;
    const sc = (plotX1 - plotX0) / (hi - lo);
    const zx = plotX0 - lo * sc;
    f.svg.appendChild(el('line', { x1: zx, y1: f.y0 - 8, x2: zx, y2: f.y1, stroke: '#aeb4be', 'stroke-width': 1.2 }));
    niceTicks(lo, hi, 5).forEach(t => {
      const x = plotX0 + t * sc;
      f.svg.appendChild(el('line', { x1: x, y1: f.y0 - 8, x2: x, y2: f.y1, stroke: GRID }));
      f.svg.appendChild(el('text', { x, y: f.y1 + 14, 'text-anchor': 'middle', 'font-size': 9.5,
        fill: MUTED }, (cfg.signedValues ? signed(t, 0) : fmt(t, 0))));
    });
    cats.forEach((c, i) => {
      const y = f.y0 + i * rowH;
      f.svg.appendChild(el('text', { x: plotX0 - 8, y: y + rowH * 0.62, 'text-anchor': 'end',
        'font-size': 10.5, fill: INK }, c));
      rows.forEach((r, ri) => {
        const v = r.values[i];
        if (v === null || v === undefined) return;
        const h = rowH / rows.length - 3;
        const yy = y + 3 + ri * (h + 2);
        const x = plotX0 + v * sc;
        const rect = el('rect', { x: Math.min(zx, x), y: yy, width: Math.abs(x - zx), height: h,
          fill: (r.colors && r.colors[i]) || r.color || INK, rx: 1.5 });
        rect.style.cursor = 'pointer';
        rect.addEventListener('mouseenter', () => {
          f.tip.innerHTML = `<b>${c}</b><br>${r.name}: <b>${signed(v, 2)}${cfg.suffix || ''}</b>`
            + (r.notes && r.notes[i] ? `<br><span style="opacity:.75">${r.notes[i]}</span>` : '');
          const rc = f.wrap.getBoundingClientRect();
          f.tip.style.left = (x / W * rc.width) + 'px';
          f.tip.style.top = (yy / H * rc.height) + 'px';
          f.tip.classList.add('on');
        });
        rect.addEventListener('mouseleave', () => f.tip.classList.remove('on'));
        f.svg.appendChild(rect);
      });
      const tot = rows.reduce((a, r) => a + (r.values[i] || 0), 0);
      if (cfg.showTotal) {
        f.svg.appendChild(el('text', { x: f.x1 + 8, y: y + rowH * 0.62, 'font-size': 10.5,
          fill: Math.abs(tot) > 5 ? INK : MUTED, 'font-weight': 650 }, signed(tot, 1)));
      }
    });
  }

  /* ------------------------------------------------------- slope (coefs) */
  function forest(host, cfg) {
    const items = cfg.items;      // {name, est, lo, hi, t}
    const W = cfg.w || 760, rowH = 34;
    const H = rowH * items.length + 66;
    const f = frame(host, W, H, { t: 20, r: 74, b: 30, l: 210 });
    const lo = Math.min(...items.map(i => i.lo)), hi = Math.max(...items.map(i => i.hi));
    const pad = (hi - lo) * 0.1 || 1;
    const l2 = lo - pad, h2 = hi + pad;
    const sc = (f.x1 - f.x0) / (h2 - l2);
    const X = v => f.x0 + (v - l2) * sc;
    niceTicks(l2, h2, 6).forEach(t => {
      f.svg.appendChild(el('line', { x1: X(t), y1: f.y0, x2: X(t), y2: f.y1, stroke: GRID }));
      f.svg.appendChild(el('text', { x: X(t), y: f.y1 + 15, 'text-anchor': 'middle', 'font-size': 9.5,
        fill: MUTED }, fmt(t, 0)));
    });
    f.svg.appendChild(el('line', { x1: X(0), y1: f.y0 - 6, x2: X(0), y2: f.y1, stroke: '#b4453c',
      'stroke-width': 1.3, 'stroke-dasharray': '4,3' }));
    items.forEach((it, i) => {
      const y = f.y0 + i * rowH + rowH / 2;
      f.svg.appendChild(el('text', { x: f.x0 - 10, y: y + 4, 'text-anchor': 'end', 'font-size': 11.5,
        fill: INK, 'font-weight': 600 }, it.name));
      f.svg.appendChild(el('line', { x1: X(it.lo), y1: y, x2: X(it.hi), y2: y, stroke: INK, 'stroke-width': 1.6 }));
      const sig = Math.abs(it.t) >= 2;
      f.svg.appendChild(el('circle', { cx: X(it.est), cy: y, r: sig ? 5.5 : 4.5,
        fill: sig ? '#1f5c46' : MUTED }));
      f.svg.appendChild(el('text', { x: f.x1 + 8, y: y + 4, 'font-size': 10.5,
        fill: sig ? INK : MUTED, 'font-weight': sig ? 700 : 400 }, 't=' + signed(it.t, 1)));
    });
  }

  global.Charts = { lines, bars, hbars, forest, SEQ, fmt, signed };
})(window);
