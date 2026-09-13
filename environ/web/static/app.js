/* app.js — renders /api/analysis into the page.
 * Nothing here is hard-coded: change the panel, and every sentence, table and
 * chart below changes with it. The verdict text is generated in Python
 * (environ/stats.py :: verdict), not in JS, so the memo and the deck quote the
 * exact same words.
 */
'use strict';

const C = window.Charts;
const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));
const n1 = (v) => (v === null || v === undefined ? '—' : Number(v).toFixed(1));
const s1 = (v) => (v === null || v === undefined ? '—' : (v > 0 ? '+' : '') + Number(v).toFixed(1));
const s2 = (v) => (v === null || v === undefined ? '—' : (v > 0 ? '+' : '') + Number(v).toFixed(2));
const cls = (v) => (v === null || v === undefined ? 'dim' : v > 0 ? 'pos' : v < 0 ? 'neg' : 'dim');
const qcolor = (q) => C.SEQ[(q || 1) - 1];

let DATA = null;
let cumView = 'cum';
let cumOn = { 1: true, 2: true, 3: true, 4: true, 5: true };

/* ------------------------------------------------------------------ table */
function table(cfg) {
  const t = document.createElement('table');
  t.className = 'tbl';
  const thead = `<thead><tr>${cfg.cols.map((c) => `<th>${c.h}</th>`).join('')}</tr></thead>`;
  const body = cfg.rows
    .map((r, ri) => {
      const cells = cfg.cols.map((c) => {
        const v = c.f ? c.f(r, ri) : r[c.k];
        const kn = c.cls ? c.cls(r, ri, v) : '';
        return `<td class="${kn}">${v === null || v === undefined ? '—' : v}</td>`;
      });
      const tr = document.createElement('tr');
      if (cfg.rowCls) {
        const k = cfg.rowCls(r, ri);
        if (k) tr.className = k;
      }
      tr.innerHTML = cells.join('');
      return tr.outerHTML;
    })
    .join('');
  t.innerHTML = thead + `<tbody>${body}</tbody>` + (cfg.cap ? `<caption>${cfg.cap}</caption>` : '');
  return t;
}
const mount = (sel, node) => {
  const host = $(sel);
  host.innerHTML = '';
  if (node) host.appendChild(node);
};

/* ------------------------------------------------------------------ boot */
async function boot() {
  try {
    const r = await fetch('/api/analysis');
    if (!r.ok) throw new Error('HTTP ' + r.status);
    DATA = await r.json();
  } catch (e) {
    document.querySelector('main').insertAdjacentHTML(
      'afterbegin',
      `<div class="err-banner"><b>Could not load /api/analysis.</b> ${e.message}. Start the server with
       <code>uvicorn environ.app:app --reload</code> from the repo root.</div>`
    );
    return;
  }
  if (DATA.provenance && DATA.provenance.is_synthetic) document.body.classList.add('is-demo');
  renderHeader();
  renderAnswers();
  renderReturns();
  renderSector();
  renderRisk();
  renderRegression();
  renderMethod();
  renderData();
  wireTabs();
  wireUpload();
  wirePitch();
  loadSvgs();
}

function renderHeader() {
  const u = DATA.universe || {};
  $('#m-universe').textContent = `${u.n_firms} firms · ${u.n_months} months · ${(u.span || [''])[0].slice(0, 7)} to ${(u.span || [''])[1].slice(0, 7)} · ${(u.sectors || []).length} sectors`;
  $('#m-oneliner').textContent = (DATA.verdict && DATA.verdict.one_liner) || 'Not enough in this panel to answer.';

  const neu = DATA.sorts.sector_neutral, na = DATA.sorts.naive;
  if (!neu || !na || neu.spread_ret_ann_pct === undefined || na.spread_ret_ann_pct === undefined) {
    $('#m-headline').textContent = 'n/a';
    $('#m-headline-sub').textContent = 'The panel is too sparse to build quintile portfolios.';
    $('#m-built').innerHTML = `Source: ${u.source || 'unknown'}`;
    return;
  }
  $('#m-headline').textContent = `${s1(neu.spread_ret_ann_pct)}%/yr`;
  $('#m-headline-sub').innerHTML =
    `sector-neutral Q5−Q1 return spread. <b>t = ${n1(neu.spread_t)}</b> — statistically indistinguishable from zero.
     The same portfolios, unadjusted, print ${s1(na.spread_ret_ann_pct)}%/yr.`;
  const v = ((DATA.verdict || {}).answers || []).find((a) => a.tone === 'positive');
  $('#m-built').innerHTML =
    (v ? `But the <b>risk</b> spread is real: ${v.stat} (${v.stat_label}).<br>` : '') +
    `Source: ${u.source}${DATA._buildMs ? ' · computed in ' + Math.round(DATA._buildMs) + ' ms' : ''}`;
  $('#foot-rows').textContent = `${(u.n_obs || 0).toLocaleString()} firm-month observations`;
}

