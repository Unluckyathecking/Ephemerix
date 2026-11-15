// Spectrum panel: verdict, how-to-read note, epoch selector, log/linear toggle
// and a Plotly plot (lazy-loaded). Falls back to a table if Plotly can't load.

import { el } from './dom.js';
import { CONFIDENCE_WORDS, notBrownDwarf, neutralClass, classText, pairText, rangeSentence, passSummary, matchDetails, templateCurves } from './matchtext.js';
import { flaggedNote, missingNote, noMatchReason } from './flags.js';
import { isRefusal } from './verdict.js';
import { loadPlotly, plotLayout, PLOT, PLOT_CONFIG } from './plottheme.js';

// Plotly renders labels as pseudo-HTML and expands %{...} in templates; neutralise manifest strings.
const esc = (v) => String(v ?? '').replace(/[&<>%{}]/g, (c) => `&#${c.charCodeAt(0)};`);

function noMatchBlock(m) {
  const reason = noMatchReason(m.warnings);
  const refused = isRefusal(m);
  const fallback = m.spectra.length
    ? 'These measurements are too uncertain for a reliable comparison with brown-dwarf spectra. The plot shows the wavelengths we could measure. Motion is measured separately from the images.'
    : 'SPHEREx gave no usable spectrum at this position. The images can still be used to check for motion.';
  return el('div', { class: `verdict none${refused ? ' refused' : ''}` }, [
    el('p', { class: 'verdict-line', text: m.spectra.length ? 'No reliable spectral type' : 'No usable spectrum' }),
    el('p', {}, [
      el('span', { class: `badge ${refused ? 'conf-medium' : 'neutral'}`, text: refused ? 'Unclassified' : 'No spectrum' }),
      reason ? ' ' : null,
      reason ? el('span', { class: 'verdict-reason', text: reason }) : null,
    ]),
    el('p', { class: 'muted', text: reason && m.spectra.length ? 'The plot shows the wavelengths we could measure. Motion is measured separately from the images.' : fallback }),
  ]);
}

function verdictBlock(m, published) {
  const match = m.match;
  if (!match) return noMatchBlock(m);
  const star = notBrownDwarf(match);
  const neutral = neutralClass(match);
  const tone = neutral ? 'neutral' : `conf-${match.confidence}`;
  const pair = pairText(match);
  const passes = passSummary(match);
  const rows = matchDetails(match);
  return el('div', { class: `verdict ${tone}${match.provisional ? ' provisional' : ''}` }, [
    el('p', { class: 'verdict-line', text: match.verdict }),
    published,
    pair ? el('p', { class: 'verdict-pair', text: pair }) : null,
    passes ? el('p', { class: 'verdict-passes', text: passes }) : null,
    el('p', {}, [
      el('span', { class: `badge ${tone}`, text: `${match.confidence} confidence` }),
      ' ',
      el('span', { class: 'muted', text: [classText(match), star ? 'The closest match is not a brown dwarf.'
        : match.class === 'uncertain' ? null : CONFIDENCE_WORDS[match.confidence]].filter(Boolean).join(' ') }),
    ]),
    // The pipeline's own caution when the type stands but a neighbour may add light.
    match.provisional ? el('p', { class: 'verdict-provisional' }, [el('span', { class: 'badge v-provisional', text: 'Provisional' }), ' ', match.provisional]) : null,
    rangeSentence(match) ? el('p', { class: 'small', text: rangeSentence(match) }) : null,
    rows.length || match.method ? el('details', { class: 'match-details small' }, [
      el('summary', { text: 'Details' }),
      el('dl', { class: 'facts' }, rows.flatMap(([k, v]) => [el('dt', { text: k }), el('dd', { class: 'mono', text: v })])),
      match.method ? el('p', { class: 'muted', text: match.method }) : null,
    ]) : null,
  ]);
}

function howToRead() {
  return el('details', { class: 'howto' }, [
    el('summary', { text: 'How to read this plot' }),
    el('p', { text: 'Each dot is how bright the object is at one wavelength, with a bar for the uncertainty. Grey hollow dots were flagged and are not used in the fit.' }),
    el('p', { text: 'Shaded strips mark molecules. Cold brown dwarfs are dark where methane (CH4) absorbs near 3.3 µm and bright around 4 to 4.5 µm. A normal star looks smooth and falls steadily toward longer wavelengths.' }),
    el('p', { text: 'The lines are the brown-dwarf templates that fit best, scaled to the data.' }),
  ]);
}

