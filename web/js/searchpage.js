// "Searching blind for slow movers" page: completeness plot and tables from data/movers.json,
// Planet X distances from data/planetx-limits.json. Plotly is the vendored build, lazy-loaded.

import { el, $ } from './dom.js';
import { curveSeries, binText, peakText, peakTotals, range, brightnessReach, reachText, searchLead } from './searchdata.js';
import { loadPlotly, plotLayout, PLOT, PLOT_CONFIG } from './plottheme.js';
import { mountChrome } from './chrome.js';
import { pageTitle } from './site.js';
import { openLinkedSection } from './openhash.js';
import { renderP9 } from './p9view.js';

const DATA_URL = new URL('../data/movers.json', import.meta.url);
const PLANETX_URL = new URL('../data/planetx-limits.json', import.meta.url);
const P9_URL = new URL('../data/p9-search.json', import.meta.url);
const binCell = (b) => binText(b).replace(' (', '\n(');
const pct = (x) => `${Math.round(x * 1000) / 10}%`;

async function getJson(url) {
  const res = await fetch(url, { headers: { Accept: 'application/json' } });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

function table(head, rows) {
  return el('table', {}, [
    el('thead', {}, [el('tr', {}, head.map((h) => el('th', { scope: 'col', text: h })))]),
    el('tbody', {}, rows.map((r) => el('tr', {}, r.map((c, i) => el(i ? 'td' : 'th', { scope: i ? null : 'row', text: c }))))),
  ]);
}

function renderStats(data) {
  const p = data.pooled.limits;
  const known = data.known_bodies;
  const tot = peakTotals(data.fields, ['tno', 'blank']);
  const items = [
    ['Known dwarf planets found blind', `${known.length} of ${known.length}`, known.map((k) => k.name).join(', ')],
    [`Peaks ${data.campaign.threshold_snr}× above the noise`, `${tot.real} vs ${tot.null}`, `real sky vs the backwards (null) search, ${tot.fields} fields${tot.real <= tot.null ? ': no excess' : ''}`],
    ['Half of planted objects found at', `${p.flux50_ujy} µJy`, `V ${p.vmag50.toFixed(1)}, all fields together (50% complete)`],
    ['9 in 10 found at', `${p.flux90_ujy} µJy`, `V ${p.vmag90.toFixed(1)}, all fields together (90% complete)`],
  ];
  $('#sr-stats').replaceChildren(...items.map(([t, v, s]) => el('div', { class: 'stat' }, [
    el('dt', { text: t }), el('dd', {}, [el('span', { class: 'stat-v', text: v }), el('span', { class: 'small muted', text: s })])])));
}

function traces(data) {
  const fieldLines = data.fields.map((f) => {
    const s = curveSeries(f.curve);
    return { type: 'scatter', mode: 'lines', x: s.x, y: s.y, name: f.label, showlegend: false,
      line: { width: 1, color: f.kind === 'control' ? 'rgba(255,139,122,0.45)' : 'rgba(179,185,194,0.35)' },
      hovertemplate: `${f.label}: %{y:.2f} at %{x:.0f} µJy<extra></extra>` };
  });
  const s = curveSeries(data.pooled.curve);
  const band = { type: 'scatter', mode: 'lines', x: s.x, line: { width: 0 }, hoverinfo: 'skip', showlegend: false };
  const p = data.pooled.limits;
  return [
    ...fieldLines,
    { ...band, y: s.hi },
    { ...band, y: s.lo, fill: 'tonexty', fillcolor: 'rgba(255,181,71,0.18)' },
    { type: 'scatter', mode: 'lines+markers', x: s.x, y: s.y, name: 'All fields pooled (95% band)', customdata: s.n,
      line: { color: PLOT.accent, width: 2.5 }, marker: { size: 6 },
      hovertemplate: 'Pooled: %{y:.2f} at %{x:.0f} µJy (%{customdata} planted)<extra></extra>' },
    { type: 'scatter', mode: 'markers', x: [p.flux50_ujy, p.flux90_ujy], y: [0.5, 0.9], name: '50% and 90% limits',
      marker: { symbol: 'diamond', size: 10, color: PLOT.ink }, customdata: [p.vmag50, p.vmag90],
      hovertemplate: '%{y:.0%} at %{x} µJy (V %{customdata:.1f})<extra></extra>' },
  ];
}

/** Labels on the curve itself, so the plot reads without a legend. */
function labels(data) {
  const p = data.pooled.limits;
  const s = curveSeries(data.pooled.curve);
  const i = s.y.reduce((best, y, j) => (Math.abs(y - 0.2) < Math.abs(s.y[best] - 0.2) ? j : best), 0);
  const font = { size: 11, color: PLOT.ink };
  const arrow = { showarrow: true, arrowhead: 0, arrowwidth: 1, arrowcolor: PLOT.ink2, font };
  return [
    { ...arrow, x: Math.log10(p.flux50_ujy), y: 0.5, ax: 16, ay: 0, xanchor: 'left', align: 'left', text: `Half found<br>${p.flux50_ujy} µJy, V ${p.vmag50.toFixed(1)}` },
    { ...arrow, x: Math.log10(p.flux90_ujy), y: 0.9, ax: -16, ay: 0, xanchor: 'right', align: 'right', text: `9 in 10 found<br>${p.flux90_ujy} µJy, V ${p.vmag90.toFixed(1)}` },
    { ...arrow, x: Math.log10(s.x[i]), y: s.y[i], ax: -30, ay: -46, xanchor: 'right', text: 'All fields<br>together', font: { size: 11, color: PLOT.accent } },
    { x: 1, xref: 'paper', y: 0.04, yref: 'paper', xanchor: 'right', yanchor: 'bottom', showarrow: false, align: 'right',
      text: 'Thin lines: single fields<br>(red: the two control fields)', font: { size: 11, color: PLOT.ink2 } },
  ];
}

function layout(data) {
  const level = (y, dash) => ({ type: 'line', xref: 'paper', x0: 0, x1: 1, yref: 'y', y0: y, y1: y, line: { color: 'rgba(230,232,235,0.35)', width: 1, dash } });
  return plotLayout({
    x: { title: 'Brightness at 1 µm, in µJy (fainter to the left)', type: 'log', range: [Math.log10(20), Math.log10(400)], tickvals: [20, 30, 50, 70, 100, 200, 300, 400] },
    y: { title: 'Planted objects found again', range: [-0.02, 1.04], tickformat: '.0%' },
    extra: { margin: { l: 58, r: 10, t: 12, b: 48 }, shapes: [level(0.5, 'dash'), level(0.9, 'dot')],
      showlegend: false, annotations: labels(data) },
  });
}

async function renderPlot(data) {
  const card = $('.sr-plot-card');
  const p = data.pooled;
  $('#sr-plot-lead').textContent = `${p.n_injected.toLocaleString('en')} synthetic movers planted in ${data.fields.length} fields (${data.campaign.injections.per_field} per field, ${data.campaign.injections.flux_ujy[0]} to ${data.campaign.injections.flux_ujy[1]} µJy, ${data.campaign.injections.distance_au[0]} to ${data.campaign.injections.distance_au[1]} au); ${p.n_recovered.toLocaleString('en')} recovered.`;
  try {
    const Plotly = await loadPlotly();
    await Plotly.react($('.sr-plot', card), traces(data), layout(data), PLOT_CONFIG);
  } catch {
    $('.sr-plot', card).replaceChildren(el('p', { class: 'muted', text: 'The plotting library could not be loaded; the table below holds the same numbers.' }));
  }
}

function renderFields(data) {
  const head = ['Field', 'Frames, window', 'Trials', ...data.pooled.bins.map((b) => `${b.lo_ujy}–${b.hi_ujy} µJy`), '50% / 90% (µJy)', 'Motion limit'];
  const row = (f) => [f.label, `${f.frames_searched}/${f.frames_in_pass}\n${f.span_days} d`, f.n_trials.toLocaleString('en'),
    ...f.bins.map(binCell), `${f.limits.flux50_ujy ?? '–'} / ${f.limits.flux90_ujy ?? '–'}`,
    `${f.motion_limit_au} au`];
  const p = data.pooled;
  const all = ['All fields', '', '', ...p.bins.map(binCell), `${p.limits.flux50_ujy} / ${p.limits.flux90_ujy}`, ''];
  $('#sr-fields').replaceChildren(table(head, [...data.fields.map(row), all]));
}

function renderKnown(data) {
  const px = data.campaign.pixscale_arcsec;
  const rows = data.known_bodies.map((k) => [k.name, `V ${k.v}`, `${k.delta_au} au`, String(k.snr), `${k.rank} of all peaks`,
    k.offset_px === 0 ? `same pixel (within about 1 px, ${Math.round(px)}″)` : `${k.offset_px} px (${k.offset_arcsec}″)`]);
  $('#sr-known').replaceChildren(table(['Body', 'Brightness', 'Distance', 'S/N', 'Rank in its field', 'Offset from catalogue position'], rows));
}

function renderNull(data) {
  const t = peakTotals(data.fields, ['tno', 'blank']);
  const thr = data.campaign.threshold_snr;
  $('#sr-null-lead').textContent = `After excluding known dwarf planets, we counted ${t.real} peaks at or above a signal-to-noise ratio (S/N) of ${thr} in the ${t.fields} non-control fields. Reversing the paths, our null search, gave ${t.null} peaks. Noise can account for counts this similar. We did not follow up individual peaks in this test.`;
  const rows = data.fields.map((f) => [f.label, String(f.peaks.real_ge5), String(f.peaks.null_ge5),
    peakText(f.peaks.real_ge7, f.peaks.real_max), peakText(f.peaks.null_ge7, f.peaks.null_max)]);
  $('#sr-null').replaceChildren(table(['Field', 'Real, S/N ≥ 5', 'Null, S/N ≥ 5', `Real, S/N ≥ ${thr}`, `Null, S/N ≥ ${thr}`], rows));
}

function renderPlanetX(data, planetx) {
  const host = $('#sr-px');
  const p = data.pooled.limits;
  const mot = range(data.fields, (f) => f.motion_limit_au);
  const parts = [el('p', { text: `The pooled 50% limit, ${p.flux50_ujy} µJy, is AB ${p.ab1um50.toFixed(1)} at 1 µm (V ${p.vmag50.toFixed(1)}). That is ${(21.5 - p.vmag50).toFixed(1)} magnitudes shallower than the Pan-STARRS, ZTF and DES searches, which have already covered most of the favoured Planet Nine orbits to V 21.5.` })];
  if (!planetx) {
    parts.push(el('p', { text: 'The Planet X brightness table could not be loaded, so the limit is not mapped to a distance here.' }));
  } else {
    const rows = brightnessReach(planetx, p.ab1um50);
    parts.push(el('p', { text: 'Using the same brightness curves as the Planet X page (SPHEREx D1, 0.75 to 1.1 µm, which contains 1 µm), a body at this limit would be seen out to:' }));
    parts.push(el('div', { class: 'table-wrap sr-table' }, [table(['Planet', 'Brightness-only distance (dark to bright)'], rows.map((r) => [r.label, reachText(r)]))]));
  }
  const nep = planetx && brightnessReach(planetx, p.ab1um50).find((r) => r.key === 'neptune');
  const bound = nep && typeof nep.nom === 'number' ? data.fields.filter((f) => f.motion_limit_au < nep.nom) : [];
  const where = bound.length
    ? ` In ${bound.map((f) => `${f.label} (${f.motion_limit_au} au)`).join(' and ')} that is nearer than the Neptune analogue's ${nep.nom} au, so there motion sets the reach; in the other fields brightness does.`
    : '';
  const area = (data.campaign.n_fields * (data.campaign.field_arcmin / 60) ** 2).toFixed(1);
  parts.push(el('p', { text: `Brightness is not the only limit. A body must also move at least ${data.campaign.min_motion_px} px within the searched window, and in these fields that holds only out to ${mot[0]} to ${mot[1]} au (the search stops at 1000 au).${where} These distances are for 50% recovery in one pass of one field; the ${data.campaign.n_fields} fields together cover about ${area} square degrees, not the sky.` }));
  parts.push(el('p', {}, ['For the wider picture of how far each survey reaches, see ', el('a', { href: 'planetx.html', text: 'Could SPHEREx see Planet X?' })]));
  host.replaceChildren(...parts);
}

function renderLimits(data) {
  const ctrl = data.fields.filter((f) => f.kind === 'control');
  const t = peakTotals(data.fields, ['tno', 'blank']);
  const thr = data.campaign.threshold_snr;
  const desc = ctrl.map((f) => `${f.label} gave ${f.peaks.real_ge7} real-sky peaks at S/N ${thr} or above against ${f.peaks.null_ge7} in its mirrored null, and was 50% complete only at ${f.limits.flux50_ujy} µJy`).join('; ');
  $('#sr-controls').textContent = `The two fields centred on fast-moving nearby objects, a star and a brown dwarf, were meant to be clean artefact controls: each moves under 1 px in a pass, so it cannot be a candidate, and none of the peaks lies within 5 px of either. Instead ${desc}. The other ten fields gave ${t.real} and ${t.null} in total. Follow-up runs traced the excess to subtraction residuals of catalogued stars just outside the source mask: the residual is present in every frame, so it stacks along the slowest paths and shows up equally in the mirrored search. Why star wings read brighter in the searched pass than in the reference images is not established, and no fix tested removed it without losing real movers. These fields do not show "no candidates"; they show that the S/N ${thr} cut alone is not enough there.`;
  const c = data.classifier;
  const all = c.variants.all_features;
  const nos = c.variants.without_snr;
  $('#sr-classifier').textContent = `A logistic-regression score was trained on ${c.n_train.toLocaleString('en')} peaks from ${c.train_fields.length} fields and tested on ${c.test_fields.length} held-out fields (${c.n_test_positives} recovered synthetic movers, ${c.n_test_negatives.toLocaleString('en')} real-sky and null peaks). To pass, it had to keep at least ${Math.round(c.min_gain * 100)} percentage points more of the held-out movers than the plain S/N ${thr} cut at the same false-positive rate (${c.fp_per_test_field} per field), and keep every real dwarf planet. The S/N cut kept ${pct(c.recall_snr_cut)}; the model with all features kept ${pct(all.recall)}, and the model without S/N kept ${pct(nos.recall)}${nos.tnos_kept ? '' : ' and scored one of the held-out dwarf planets below its threshold'}. We kept the signal-to-noise threshold for ranking peaks.`;
  const skip = /control fields|vetting classifier/;
  $('#sr-caveats').replaceChildren(...data.caveats.filter((s) => !skip.test(s)).map((s) => el('li', { text: s })));
  $('#sr-date').textContent = data.campaign.date;
}

async function main() {
  let data;
  try {
    data = await getJson(DATA_URL);
  } catch (err) {
    $('#sr-answer').after(el('p', { class: 'banner', role: 'alert', text: `The campaign summary could not be loaded (${err.message}).` }));
    return;
  }
  const [planetx, p9] = await Promise.all([getJson(PLANETX_URL).catch(() => null), getJson(P9_URL).catch(() => null)]);
  $('#sr-answer').textContent = searchLead(data, p9);
  renderStats(data);
  renderFields(data);
  renderKnown(data);
  renderNull(data);
  renderPlanetX(data, planetx);
  renderLimits(data);
  await renderPlot(data);
}

mountChrome('search');
openLinkedSection();
renderP9($('#sr-p9'));
document.title = pageTitle('Can we find a dwarf planet without its coordinates?');
main();