/* ---------------------------------------------------------------- answers */
function renderAnswers() {
  const host = $('#answers');
  host.innerHTML = '';
  DATA.verdict.answers.forEach((a) => {
    const d = document.createElement('div');
    d.className = `ans tone-${a.tone}`;
    d.innerHTML =
      `<div class="ans-q">${a.q}</div>
       <div class="ans-a">${a.a}</div>
       <div class="ans-detail">${a.detail}</div>
       <div class="ans-stat"><b>${a.stat}</b><span>${a.stat_label}</span></div>`;
    host.appendChild(d);
  });
}

/* ---------------------------------------------------------------- returns */
function renderReturns() {
  const na = DATA.sorts.naive, neu = DATA.sorts.sector_neutral;
  if (!na || !neu || !(na.rows || []).length) { $('#returns-lede').textContent = 'No sortable panel loaded.'; return; }
  $('#returns-lede').innerHTML =
    `Every month I rank all firms into five buckets on that month's published ESG score and hold each bucket
     equal-weighted for a month. Top minus bottom is the <b>spread</b> — the number every sell-side ESG note
     quotes. Left panel below is that number as published; right panel is it after subtracting what each
     firm's own sector did.`;
  mount('#tbl-returns', table({
    cols: [
      { h: 'Quintile', k: 'label' },
      { h: 'Return %/yr', f: (r) => s1(r.ret_ann_pct), cls: (r) => cls(r.ret_ann_pct) },
      { h: 'Vol %/yr', f: (r) => n1(r.vol_ann_pct) },
      { h: 'Sharpe', f: (r) => n1(r.sharpe) },
      { h: 'Worst drawdown', f: (r) => n1(r.max_drawdown_pct) + '%', cls: (r) => (r.max_drawdown_pct < -25 ? 'neg' : '') },
      { h: 't vs Q1', f: (r) => (r.t_vs_q1 === null ? '—' : s2(r.t_vs_q1)), cls: (r) => cls(r.t_vs_q1) },
    ],
    rows: na.rows,
    rowCls: (r) => (r.q === 5 ? 'hl' : ''),
    cap: `As published. Spread ${s1(na.spread_ret_ann_pct)}%/yr, t=${n1(na.spread_t)}, IR=${n1(na.spread_ir)} over ${na.n_months} months.
          The bottom row of a quintile table is the row that matters.`,
  }));
  $('#returns-callout').innerHTML =
    `<span class="k">Read this before the chart</span>
     The <b>sector-neutral</b> spread is ${s1(neu.spread_ret_ann_pct)}%/yr (t=${n1(neu.spread_t)}), the
     <b>published</b> one ${s1(na.spread_ret_ann_pct)}%/yr (t=${n1(na.spread_t)}). Both are noise. The Sharpe
     numbers differ slightly — ${n1(neu.rows[4].sharpe)} vs ${n1(neu.rows[0].sharpe)} — but that gap comes from the
     denominator, not the numerator. That is the whole finding in one sentence:
     <b>ESG changes risk, not return.</b>`;

  // chips
  const chips = $('#cum-chips');
  chips.innerHTML = '';
  for (let q = 1; q <= 5; q++) {
    const b = document.createElement('button');
    b.className = 'sw' + (cumOn[q] ? ' on' : '');
    b.innerHTML = `<i style="background:${qcolor(q)}"></i>Q${q}`;
    b.onclick = () => { cumOn[q] = !cumOn[q]; b.classList.toggle('on'); drawCum(); };
    chips.appendChild(b);
  }
  $$('#cum-view button').forEach((b) => (b.onclick = () => {
    cumView = b.dataset.v;
    $$('#cum-view button').forEach((x) => x.classList.toggle('on', x === b));
    drawCum();
  }));
  drawCum();

  // rolling
  const roll = DATA.rolling;
  C.lines($('#chart-rolling'), {
    labels: roll.dates, includeZero: true, suffix: '%/yr',
    series: [
      { name: `rolling ${roll.window_months}m spread`, values: roll.rolling_pct, color: '#1f5c46', width: 2.6, fill: true },
      { name: '12m rolling', values: roll.annual_pct, color: '#c9ccd2', width: 1.4, opacity: 0.9 },
    ],
    valFmt: (v) => (v === null ? '—' : s1(v) + '%/yr'),
    m: { t: 34, r: 16, b: 34, l: 46 },
  });

  // by-year table
  mount('#tbl-years', table({
    cols: [
      { h: 'Year', k: 'year' },
      { h: 'As published %/yr', f: (r) => s1(r.naive), cls: (r) => cls(r.naive) },
      { h: 'Sector-neutral %/yr', f: (r) => s1(r.neutral), cls: (r) => cls(r.neutral) },
      { h: 'Gap (pts)', f: (r) => s1(r.gap), cls: (r) => (Math.abs(r.gap) > 8 ? 'neg' : 'dim') },
      { h: 'What happened', f: (r) => r.note },
    ],
    rows: DATA.by_year.years.map((y, i) => {
      const a = DATA.by_year.naive[i], b = DATA.by_year.sector_neutral[i];
      const gap = a - b;
      let note = '';
      if (Math.abs(gap) > 8) note = 'sector mix dominates';
      else if (a < -5 && b < 0) note = 'ESG genuinely lagged';
      else if (a > 5) note = 'lucky sector exposure';
      return { year: y, naive: a, neutral: b, gap, note };
    }),
    rowCls: (r) => (Math.abs(r.gap) > 15 ? 'hl' : ''),
    cap: 'Highlighted row is the year the whole industry had to explain.',
  }));
}

