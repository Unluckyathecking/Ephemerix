// The reach chart on the Planet X page: one row per hypothetical planet, a bar from its dark to
// its bright version, against the band where Planet Nine is predicted. Labels sit on the bars,
// so the chart reads without a legend. Pure: Plotly traces and layout only, no DOM.

import { plotLayout, PLOT } from './plottheme.js';

const BAR = 'rgba(255,181,71,0.85)';
const BAR_ALL = 'rgba(255,181,71,0.4)';
const X_RANGE = [200, 1400];
const BAND_DROP = 0.3; // the 17-channel bar sits this far below its planet's one-channel bar

/** Rows from the top: planet i at y = n - 1 - i. */
const rowY = (n, i) => n - 1 - i;

/** Segments lo..hi as one trace, broken by nulls. */
function segments(bars, dy) {
  const n = bars.length;
  return {
    x: bars.flatMap((b) => [b.lo, b.hi, null]),
    y: bars.flatMap((b, i) => [rowY(n, i) - dy, rowY(n, i) - dy, null]),
  };
}

/**
 * @param {{channel: object[], band: object[]}} bars reachBars() for one map per channel and for 17 channels combined
 */
export function reachTraces({ channel, band }) {
  const n = channel.length;
  const line = (seg, color, width) => ({ type: 'scatter', mode: 'lines', ...seg, line: { color, width }, hoverinfo: 'skip', showlegend: false });
  return [
    line(segments(band, BAND_DROP), BAR_ALL, 3),
    line(segments(channel, 0), BAR, 10),
    { type: 'scatter', mode: 'markers', showlegend: false, x: channel.map((b) => b.nom), y: channel.map((_, i) => rowY(n, i)),
      marker: { size: 12, color: PLOT.ink, line: { color: '#0c0d10', width: 2 } },
      customdata: channel.map((b) => [b.label, b.text]),
      hovertemplate: '%{customdata[0]}: most likely %{customdata[1]}, one SPHEREx map, one channel<extra></extra>' },
    { type: 'scatter', mode: 'text', showlegend: false, hoverinfo: 'skip', cliponaxis: false,
      x: channel.map((b) => b.hi), y: channel.map((_, i) => rowY(n, i)),
      text: channel.map((b, i) => (i === 0 ? `  ${b.text}, one channel` : `  ${b.text}`)),
      textposition: 'middle right', textfont: { family: PLOT.mono, size: 12, color: PLOT.ink } },
    { type: 'scatter', mode: 'text', showlegend: false, hoverinfo: 'skip', cliponaxis: false,
      x: [band[0]?.hi], y: [rowY(n, 0) - BAND_DROP], text: ['  all 17 channels combined'],
      textposition: 'middle right', textfont: { size: 11, color: PLOT.ink2 } },
  ];
}

/**
 * @param {{channel: object[]}} bars
 * @param {number[]} p9 [near, far] au where Planet Nine is predicted
 * @param {boolean} narrow phone width
 */
export function reachLayout({ channel }, p9, narrow) {
  const n = channel.length;
  const names = channel.map((b, i) => ({ x: X_RANGE[0], xref: 'x', xanchor: 'left', y: rowY(n, i) + 0.42, yref: 'y', yanchor: 'middle',
    showarrow: false, text: b.label, font: { size: narrow ? 12 : 13, color: PLOT.ink } }));
  return plotLayout({
    x: { title: narrow ? 'Distance from the Sun (au)' : 'Distance from the Sun in au (1 au is the distance from Earth to the Sun)', range: X_RANGE, dtick: 200, fixedrange: true },
    y: { title: '', range: [-0.6, n - 0.35], showticklabels: false, showgrid: false, showline: false, ticks: '', fixedrange: true },
    extra: {
      margin: { l: 20, r: 12, t: 30, b: 52 }, hovermode: 'closest', showlegend: false,
      shapes: [{ type: 'rect', xref: 'x', yref: 'paper', x0: p9[0], x1: p9[1], y0: 0, y1: 1, fillcolor: 'rgba(255,181,71,0.10)',
        line: { width: 1, color: 'rgba(255,181,71,0.35)', dash: 'dot' }, layer: 'below' }],
      annotations: [...names, { x: (p9[0] + p9[1]) / 2, xref: 'x', y: 1, yref: 'paper', yanchor: 'bottom', showarrow: false,
        text: `Planet Nine predicted here (${p9[0]} to ${p9[1]} au)`, font: { size: narrow ? 11 : 12, color: PLOT.accent } }],
    },
  });
}