function traces(m, spec, showOthers, dimNoisy) {
  const out = [];
  const noisy = (p) => dimNoisy && Number.isFinite(p.err) && p.err > 0 && Math.abs(p.flux) < 3 * p.err;
  const pointTrace = (s, color, name, faint) => {
    // Three kinds of point: used in the fit, measured below 3 sigma (drawn faint, no bars), and flagged.
    for (const kind of ['good', 'noisy', 'flagged']) {
      const pts = s.points.filter((p) => (kind === 'flagged' ? p.flagged : !p.flagged && noisy(p) === (kind === 'noisy')));
      if (!pts.length) continue;
      const flagged = kind === 'flagged', dim = kind === 'noisy';
      out.push({
        type: 'scatter', mode: 'markers', name: esc(flagged ? `${name} (flagged)` : dim ? `${name} (below 3 sigma)` : name),
        x: pts.map((p) => p.wl_um), y: pts.map((p) => p.flux),
        customdata: pts.map((p) => [p.detector ?? '?', p.err ?? 0, p.bw_um ?? 0]),
        error_y: { type: 'data', array: pts.map((p) => p.err ?? 0), visible: !dim, thickness: 1, width: 0,
          color: flagged ? 'rgba(141,140,134,0.3)' : faint ? 'rgba(160,170,190,0.25)' : 'rgba(86,216,236,0.4)' },
        marker: flagged
          ? { size: 6, color: 'rgba(0,0,0,0)', line: { color: PLOT.muted, width: 1 } }
          : { size: faint ? 4 : dim ? 5 : 7, color: faint ? 'rgba(160,170,190,0.55)' : color, opacity: dim ? 0.25 : 1 },
        hovertemplate: `%{x:.3f} µm<br>%{y:.3f} ± %{customdata[1]:.3f} ${esc(s.unit)}<br>detector %{customdata[0]}${flagged ? ' · flagged' : ''}<extra>${esc(s.label)}</extra>`,
      });
    }
  };
  if (showOthers) for (const s of m.spectra) if (s !== spec) pointTrace(s, null, s.label, true);
  pointTrace(spec, PLOT.wise, spec.label, false);
  const match = m.match;
  if (match) {
    const fitTo = m.spectra.find((s) => s.id === match.spectrum_id)?.label;
    const suffix = fitTo && fitTo !== spec.label ? ` (fit to ${fitTo})` : '';
    for (const c of templateCurves(match)) {
      out.push({ type: 'scatter', mode: 'lines', name: esc(`${c.label}${suffix}`),
        x: c.curve.map((p) => p[0]), y: c.curve.map((p) => p[1]), line: { color: c.color, dash: c.dash, width: Math.min(c.width, 2.5) },
        hovertemplate: `${esc(c.key)}: %{y:.3f} at %{x:.2f} µm<extra></extra>` });
    }
  }
  return out;
}

/** A y range that suits this spectrum: from just below zero to just above the brightest point or template. */
export function yRangeFor(m, spec, showOthers) {
  const vals = [];
  const take = (s) => s.points.forEach((p) => { if (!p.flagged && Number.isFinite(p.flux)) vals.push(p.flux); });
  take(spec);
  if (showOthers) m.spectra.forEach(take);
  vals.sort((a, b) => a - b);
  if (!vals.length) return null;
  let hi = vals[Math.floor(vals.length * 0.99)];
  for (const c of templateCurves(m.match)) {
    for (const [, y] of c.curve) if (Number.isFinite(y)) hi = Math.max(hi, y);
  }
  const lo = Math.min(0, vals[Math.floor(vals.length * 0.01)]) * 1.1;
  return hi > 0 ? [lo, hi * 1.12] : null;
}

/**
 * Where each molecule label goes: its strip's centre, on a second row when it would run into
 * the label before it; on a narrow plot every second label is dropped. Pure.
 * @returns {{x: number, text: string, row: 0|1}[]}
 */
export function featureLabels(features, narrow = false) {
  const sorted = features.map((f) => ({ x: (f.wl_um[0] + f.wl_um[1]) / 2, text: f.label })).sort((a, b) => a.x - b.x);
  const kept = narrow ? sorted.filter((_, i) => i % 2 === 0) : sorted;
  const gap = narrow ? 0.5 : 0.24;
  let prev = null;
  return kept.map((f) => {
    const row = prev && f.x - prev.x < gap && prev.row === 0 ? 1 : 0;
    prev = { x: f.x, row };
    return { ...f, row };
  });
}