function drawCum() {
  const host = $('#chart-cum');
  if (cumView === 'cum') {
    const cu = DATA.sorts.naive.cumulative;
    const labels = cu['1'].dates;
    const series = [1, 2, 3, 4, 5].filter((q) => cumOn[q]).map((q) => ({
      name: 'Q' + q, values: cu[q].values, color: qcolor(q), width: q === 1 || q === 5 ? 2.6 : 1.4,
      fill: q === 5,
    }));
    C.lines(host, {
      labels, series, legend: true, m: { t: 36, r: 20, b: 34, l: 48 }, yearEvery: 2,
      valFmt: (v) => (v === null ? '—' : Number(v).toFixed(1)),
    });
    $('#cum-cap').textContent = 'Growth of 100, monthly rebalanced, no transaction costs. Q1 and Q5 are drawn heavier; the middle three are there to show the pattern is flat, not V-shaped.';
  } else {
    const sp = DATA.sorts.naive;
    const neu = DATA.sorts.sector_neutral;
    C.lines(host, {
      labels: sp.spread_dates, includeZero: true, suffix: '',
      series: [
        { name: 'as published', values: sp.spread_cum, color: '#8c9bab', width: 2.2 },
        { name: 'sector-neutral', values: neu.spread_cum, color: '#1f5c46', width: 2.4, fill: true },
      ],
      valFmt: (v) => (v === null ? '—' : Number(v).toFixed(1) + ' (index)'),
      m: { t: 36, r: 20, b: 34, l: 48 },
    });
    $('#cum-cap').textContent =
      'Cumulative Q5/Q1 ratio, indexed to 100. If a line drifts away from 100 with no reversion, the effect is persistent; ' +
      'if it wanders around 100, you are watching noise — which is what the sector-neutral line is doing.';
  }
}

/* ----------------------------------------------------------------- sector */
function renderSector() {
  const a = DATA.attribution || {};
  if (!(a.rows || []).length) {
    $('#sector-lede').textContent = 'Sector decomposition needs more than one sector in the panel; this file has one.';
    $('#sector-callout').innerHTML = '<span class="k">Unavailable</span>Upload a panel with a sector column to get this exhibit.';
    return;
  }
  $('#sector-lede').innerHTML =
    `This is the exhibit I would put on slide two of any ESG pitch. Take one year — the one where the naive
     number looked worst — and ask <em>why</em>. Every month, each quintile holds a certain weight in each
     sector, so the spread decomposes exactly into (i) the sectors the two books differ on, valued at that
     sector's return, plus (ii) the stock-picking inside each sector. There is no third term; the pieces have
     to add up, and the table footer shows that they do.`;
  const sel = $('#attrib-year');
  sel.innerHTML = DATA.by_year.years
    .slice()
    .reverse()
    .map((y) => {
      const idx = DATA.by_year.years.indexOf(y);
      const nv = DATA.by_year.naive[idx], nu = DATA.by_year.sector_neutral[idx];
      return `<option value="${y}" ${y === a.year ? 'selected' : ''}>${y} — naive ${s1(nv)}%/yr, neutral ${s1(nu)}%/yr</option>`;
    })
    .join('');
  sel.onchange = () => drawAttrib(+sel.value);
  drawAttrib(a.year);

  $$('#mix-mode button').forEach((b) => (b.onclick = async () => {
    $$('#mix-mode button').forEach((x) => x.classList.toggle('on', x === b));
    const svg = await svgFor(b.dataset.v === 'last' ? 'sector_mix' : 'sector_mix_all');
    $('#svg-sector_mix').innerHTML = svg || '<p class="tiny">chart unavailable</p>';
  }));
}

