// "Brightness over time" for the two variable stars. One call places it in a view:
//   variabilityBlock(slug, baseUrl)  -> a <section> for r-draconis or rw-aurigae, else null.
// It fetches data/variability.json itself, so the caller only decides where the block goes.

import { el } from './dom.js';
import { loadPlotly, plotLayout, PLOT, PLOT_CONFIG } from './plottheme.js';
import {
  VARIABLE_SLUGS, variabilityProblem, summarySentences, limitSentence, seriesTraces, findingsList,
  axisText, AVERAGE_LABEL, CYCLE_TICKS, keyItems, markNote, shortFinding, plainLimit, yView, clippedNote,
} from './variabilitytext.js';

let dataPromise = null;

/** data/variability.json, fetched once; resolves to null when missing or malformed. */
export function loadVariability(baseUrl = document.baseURI) {
  dataPromise ||= fetch(new URL('data/variability.json', baseUrl), { headers: { Accept: 'application/json' } })
    .then((r) => (r.ok ? r.json() : null))
    .then((d) => (variabilityProblem(d) ? null : d))
    .catch(() => null);
  return dataPromise;
}

const CONFIG = { ...PLOT_CONFIG, displayModeBar: false };

function layout(folded, narrow, period, top) {
  const t = axisText(folded, period);
  return plotLayout({
    x: folded ? { title: t.x, range: [0, 2], ...CYCLE_TICKS } : { title: t.x, type: 'date', tickformat: t.tickformat, nticks: narrow ? 4 : 8 },
    y: { title: t.y, range: [0, top] },
    extra: {
      margin: { l: 56, r: 8, t: 8, b: folded ? 44 : 30 }, showlegend: false,
      shapes: [{ type: 'line', xref: 'paper', x0: 0, x1: 1, yref: 'y', y0: 1, y1: 1, layer: 'below', line: { color: PLOT.ink2, width: 1, dash: 'dash' } }],
        annotations: [{ xref: 'paper', x: 0.01, xanchor: 'left', yref: 'y', y: 1, yanchor: 'bottom', showarrow: false, text: AVERAGE_LABEL,
        bgcolor: 'rgba(23,25,29,0.85)', font: { size: 11, color: PLOT.ink2, family: PLOT.mono } }],
    },
  });
}

function key(items) {
  // Inline styles: the key is this module's own, so styles.css stays untouched.
  const sw = (k) => `display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px;vertical-align:middle;${k.hollow ? `border:1.5px solid ${k.colour}` : `background:${k.colour}`}`;
  return el('ul', { class: 'var-key small', 'aria-label': 'Key', style: 'list-style:none;padding:0;margin:8px 0 0;display:flex;flex-wrap:wrap;gap:4px 16px' },
    items.map((k) => el('li', {}, [el('span', { 'aria-hidden': 'true', style: sw(k) }), k.label])));
}

function fill(section, slug, d) {
  const s = d.stars[slug];
  const plot = el('div', { class: 'var-plot', role: 'img', 'aria-label': `${s.name}: brightness compared with its average, over time, with a comparison star` });
  const canFold = seriesTraces(slug, d, { folded: true }).length > 0;
  let folded = false;
  const buttons = canFold ? [['Over time', false], [`Through its ${Math.round(s.catalogue.period_days)}-day cycle`, true]].map(([text, f]) =>
    el('button', { type: 'button', class: 'seg', 'aria-pressed': String(f === folded), text,
      onClick: () => { folded = f; buttons.forEach((b, i) => b.setAttribute('aria-pressed', String(i === (f ? 1 : 0)))); draw(); } })) : [];
  const status = el('p', { class: 'small muted', 'aria-live': 'polite' });
  const clipNote = el('span');
  section.append(...[
    el('p', { class: 'var-lead', style: 'font-size:var(--fs-md);max-width:60ch;margin-bottom:4px', text: shortFinding(slug, d) }),
    el('p', { class: 'small muted', text: plainLimit(slug) }),
    canFold ? el('div', { class: 'segmented', role: 'group', 'aria-label': 'How to show the points' }, buttons) : null,
    key(keyItems(slug, d)),
    plot, status,
    el('p', { class: 'small muted' }, [markNote(slug, d), ' ', clipNote]),
    el('p', { class: 'var-summary', style: 'font-size:inherit', text: summarySentences(slug, d).join(' ') }),
    el('p', { class: 'small muted var-limit', text: `${limitSentence(slug)} ` }, [
      el('a', { href: 'validation.html#var-h', text: 'How we checked this' }),
    ]),
  ].filter(Boolean));
  let lastNarrow = null;
  async function draw() {
    try {
      const Plotly = await loadPlotly();
      lastNarrow = plot.clientWidth < 500;
      const traces = seriesTraces(slug, d, { folded });
      const { top, clipped } = yView(traces);
      clipNote.textContent = clippedNote(clipped);
      await Plotly.react(plot, traces, layout(folded, lastNarrow, s.catalogue?.period_days, top), CONFIG);
      status.textContent = '';
    } catch {
      status.textContent = 'The plotting library could not be loaded.';
    }
  }
  // Redraw when the plot crosses the phone width, so tick density follows the screen.
  if (typeof ResizeObserver === 'function') new ResizeObserver(() => { if (lastNarrow !== null && (plot.clientWidth < 500) !== lastNarrow) draw(); }).observe(plot);
  draw();
}

/**
 * The block for a variable star's view, or null for any other target.
 * @param {string|null|undefined} slug gallery target slug
 * @param {string} [baseUrl]
 * @returns {HTMLElement|null}
 */
export function variabilityBlock(slug, baseUrl = document.baseURI) {
  if (!VARIABLE_SLUGS.has(slug)) return null;
  const section = el('section', { class: 'card variability', id: 'variability', 'aria-labelledby': 'var-block-h' }, [
    el('h2', { id: 'var-block-h', text: 'Brightness over time' }),
  ]);
  loadVariability(baseUrl).then((d) => {
    if (d) fill(section, slug, d);
    else section.append(el('p', { class: 'small muted', text: 'The brightness measurements (data/variability.json) could not be loaded.' }));
  });
  return section;
}

/** The results page's "Variable stars" section, or a short notice when the data is missing. */
export function variableStarsSection(d) {
  const body = d ? el('ul', {}, findingsList(d).map(([k, v]) => el('li', {}, [el('strong', { text: `${k}. ` }), v])))
    : el('p', { class: 'small muted', text: 'The variability results (data/variability.json) could not be loaded.' });
  return el('section', { class: 'card', id: 'variables', 'aria-labelledby': 'var-h' }, [
    el('h2', { id: 'var-h', text: 'Variable stars' }),
    el('p', { class: 'small muted', text: 'The brief names R Draconis and RW Aurigae as variable stars. Both saturate SPHEREx at their centres, so we measure the ring of light 9 to 13 pixels out, and divide each exposure by the star\'s own average at the same wavelength. The numbers are relative, never calibrated fluxes. Made by probes/variables/export_web.py; the checks are in probes/variables/verify.py.' }),
    body,
  ]);
}
