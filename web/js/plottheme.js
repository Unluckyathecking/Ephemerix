// One look for every Plotly plot on the site: the page's own type and colours, quiet grid,
// no chart chrome that does not earn its place. Also loads the vendored Plotly build once.

import { el } from './dom.js';

// Self-hosted, pinned build (see vendor/README.md), resolved relative to this module.
const PLOTLY_URL = new URL('../vendor/plotly-basic-2.35.2.min.js', import.meta.url).href;
let plotlyPromise = null;

/** Load Plotly on first use; rejects (and allows a retry) if the script cannot be loaded. */
export function loadPlotly() {
  if (window.Plotly) return Promise.resolve(window.Plotly);
  plotlyPromise ||= new Promise((resolve, reject) => {
    const s = el('script', { src: PLOTLY_URL, async: true });
    s.onload = () => (window.Plotly ? resolve(window.Plotly) : reject(new Error('Plotly missing')));
    s.onerror = () => { plotlyPromise = null; reject(new Error('Plotly failed to load')); };
    document.head.append(s);
  });
  return plotlyPromise;
}

/** The palette, matching the tokens in styles.css (Plotly cannot read CSS variables). */
export const PLOT = {
  ink: '#edebe5', ink2: '#bcbab3', muted: '#8d8c86', grid: 'rgba(237,235,229,0.06)', axis: '#383c43',
  accent: '#ffb547', wise: '#56d8ec', gaia: '#c8a2ff', good: '#86d993', bad: '#ff8b7a',
  sans: '"IBM Plex Sans", ui-sans-serif, system-ui, sans-serif',
  mono: '"IBM Plex Mono", ui-monospace, Menlo, monospace',
};

const axis = (title, extra = {}) => ({
  title: { text: title, font: { size: 12, color: PLOT.ink2 }, standoff: 10 },
  gridcolor: PLOT.grid, zeroline: false, showline: true, linecolor: PLOT.axis, ticks: 'outside', ticklen: 4, tickcolor: PLOT.axis,
  tickfont: { family: PLOT.mono, size: 11, color: PLOT.muted }, ...extra,
});

/**
 * A themed layout. `x` and `y` are {title, ...axis overrides}; anything in `extra` is merged on top.
 * @param {{x: object, y: object, extra?: object}} opts
 */
export function plotLayout({ x, y, extra = {} }) {
  const { title: xt, ...xr } = x, { title: yt, ...yr } = y;
  return {
    paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)',
    font: { color: PLOT.ink2, family: PLOT.sans, size: 12 },
    margin: { l: 58, r: 10, t: 26, b: 44 }, hovermode: 'closest',
    hoverlabel: { bgcolor: '#17191d', bordercolor: PLOT.axis, font: { family: PLOT.sans, size: 12, color: PLOT.ink } },
    legend: { orientation: 'h', y: -0.2, x: 0, font: { size: 11, color: PLOT.ink2 }, bgcolor: 'rgba(0,0,0,0)' },
    xaxis: axis(xt, xr), yaxis: axis(yt, yr),
    ...extra,
  };
}

export const PLOT_CONFIG = { responsive: true, displaylogo: false, displayModeBar: 'hover',
  modeBarButtonsToRemove: ['select2d', 'lasso2d', 'autoScale2d', 'toggleSpikelines'] };