function layout(m, spec, log, showOthers, yTitle, yRange, narrow) {
  const yr = (yRange || yRangeFor)(m, spec, showOthers);
  const shapes = m.features.map((f) => ({ type: 'rect', xref: 'x', yref: 'paper', x0: f.wl_um[0], x1: f.wl_um[1], y0: 0, y1: 1,
    fillcolor: 'rgba(237, 235, 229, 0.055)', line: { width: 0 }, layer: 'below' }));
  // Points the pipeline had to leave out (no flux): ticks on the baseline, where data is missing.
  for (const g of spec.missing || []) {
    shapes.push({ type: 'line', xref: 'x', yref: 'paper', x0: g.wl_um, x1: g.wl_um, y0: 0, y1: 0.04,
      line: { color: PLOT.ink2, width: 2 }, layer: 'above' });
  }
  const annotations = featureLabels(m.features, narrow).map((f) => ({ x: f.x, y: 1, xref: 'x', yref: 'paper',
    yanchor: 'bottom', yshift: f.row * 13, text: esc(f.text), showarrow: false, font: { size: 11, color: PLOT.ink2, family: PLOT.mono } }));
  return plotLayout({
    x: { title: 'Wavelength (µm)', range: [0.7, 5.05] },
    y: { title: esc(yTitle || `Brightness (${spec.unit})`), type: log ? 'log' : 'linear', ...(log ? {} : { range: yr || undefined, autorange: !yr }) },
    extra: { margin: { l: 58, r: 10, t: 36, b: 44 }, shapes, annotations, legend: { orientation: 'h', y: -0.24, x: 0, font: { size: 11, color: PLOT.ink2 } } },
  });
}

function fallbackTable(spec, reason) {
  return el('div', { class: 'spec-fallback' }, [
    el('p', { class: 'muted', text: `${reason} Showing the numbers instead.` }),
    el('div', { class: 'table-wrap' }, [el('table', {}, [
      el('thead', {}, [el('tr', {}, ['µm', spec.unit, '±', 'detector', 'flagged'].map((h) => el('th', { text: h })))]),
      el('tbody', {}, spec.points.map((p) => el('tr', {}, [p.wl_um.toFixed(3), p.flux.toFixed(4), p.err?.toFixed(4) ?? '', p.detector ?? '', p.flagged ? 'yes' : '']
        .map((c) => el('td', { text: String(c) }))))),
    ])]),
  ]);
}

/**
 * @param {HTMLElement} host
 * @param {object} m validated manifest
 * @param {{spec: string|null, onSpecChange: (id: string) => void, verdict?: Node, howto?: Node,
 *   yTitle?: string, choiceLabel?: string, yRange?: Function, published?: Node, dimNoisy?: boolean}} opts
 *   verdict/howto/yTitle/choiceLabel/yRange replace the brown-dwarf wording (the Solar System body mode
 *   plots reflectance with them); `published` is a line the caller fills with the published type;
 *   `dimNoisy` draws points below 3 sigma faint and without bars, so they do not drown the rest
 */
export function renderSpectrum(host, m, { spec: wanted, onSpecChange, verdict = null, howto = null, yTitle = null, choiceLabel = 'SPHEREx epoch', yRange = null, published = null, dimNoisy = false }) {
  if (!m.spectra.length) { host.replaceChildren(verdict || verdictBlock(m, published)); return; }
  const parts = [verdict || verdictBlock(m, published)];
  let spec = m.spectra.find((s) => s.id === wanted) || m.spectra.find((s) => s.id === m.match?.spectrum_id) || m.spectra[0];
  let log = false, showOthers = false;
  const plot = el('div', { class: 'spec-plot', role: 'img', 'aria-label': 'SPHEREx spectrum plot' });
  const status = el('p', { class: 'small muted', 'aria-live': 'polite' });
  const epochButtons = m.spectra.map((s) => el('button', { type: 'button', class: 'seg', 'aria-pressed': String(s === spec), text: s.label,
    onClick: () => { spec = s; epochButtons.forEach((b, i) => b.setAttribute('aria-pressed', String(m.spectra[i] === s))); onSpecChange(s.id); draw(); } }));
  const logBox = el('input', { type: 'checkbox', id: 'spec-log', onChange: (e) => { log = e.target.checked; draw(); } });
  const othersBox = el('input', { type: 'checkbox', id: 'spec-others', onChange: (e) => { showOthers = e.target.checked; draw(); } });
  const controls = el('div', { class: 'spec-controls' }, [
    el('div', { class: 'segmented', role: 'group', 'aria-label': choiceLabel }, epochButtons),
    el('label', { class: 'check' }, [logBox, ' Log scale']),
    m.spectra.length > 1 ? el('label', { class: 'check' }, [othersBox, ' Show other epochs faintly']) : null,
  ]);
  const flagNote = el('p', { class: 'small muted flag-note' });
  const gapNote = el('p', { class: 'small muted gap-note' });
  host.replaceChildren(...parts, controls, plot, flagNote, gapNote, status, howto || howToRead());

  async function draw() {
    status.textContent = log ? 'Log scale hides points at or below zero.' : '';
    flagNote.textContent = flaggedNote(spec, m.warnings) || '';
    gapNote.textContent = missingNote(spec, m.warnings) || '';
    try {
      const Plotly = await loadPlotly();
      await Plotly.react(plot, traces(m, spec, showOthers, dimNoisy), layout(m, spec, log, showOthers, yTitle, yRange, plot.clientWidth < 500), PLOT_CONFIG);
    } catch {
      plot.replaceChildren(fallbackTable(spec, 'The plotting library could not be loaded.'));
    }
  }
  draw();
}