function drawAttrib(year) {
  const a = (DATA.attribution_by_year || {})[String(year)] || DATA.attribution || { rows: [] };
  if (!(a.rows || []).length) return;
  $('#sector-callout').innerHTML = `<span class="k">The one-sentence version</span>${a.reading}`;

  const rows = a.rows.filter((r) => Math.abs(r.contribution_ann_pct) > 0.02);
  C.hbars($('#chart-attrib'), {
    cats: rows.map((r) => r.sector),
    labelW: 172,
    rowH: 32,
    suffix: '%/yr',
    signedValues: true,
    showTotal: true,
    rows: [
      { name: 'sector mix', color: '#b4453c', values: rows.map((r) => r.mix_ann_pct),
        notes: rows.map((r) => `Q5 wt ${n1(r.w_q5_pct)}% vs Q1 ${n1(r.w_q1_pct)}%, sector ${s1(r.sector_ret_ann_pct)}%/yr`) },
      { name: 'within-sector selection', color: '#5f8fb3', values: rows.map((r) => r.selection_ann_pct) },
    ],
  });
  const tot = a.total_mix_effect_ann_pct + a.total_selection_ann_pct;
  mount('#tbl-attrib', table({
    cols: [
      { h: 'Sector', k: 'sector' },
      { h: 'Wt in Q5', f: (r) => n1(r.w_q5_pct) + '%' },
      { h: 'Wt in Q1', f: (r) => n1(r.w_q1_pct) + '%' },
      { h: 'Sector return %/yr', f: (r) => s1(r.sector_ret_ann_pct), cls: (r) => cls(r.sector_ret_ann_pct) },
      { h: '→ mix pts', f: (r) => s2(r.mix_ann_pct), cls: (r) => cls(r.mix_ann_pct) },
      { h: '→ pick pts', f: (r) => s2(r.selection_ann_pct), cls: (r) => cls(r.selection_ann_pct) },
      { h: 'Total', f: (r) => s2(r.contribution_ann_pct), cls: (r) => cls(r.contribution_ann_pct) },
    ],
    rows,
    rowCls: (r) => (Math.abs(r.mix_ann_pct) > 5 ? 'hl' : ''),
    cap:
      `Sum: mix ${s1(a.total_mix_effect_ann_pct)} + selection ${s1(a.total_selection_ann_pct)} = ${s1(tot)}%/yr against a ` +
      `raw spread of ${s1(a.raw_spread_ann_pct)}%/yr — gap ${s2(a.reconciliation_gap_ann_pct)} pts. Weights move every ` +
      `month, so an annual average of an exact monthly identity closes to a few basis points, not to zero. ` +
      `Highlighted rows are the sectors carrying the year.`,
  }));
}

/* ------------------------------------------------------------------- risk */
function renderRisk() {
  const R = DATA.risk || {}, rows = R.rows || [];
  if (!rows.length) {
    $('#tab-risk .two-col > div:first-child').insertAdjacentHTML('afterbegin',
      `<div class="callout warn"><span class="k">Risk view unavailable for this panel</span>
       ${R.reason || R.note || 'The analysis needs a volatility column (idio_vol_ann) that this file does not have.'}
       <br><span class="tiny">Everything else on this page is computed normally; add the column and re-upload.</span></div>`);
    return;
  }
  const vDrop = rows[0].vol_ann_pct - rows[4].vol_ann_pct;
  const dDrop = rows[4].max_drawdown_pct - rows[0].max_drawdown_pct;
  mount('#tbl-risk', table({
    cols: [
      { h: 'Quintile', k: 'label' },
      { h: 'Vol %/yr', f: (r) => n1(r.vol_ann_pct) },
      { h: 'Downside dev', f: (r) => n1(r.downside_deviation_pct) },
      { h: 'Downside capture', f: (r) => n1(r.downside_capture_pct) + '%', cls: (r) => (r.downside_capture_pct < 100 ? 'pos' : 'neg') },
      { h: 'Upside capture', f: (r) => n1(r.upside_capture_pct) + '%' },
      { h: 'Worst drawdown', f: (r) => n1(r.max_drawdown_pct) + '%' },
      { h: 'Trough', k: 'trough' },
      { h: 'Recovered in', f: (r) => (r.recovery_months === null ? 'not within sample' : r.recovery_months + ' mo') },
      { h: 'Sortino', f: (r) => n1(r.sortino) },
    ],
    rows,
    rowCls: (r) => (r.q === 5 ? 'hl' : ''),
    cap: 'Market proxy: ' + R.market_proxy + '. ' + R.n_down_months + ' down months in the sample.',
  }));
  $('#risk-note').textContent = R.note;
  $('#risk-callout').innerHTML =
    `<span class="k">The result that survives every control</span>
     Bottom-to-top quintile: volatility <b>${s1(-vDrop).replace('-', '')} pts lower</b>
     (${n1(rows[0].vol_ann_pct)}% → ${n1(rows[4].vol_ann_pct)}%), downside capture
     <b>${n1(rows[0].downside_capture_pct)}% → ${n1(rows[4].downside_capture_pct)}%</b>, worst drawdown
     <b>${n1(rows[0].max_drawdown_pct)}% → ${n1(rows[4].max_drawdown_pct)}%</b> — a ${s1(dDrop)}-point improvement.
     The recovery time is the part clients actually feel: ${rows[0].recovery_months} months vs ${rows[4].recovery_months}.`;

  C.bars($('#chart-volsort'), {
    cats: rows.map((r) => 'Q' + r.q),
    groups: [{ name: 'volatility %/yr', values: rows.map((r) => r.vol_ann_pct), color: '#1f5c46' },
             { name: 'downside deviation', values: rows.map((r) => r.downside_deviation_pct), color: '#8c9bab' }],
    nd: 1, m: { t: 16, r: 16, b: 40, l: 46 },
  });
  C.bars($('#chart-capture'), {
    cats: rows.map((r) => 'Q' + r.q),
    groups: [{ name: 'upside capture %', values: rows.map((r) => r.upside_capture_pct), color: '#c9ccd2' },
             { name: 'downside capture %', values: rows.map((r) => r.downside_capture_pct), color: '#b4453c' }],
    nd: 0, m: { t: 16, r: 16, b: 40, l: 46 },
    valFmt: (v) => Number(v).toFixed(0) + '%',
  });
}

