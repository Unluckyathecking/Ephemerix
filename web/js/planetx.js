// Planet X page: what we found on real objects (planetxfound.js), then brightness-vs-distance plot, reach table and motion
// table, all drawn from data/planetx-limits.json. Plotly is the vendored build, lazy-loaded.

import { el, $ } from './dom.js';
import { bestReach, reachText, depthLinesFor, caseSeries, fortneySeries, reachBars, leadAnswer, P9_RANGE_AU } from './planetxdata.js';
import { reachTraces, reachLayout } from './planetxreach.js';
import { foundLines } from './planetxfound.js';
import { loadPlotly, plotLayout, PLOT, PLOT_CONFIG } from './plottheme.js';
import { mountChrome } from './chrome.js';
import { pageTitle } from './site.js';
import { openLinkedSection } from './openhash.js';

const DATA_URL = new URL('../data/planetx-limits.json', import.meta.url);
const MOVERS_URL = new URL('../data/movers.json', import.meta.url);
const P9_URL = new URL('../data/p9-search.json', import.meta.url);
const BODIES_URL = new URL('../data/body-recovery.json', import.meta.url);
const HAUMEA_URL = new URL('../gallery/haumea/manifest.json', import.meta.url);
const MAKEMAKE_URL = new URL('../gallery/makemake/manifest.json', import.meta.url);
/** A JSON file, or null if it cannot be read: these lines are extras, the page stands without them. */
const getJson = (url) => fetch(url, { headers: { Accept: 'application/json' } }).then((r) => (r.ok ? r.json() : null), () => null).catch(() => null);
const CASE_STYLE = {
  se5: { color: PLOT.accent, dash: 'dot' },
  se10: { color: PLOT.accent, dash: 'solid' },
  neptune: { color: PLOT.ink2, dash: 'solid' },
  jupiter: { color: PLOT.muted, dash: 'dash' },
};
const DEPTH_STYLE = {
  spx_one_map_channel: { fill: 'rgba(230,232,235,0.16)', dash: 'solid' },
  spx_one_map_band: { fill: 'rgba(230,232,235,0.08)', dash: 'dash' },
  spx_measured_channel: { fill: 'rgba(255,139,122,0.14)', dash: 'dot' },
  spx_four_map_channel: { fill: 'rgba(230,232,235,0.05)', dash: 'longdash' },
  wise: { fill: 'rgba(86,216,236,0.16)', dash: 'solid' },
};
const DEFAULT_BAND = 'SPHEREx D1';

function caseTraces(data, band) {
  return data.cases.flatMap((c) => {
    const s = caseSeries(data, c, band);
    const st = CASE_STYLE[c.key] || { color: PLOT.ink2, dash: 'solid' };
    const shade = { type: 'scatter', mode: 'lines', x: s.x, line: { width: 0 }, hoverinfo: 'skip', showlegend: false };
    return [
      { ...shade, y: s.hi },
      { ...shade, y: s.lo, fill: 'tonexty', fillcolor: c.key === 'se10' ? 'rgba(255,181,71,0.12)' : 'rgba(179,185,194,0.07)' },
      { type: 'scatter', mode: 'lines', name: c.label, x: s.x, y: s.nom, line: { color: st.color, dash: st.dash, width: 2 },
        hovertemplate: `%{x} au: AB %{y:.1f}<extra>${c.label}</extra>` },
    ];
  });
}

function fortneyTraces(data, band) {
  const f = fortneySeries(data, band);
  if (!f) return [];
  const line = { type: 'scatter', mode: 'lines', x: f.x, line: { width: 1, color: 'rgba(86,216,236,0.6)', dash: 'dot' } };
  return [
    { ...line, y: f.bright, name: 'Methane-depleted, 50 K (Fortney 2016)', hovertemplate: '%{x} au: AB %{y:.1f}<extra>Fortney 50 K</extra>' },
    { ...line, y: f.faint, name: 'Methane-depleted, 40 K (Fortney 2016)', hovertemplate: '%{x} au: AB %{y:.1f}<extra>Fortney 40 K</extra>' },
  ];
}

const edge = (fill) => fill.replace(/[\d.]+\)$/, '0.7)');

/** The survey-depth bands as shapes, with the 400 to 800 au strip behind them. */
function depthShapes(data, band) {
  const shapes = [{ type: 'rect', xref: 'x', yref: 'paper', x0: 400, x1: 800, y0: 0, y1: 1,
    fillcolor: 'rgba(255,181,71,0.06)', line: { width: 0 }, layer: 'below' }];
  for (const d of depthLinesFor(data, band)) {
    const st = DEPTH_STYLE[d.key] || DEPTH_STYLE.spx_four_map_channel;
    shapes.push({ type: 'rect', xref: 'paper', yref: 'y', x0: 0, x1: 1, y0: d.shallow, y1: d.deep,
      fillcolor: st.fill, line: { width: 1, color: edge(st.fill), dash: st.dash }, layer: 'below' });
  }
  return shapes;
}

/** One legend entry per depth band (the bands themselves are shapes, which a legend cannot list). */
function depthLegend(data, band, narrow) {
  // On a phone a long name breaks after its first comma, so the legend is not cut off.
  const fit = (name) => (narrow ? name.replace(', ', ',<br>') : name);
  return depthLinesFor(data, band).map((d) => {
    const st = DEPTH_STYLE[d.key] || DEPTH_STYLE.spx_four_map_channel;
    return { type: 'scatter', mode: 'lines', x: [null], y: [null], hoverinfo: 'skip', legendgroup: 'depths',
      name: fit(`Depth: ${d.label.includes(d.kind) ? d.label : `${d.label} (${d.kind})`}`), line: { color: edge(st.fill), dash: st.dash, width: 6 } };
  });
}

function layout(data, band, narrow) {
  // On a phone the legend runs to eight lines, so it sits lower and the plot is taller (planetx.css).
  return plotLayout({
    x: { title: 'Distance from the Sun (au)', range: [200, 1500] },
    y: { title: `${band}, AB magnitude (brighter up)`, range: [27, 14] },
    extra: { margin: { l: 58, r: 10, t: 12, b: 46 }, shapes: depthShapes(data, band),
      annotations: [{ x: 600, xref: 'x', y: 1, yref: 'paper', yanchor: 'top', showarrow: false, text: 'Planet Nine, 400 to 800 au', font: { size: 11, color: PLOT.accent, family: PLOT.mono } }],
      legend: { orientation: 'h', y: narrow ? -0.32 : -0.2, x: 0, font: { size: 11, color: PLOT.ink2 }, traceorder: 'normal' } },
  });
}

function plotNote(band) {
  if (band.startsWith('WISE')) return 'WISE bands: the dotted lines are the methane-depleted thermal models of Fortney et al. 2016 for a Neptune-sized planet; their bright end is already excluded by Meisner et al. 2018 inside about 800 au.';
  if (band === 'SPHEREx D5' || band === 'SPHEREx D6') return 'At 3.8 to 5 µm the Jupiter analogue is drawn as a blackbody, which badly underestimates a giant planet there; read it as a lower bound.';
  if (band === 'SPHEREx D4') return 'Reflected sunlight and a blackbody only. The methane-depleted models that peak near 3.3 µm are published only as WISE magnitudes, so they are shown on W1 and W2, not here.';
  return 'Reflected sunlight with a grey albedo; methane bands at 1.7, 2.3 and 3.3 µm would make a real ice giant darker.';
}

function renderPlot(card, data) {
  const plot = $('.px-plot', card);
  const note = $('.px-plot-note', card);
  const group = $('.px-bands', card);
  const buttons = data.bands.map((b) => el('button', { type: 'button', class: 'seg', 'aria-pressed': String(b.name === DEFAULT_BAND),
    text: b.name.replace('SPHEREx ', '').replace('WISE ', ''), title: `${b.name}, ${b.lo_um}-${b.hi_um} µm`,
    onClick: () => draw(b.name) }));
  group.replaceChildren(...buttons);

  async function draw(band) {
    buttons.forEach((btn, i) => btn.setAttribute('aria-pressed', String(data.bands[i].name === band)));
    note.textContent = plotNote(band);
    try {
      const Plotly = await loadPlotly();
      await Plotly.react(plot, [...caseTraces(data, band), ...fortneyTraces(data, band), ...depthLegend(data, band, plot.clientWidth < 500)], layout(data, band, plot.clientWidth < 500), PLOT_CONFIG);
    } catch {
      plot.replaceChildren(el('p', { class: 'muted', text: 'The plotting library could not be loaded; the tables below hold the same conclusions.' }));
    }
  }
  // The plot sits in a closed section: draw it when that opens, so Plotly sees its real width.
  const box = card.closest('details');
  if (!box || box.open) draw(DEFAULT_BAND);
  else box.addEventListener('toggle', () => draw(DEFAULT_BAND), { once: true });
}

function table(head, rows) {
  return el('table', {}, [
    el('thead', {}, [el('tr', {}, head.map((h) => el('th', { scope: 'col', text: h })))]),
    el('tbody', {}, rows.map((r) => el('tr', {}, r.map((c, i) => el(i ? 'td' : 'th', { scope: i ? null : 'row', text: c }))))),
  ]);
}