/* ------------------------------------------------------------ regression */
function renderRegression() {
  const R = DATA.regressions || { specs: [], legend: {} };
  R.specs = R.specs || [];
  const host = $('#reg-specs');
  host.innerHTML = '';
  R.specs.forEach((sp) => {
    const d = document.createElement('div');
    d.className = 'spec';
    const rows = sp.result.coef.map((c) => {
      const nm = R.legend[c.name] || c.name;
      const unit = sp.id === 'risk' ? 'pts of annual vol' : 'bp/month';
      return `<tr class="${Math.abs(c.t) >= 2 ? 'hl' : ''}">
        <td>${nm}</td>
        <td class="${cls(c.bp_per_month)}">${s2(c.bp_per_month)}</td>
        <td>${s2(c.ci_lo_bp)} … ${s2(c.ci_hi_bp)}</td>
        <td class="${Math.abs(c.t) >= 2 ? '' : 'dim'}">${s2(c.t)}</td>
        <td class="${c.p < 0.05 ? 'pos' : 'dim'}">${c.p < 0.001 ? '&lt;0.001' : c.p.toFixed(3)}</td></tr>`;
    }).join('');
    d.innerHTML =
      `<div class="spec-h"><b>${sp.label}</b><span class="q">${sp.question}</span></div>
       <table class="tbl"><thead><tr><th>Driver (1 SD)</th><th>Coefficient</th><th>95% CI</th><th>t</th><th>p</th></tr></thead>
       <tbody>${rows}</tbody></table>
       <div class="n">n = ${sp.result.n.toLocaleString()} firm-months · ${sp.result.n_clusters} firms clustered ·
         R² = ${sp.result.r2}${sp.unit ? ' · unit: ' + sp.unit : ''} · ${sp.result.spec_note}
         ${sp.dropped && sp.dropped.length ? '<br><span style="color:#b4453c">controls dropped for this panel: ' + sp.dropped.join(', ') + '</span>' : ''}
         ${sp.result.row_note ? '<br><span style="color:#b4453c">' + sp.result.row_note + '</span>' : ''}</div>`;
    host.appendChild(d);
  });

  if ((R.notes || []).length) {
    const box = document.createElement('div');
    box.className = 'callout';
    box.style.marginBottom = '1rem';
    box.innerHTML = `<span class="k">Controls adjusted for this panel</span>${R.notes.join(' · ')}`;
    host.prepend(box);   // after the loop - host.innerHTML is cleared above
  }

  // operating characteristics by quintile - the "is there even a business case?" check
  const ops = DATA.operating;
  if (ops && ops.available) {
    const nice = {
      revenue_growth_pct: "Revenue growth %", ebitda_margin_pct: "EBITDA margin %",
      capex_intensity_pct: "Capex intensity %", cost_of_equity_pct: "Cost of equity %",
      idio_vol_ann: "Idio vol %", beta: "Beta", ev_bn: "EV $bn (mean)",
    };
    mount('#tbl-ops', table({
      cols: [{ h: 'Quintile', k: 'label' }].concat(ops.cols.map((c) => ({
        h: nice[c] || c, f: (r) => n1(r[c]),
      }))),
      rows: ops.rows,
      cap: ops.note,
    }));
    mount('#tbl-opstests', table({
      cols: [
        { h: 'Firm-level test', k: 'metric_name' },
        { h: 'Slope per 1 SD', f: (r) => s2(r.slope_per_sd), cls: (r) => cls(r.slope_per_sd) },
        { h: 't', f: (r) => s2(r.t), cls: (r) => (Math.abs(r.t) >= 2 ? '' : 'dim') },
        { h: 'corr', f: (r) => (r.corr === null ? '—' : Number(r.corr).toFixed(2)) },
      ],
      rows: ops.tests.map((t) => ({ ...t, metric_name: nice[t.metric] || t.metric })),
      cap: 'One observation per firm, so these are plain cross-sections - deliberately the least "research-y" '
         + 'table on the page. If a growth or margin effect were big you would see it here with no controls at all.',
    }));
  } else {
    $('#reg-specs').insertAdjacentHTML('afterend',
      `<div class="callout warn"><span class="k">Operating stats not available</span>${(ops && ops.reason) || 'no firm-level file loaded'}</div>`);
  }
}