function renderReach(host, data) {
  const depths = data.depths.map((d) => d.key);
  const label = Object.fromEntries(data.depths.map((d) => [d.key, d.label]));
  host.replaceChildren(table(['Planet', ...depths.map((k) => label[k])],
    data.cases.map((c) => [c.label, ...depths.map((k) => reachText(bestReach(c, k)))])));
}

function renderMotion(host, data) {
  const rows = data.motion.rows.map((r) => [
    `${r.r_au} au`, `${r.between_passes_arcmin}′`, `${r.per_day_arcsec['0']}″ / ${r.per_day_arcsec['30']}″ / ${r.per_day_arcsec['60']}″`,
    `${r.in_pass_px['0']} / ${r.in_pass_px['30']} / ${r.in_pass_px['60']} px`,
  ]);
  host.replaceChildren(table(['Distance', 'Jump between passes (6 months)', 'Per day, ecliptic latitude 0° / 30° / 60°',
    `Across a ${data.motion.pass_days}-day pass`], rows));
}

function fillReachSpans(data) {
  for (const span of document.querySelectorAll('[data-reach]')) {
    const [caseKey, depthKey] = span.dataset.reach.split(':');
    const c = data.cases.find((x) => x.key === caseKey);
    const r = c && bestReach(c, depthKey);
    if (r) span.textContent = reachText(r);
  }
}

/** The jump between passes, read from the motion table: data-shift="1000" or "1000:300" (au). */
function fillShiftSpans(data) {
  const at = (r) => data.motion.rows.find((x) => x.r_au === Number(r))?.between_passes_arcmin;
  for (const span of document.querySelectorAll('[data-shift]')) {
    const vals = span.dataset.shift.split(':').map(at);
    if (vals.every(Number.isFinite)) span.textContent = vals.map((v) => String(Math.round(v))).join(' to ');
  }
}

/** The pilot search of the Planet Nine region, from its own report; left empty if that cannot be read. */
async function fillPilot() {
  const p9 = await getJson(P9_URL);
  if (p9?.pooled && Number.isFinite(p9.area_deg2)) {
    $('#px-blind').replaceChildren(`A pilot run of our search on ${p9.n_fields} fields (${p9.area_deg2.toFixed(1)} deg²) where Planet Nine is predicted gives upper limits only and excludes none of the favoured cases. `,
      el('a', { href: 'search.html#p9', text: 'See the pilot search' }), '.');
  }
}

/** What we found on real objects, one line each; the static list stays if the data cannot be read. */
async function fillFound() {
  const [movers, bodies, haumea, makemake] = await Promise.all([MOVERS_URL, BODIES_URL, HAUMEA_URL, MAKEMAKE_URL].map(getJson));
  const lines = foundLines({ movers, bodies, haumea, makemake });
  if (!lines.length) return;
  $('#px-found-list').replaceChildren(...lines.map((l) => el('li', {}, [`${l.text} `, el('a', { href: l.href, text: l.link }),
    ...(l.href2 ? [', ', el('a', { href: l.href2, text: l.link2 })] : []), '.'])));
}

function fillAnswer(data) {
  const lead = leadAnswer(data);
  if (lead) $('#px-answer').replaceChildren(el('strong', { text: lead.verdict }), ` ${lead.detail}`);
}

async function renderReachPlot(host, data) {
  try {
    const Plotly = await loadPlotly();
    const bars = { channel: reachBars(data, 'spx_one_map_channel'), band: reachBars(data, 'spx_one_map_band') };
    await Plotly.react(host, reachTraces(bars), reachLayout(bars, P9_RANGE_AU, host.clientWidth < 500), { ...PLOT_CONFIG, displayModeBar: false });
  } catch {
    host.replaceChildren(el('p', { class: 'muted', text: 'The plotting library could not be loaded; the numbers are in the sections below.' }));
  }
}

async function main() {
  const card = $('.px-plot-card');
  let data;
  try {
    const res = await fetch(DATA_URL, { headers: { Accept: 'application/json' } });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    data = await res.json();
  } catch (err) {
    $('.px-reach-card').append(el('p', { class: 'banner', role: 'alert', text: `The limits table could not be loaded (${err.message}).` }));
    return;
  }
  fillAnswer(data);
  renderReachPlot($('#px-reach-plot'), data);
  fillReachSpans(data);
  fillShiftSpans(data);
  renderPlot(card, data);
  renderReach($('#px-reach'), data);
  renderMotion($('#px-motion'), data);
}

mountChrome('planetx');
openLinkedSection();
document.title = pageTitle('Planet X: what we found, and how far SPHEREx can see');
fillFound();
fillPilot();
main();