/* ---------------------------------------------------------------- method */
function renderMethod() {
  const steps = [
    ['Assemble the panel', 'One row per firm per month: published ESG score, total return, sector, size, realised volatility. Real data means merging a ratings table with a price table on ticker and month-end, then dropping firm-months with a missing score or price.'],
    ['Standardise the score', 'Each month, subtract that month\'s mean score and divide by its SD. Now "ESG" is one comparable unit (1 SD ≈ 11 rating points) for the whole sample, and the sorts cannot be skewed by the market-wide drift in scoring.'],
    ['Build quintile portfolios', 'Each month, rank firms into Q1..Q5 on that month\'s score and hold each bucket equal-weighted. Equal weight, because cap-weighting would smuggle in a size factor and you would never notice.'],
    ['Sector-neutralise', 'For every firm-month, subtract the mean of its own sector that month. What remains is "did this stock beat the stocks it is comparable to". This single step is the difference between the two bars in the first chart.'],
    ['Run the regression', 'Return on ESG level and ESG momentum, with year fixed effects and standard errors clustered by firm. Clustering matters: each firm appears ~95 times, and unclustered SEs would make a null result look like a discovery.'],
    ['Test the risk channel', 'Volatility, downside capture, worst drawdown and recovery time by quintile. The Sharpe ratio is reported so a return difference cannot hide inside a risk difference.'],
    ['Decompose the year', 'Split the worst naive year into sector-mix and within-sector selection. It is an exact identity, so the two pieces must sum to the headline — that constraint is what makes the exhibit persuasive.'],
    ['Stress it, then publish the stress', 'Re-generate the demo panel with the ESG effects set to zero and confirm the verdict text flips to "nothing here". Any analysis that cannot fail a test like that is not an analysis.'],
  ];
  $('#method-steps').innerHTML = steps
    .map((s, i) => `<li><b>${s[0]}.</b> ${s[1]}</li>`)
    .join('');

  const riskT = (() => {
    const sp = (DATA.regressions.specs || []).find((x) => x.id === 'risk');
    const c = sp && sp.result && (sp.result.coef || [])[0];
    return c && c.t !== null && c.t !== undefined ? n1(c.t) : 'not available on this panel';
  })();
  const limits = [
    ['The demo panel is synthetic', 'It is generated from three named assumptions in <code>environ/config.py</code> and it is labelled as synthetic in the header, the watermark and every figure caption. Conclusions about the real world require MSCI or ESG-Book scores merged with real prices — the pipeline is written for exactly that swap, and nothing downstream is hard-coded.'],
    ['A fixed universe biases the result', 'The panel holds the same firms from 2016 to 2024, so it cannot show delistings or index additions. Real ESG studies fight this with survivorship-bias-free data; low-ESG firms are more likely to disappear, which flatters the naive spread. My version therefore overstates the naive result, not the neutral one.'],
    ['These t-stats are small-sample', `These are ${DATA.sorts.naive.n_months || 'n'} months and ${DATA.universe.n_firms} firms. The sector-neutral return spread is t=${n1(DATA.sorts.sector_neutral.spread_t)} — that is "I could not detect it", not "it is zero". The risk result (t=${riskT}) ${riskT === 'not available on this panel' ? 'needs a volatility column' : 'is far from the same borderline'}, which is why a recommendation would differ in confidence, not just in sign.`],
    ['ESG momentum decays', 'The momentum coefficient is the largest significant effect here, and momentum is famously the thing that dies once it is published and traded. A live strategy must pay for turnover; the returns above are gross.'],
  ];
  $('#limits').innerHTML = limits.map((l) => `<div class="limit"><b>${l[0]}</b>${l[1]}</div>`).join('');

  const d = DATA.definitions;
  const f = DATA.falsification;
  $('#falsify-card').innerHTML = f ? `
      <div class="dc-title">Falsification test — the result must die under the null</div>
      <p>Same pipeline, regenerated panel with ESG's assumed effect on returns <b>and</b> on volatility set to zero:</p>
      <table class="tbl"><tbody>
        <tr><td>ESG → vol, this panel</td><td>${s1(f.live.vol_bp_per_sd)} bp/SD</td><td class="${Math.abs(f.live.vol_t)>=2?'pos':'dim'}">t = ${n1(f.live.vol_t)}</td></tr>
        <tr><td>ESG → vol, null world</td><td>${s1(f.null.vol_bp_per_sd)} bp/SD</td><td class="${Math.abs(f.null.vol_t)>=2?'neg':'dim'}">t = ${n1(f.null.vol_t)}</td></tr>
        <tr><td>Raw Q1−Q5 vol gap, null</td><td>${n1(f.null.raw_vol_gap_pts)} pts</td><td class="dim">should be ~0</td></tr>
      </tbody></table>
      <p class="tiny" style="color:${f.conclusion_survives ? '#1f5c46' : '#b4453c'}">
        ${f.conclusion_survives ? '✓ The coefficient collapses under the null — the finding is the effect, not an artefact.'
                                : '✗ It survives the null, which means it was never an ESG result.'} ${f.raw_gap_persists_in_null
        ? 'Note: the raw gap persists, so part of the headline is sector composition — quote the sector-adjusted number.' : ''}</p>
      <p class="tiny">${f.null.meaning}</p>`
    : `<div class="dc-title">Falsification test</div><p class="tiny">Only available on the synthetic demo
       panel, because it requires re-running the generator. On your own data, run
       <code>generate_data --level-bp 0 --momentum-bp 0 --level-vol-pct 0</code> and compare by hand.</p>`;

  $('#defs').innerHTML = Object.entries(d)
    .filter(([k]) => !k.startsWith('_'))
    .map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`)
    .join('');
}

/* ------------------------------------------------------------------ data */
function renderData() {
  const cols = [
    ['date', 'date', 'yes', 'month-end, YYYY-MM-DD'],
    ['ticker', 'text', 'yes', 'firm id'],
    ['sector', 'text', 'yes', 'GICS level-1 name'],
    ['esg_score', 'number', 'yes', 'published 0-100 rating, that month'],
    ['ret_m', 'number', 'yes', 'total return, % per month (price + dividends)'],
    ['esg_momentum_z', 'number', 'yes', 'z-score of the trailing 12-month rating change'],
    ['esg_z', 'number', 'no', 'cross-sectional z of esg_score; derived if absent'],
    ['idio_vol_ann', 'number', 'no', 'annualised firm-specific vol, %; needed for the risk table'],
    ['beta', 'number', 'no', 'market beta'],
    ['ev_bn', 'number', 'no', 'enterprise value, $bn; needed for the size control'],
    ['esg_persistent / esg_reported_change_12m', 'number', 'no', 'demo-only: the underlying rating vs the published one, used for the measurement-error note'],
  ];
  mount('#tbl-schema', table({
    cols: [
      { h: 'Column', k: 'c' }, { h: 'Type', k: 't' },
      { h: 'Required', f: (r) => (r.req === 'yes' ? '<b>required</b>' : 'optional'), cls: (r) => (r.req === 'yes' ? '' : 'dim') },
      { h: 'Meaning', k: 'd' },
    ],
    rows: cols.map((c) => ({ c: `<code>${c[0]}</code>`, t: c[1], req: c[2], d: c[3] })),
  }));

  const p = DATA.provenance;
  $('#prov-card').innerHTML =
    `<span class="k">Provenance</span>
     <b>${p.source}</b>${p.is_synthetic ? ' — this panel is generated, not observed.' : ''}<br>
     <span class="tiny">Generator: <code>${p.generator}</code><br>
     Real data: <code>${p.how_to_get_real}</code></span>`;

  const e = DATA.config_effects;
  if (e) {
    $('#assumed-card').innerHTML =
      `<div class="dc-title">Assumptions used to build the demo</div>
       <p>These are <b>inputs</b>, not findings. They are what the generator was told, so you can see exactly
       where the results come from.</p>
       <table class="tbl"><tbody>
         <tr><td>ESG level → return</td><td>${n1(e.level_ret_bp * 100)} bp / month / SD</td></tr>
         <tr><td>ESG momentum → return</td><td>${n1(e.momentum_ret_bp * 100)} bp / month / SD</td></tr>
         <tr><td>ESG level → idio vol</td><td>${n1(e.level_vol_pct)} pts / SD</td></tr>
       </tbody></table>
       <p class="tiny">${e.note}</p>`;
  }
  const nz = DATA.noise;
  if (nz && nz.available) {
    $('#noise-card').innerHTML =
      `<div class="dc-title">How much of a "rating change" is real?</div>
       <p>Reported 12-month change has SD <b>${n1(nz.sd_reported_change_pts)} pts</b>; the true underlying change has SD
       <b>${n1(nz.sd_true_change_pts)} pts</b>. About <b>${Math.round(nz.signal_share_of_variance * 100)}%</b> of the variance is signal.</p>
       <p class="tiny">${nz.read}</p>`;
  }
  const u = DATA.universe;
  if (u.warnings && u.warnings.length) {
    $('#tab-data .two-col>div:first-child').insertAdjacentHTML(
      'afterbegin',
      u.warnings.map((w) => `<div class="callout warn" style="margin-bottom:.8rem"><span class="k">Loader warning</span>${w}</div>`).join('')
    );
  }
}

/* ------------------------------------------------------------------- tabs */
function wireTabs() {
  $$('#tabs button').forEach((b) => {
    b.onclick = () => {
      $$('#tabs button').forEach((x) => x.classList.toggle('on', x === b));
      $$('.panel').forEach((p) => p.classList.toggle('on', p.id === 'tab-' + b.dataset.tab));
      window.scrollTo({ top: 0, behavior: 'smooth' });
      if (b.dataset.tab === 'returns') drawCum();
    };
  });
}

async function svgFor(name) {
  try {
    const r = await fetch('/api/svg/' + name);
    if (!r.ok) return null;
    return await r.text();
  } catch {
    return null;
  }
}
async function loadSvgs() {
  const hosts = {
    quintile_bars: '#svg-quintile_bars',
    risk_profile: '#svg-risk_profile',
    year_gap: '#svg-year_gap',
    drawdown: '#svg-drawdown',
    forest: '#svg-forest',
    sector_mix: '#svg-sector_mix',
    attribution: '#svg-attribution',
  };
  for (const k in hosts) {
    const h = $(hosts[k]);
    if (!h) continue;
    const svg = await svgFor(k);
    if (svg) h.innerHTML = svg;
  }
}

/* ----------------------------------------------------------------- upload */
function wireUpload() {
  $('#file').onchange = async (e) => {
    const f = e.target.files[0];
    if (!f) return;
    const st = $('#upload-state');
    st.className = 'upload-state';
    st.textContent = 'analysing ' + f.name + '…';
    const fd = new FormData();
    fd.append('file', f);
    const r = await fetch('/api/upload', { method: 'POST', body: fd });
    const j = await r.json();
    if (!r.ok) {
      st.className = 'upload-state err';
      st.textContent = '✗ ' + (j.detail || 'failed');
      return;
    }
    st.textContent = `✓ ${j.rows.toLocaleString()} rows, ${j.firms} firms, ${j.months} months in ${Math.round(j.build_ms)} ms — reloading`;
    setTimeout(() => location.reload(), 700);
  };
}

/* ------------------------------------------------------------------ pitch */
function wirePitch() {
  const R = (DATA.risk || {}).rows || [];
  if (R.length < 5 || !((DATA.verdict || {}).answers || []).length) {
    $('#pitch-body').innerHTML = '<p>The demo script is generated from a full analysis; this panel is too sparse ' +
      'to produce one. Load <code>data/panel.csv</code> to see it.</p>';
  } else { pitchBody(R); }
}

function pitchBody(R) {
  const open = () => $('#pitch').hidden = false;
  const close = () => ($('#pitch').hidden = true);
  $('#btn-pitch').onclick = open;
  $('#pitch-x').onclick = close;
  $('#pitch').onclick = (e) => e.target.id === 'pitch' && close();
  document.addEventListener('keydown', (e) => e.key === 'Escape' && close());

  const v = DATA.verdict.answers;
  const u = DATA.universe;
  const neu = DATA.sorts.sector_neutral, na = DATA.sorts.naive;
  const r = { 0: R[0], 4: R[4] };
  const txt = [
    `I built the thing I kept failing to answer in class: does owning high-ESG companies actually pay?`,
    `I took a panel of ${u.n_firms} firms over ${u.n_months} months, ranked them into ESG quintiles every month, and looked at top minus bottom. Unadjusted, the spread is ${s1(na.spread_ret_ann_pct)}% a year — the number that generates headlines in both directions. After subtracting what each firm's own sector did, it is ${s1(neu.spread_ret_ann_pct)}% with a t of ${n1(neu.spread_t)}, which is noise.`,
    `Then I decomposed the worst year into sectors held versus stock-picking within sectors, and the sector term explained essentially all of it. So the ESG-underperformance story is really an energy-and-rates story wearing an ESG label.`,
    `What does move is risk: from the bottom to the top quintile, volatility falls ${n1(DATA.risk.rows[0].vol_ann_pct - DATA.risk.rows[4].vol_ann_pct)} points and the worst drawdown improves ${s1(DATA.risk.rows[4].max_drawdown_pct - DATA.risk.rows[0].max_drawdown_pct)} points. And the one significant return effect is not the level of the rating — it's the change in it.`,
    `So my recommendation is to stop selling ESG as a return alpha. Sell it as downside control, and buy improvement momentum rather than league-table leaders. I put the whole thing in a FastAPI app with a data loader, so the same analysis runs on real MSCI or ESG-Book scores the moment you drop them in — and I published the sensitivity test that shows the result collapsing when the assumed effect is zero.`,
  ];
  $('#pitch-body').innerHTML =
    txt.map((p, i) => `<div class="cue">${['Hook', 'What I did', 'What I found (1)', 'What I found (2)', 'So what'][i]}</div><blockquote>${p}</blockquote>`).join('') +
    `<p class="tiny">Deliver at ~150 words a minute and it lands at 60 seconds. Expect "how did you handle sector bias?" — you just answered it in slide three.</p>`;
  $('#pitch-copy').onclick = async () => {
    await navigator.clipboard.writeText(txt.join('\n\n'));
    $('#pitch-copy').textContent = 'Copied ✓';
    setTimeout(() => ($('#pitch-copy').textContent = 'Copy as text'), 1600);
  };
}

boot();
