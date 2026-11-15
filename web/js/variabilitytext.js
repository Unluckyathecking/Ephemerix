// Words, dates and plot traces for the "Brightness over time" block of the two variable stars
// (data/variability.json, written by probes/variables/export_web.py). Pure: no DOM, no fetch.

import { PLOT } from './plottheme.js';

export const VARIABLE_SLUGS = new Set(['r-draconis', 'rw-aurigae']);

const COLOUR = { 1: PLOT.wise, 5: PLOT.gaia, 6: PLOT.accent };
const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
const MJD_UNIX_DAY = 40587; // MJD of 1970-01-01

/** Phase in the cycle, 0 at the catalogue maximum, in [0, 1). */
export function foldPhase(mjd, period, t0) {
  const p = ((mjd - t0) / period) % 1;
  return p < 0 ? p + 1 : p;
}

/** @param {number} mjd @returns {string} YYYY-MM-DD (UTC) */
export function mjdToIso(mjd) {
  return new Date((mjd - MJD_UNIX_DAY) * 86400000).toISOString().slice(0, 10);
}

/** "2025-09-11" -> "September 2025" */
export function monthYear(iso) {
  const [y, m] = iso.split('-');
  return `${MONTHS[Number(m) - 1]} ${y}`;
}

const dashes = (s) => s.replace(/(\d)-(\d)/g, '$1 to $2'); // "0.75-1.1 µm" -> "0.75 to 1.1 µm"
const oneDp = (x) => (Math.round(x * 10) / 10).toFixed(1);

/** null when the data can drive the block, else what is wrong with it. */
export function variabilityProblem(d) {
  if (!d || typeof d !== 'object' || !d.stars) return 'The variability data has no stars.';
  const r = d.stars['r-draconis'], w = d.stars['rw-aurigae'];
  if (!r || !Array.isArray(r.bands) || r.bands.length < 1 || !r.bands.every((b) => b.fit && Array.isArray(b.points))) return 'R Draconis has no fitted bands.';
  if (!r.catalogue?.period_days || !r.brightest_pass || !r.faintest_pass || !r.control?.bands) return 'R Draconis is missing its period, passes or control.';
  if (!w || !Array.isArray(w.bands) || !w.control?.bands) return 'RW Aurigae has no bands.';
  return null;
}

function rwFade(w) {
  const pick = (bands) => bands.filter((b) => (w.headline_dets || []).includes(b.det));
  const star = pick(w.bands);
  const ratios = star.map((b) => b.passes[0].rel / b.passes[b.passes.length - 1].rel);
  const ctrlDev = Math.max(...pick(w.control.bands).flatMap((b) => b.passes.map((p) => Math.abs(p.rel - 1))));
  return {
    factor: ratios.reduce((a, b) => a + b, 0) / ratios.length,
    first: star[0].passes[0].date, last: star[0].passes[star[0].passes.length - 1].date,
    ctrlPct: Math.ceil((ctrlDev * 100) / 5) * 5,
    ctrlErr: Math.max(...pick(w.control.bands).flatMap((b) => b.passes.map((p) => p.err))),
  };
}

/** One or two plain sentences saying what is seen. [] when there is nothing for this slug. */
export function summarySentences(slug, d) {
  if (!d || variabilityProblem(d)) return [];
  if (slug === 'r-draconis') {
    const r = d.stars[slug];
    const [blue, red] = r.bands;
    return [
      `Over its ${Math.round(r.catalogue.period_days)}-day cycle R Draconis brightens and fades by about ${oneDp(blue.fit.mag_pk)} magnitudes (a factor of about ${Math.round(blue.fit.ratio_pk)}) at ${dashes(blue.label)} and about ${oneDp(red.fit.mag_pk)} magnitudes at ${dashes(red.label)}.`,
      `SPHEREx caught it bright in ${monthYear(r.brightest_pass.date)} and faint in ${monthYear(r.faintest_pass.date)}; a star of similar brightness measured the same way shows no such cycle.`,
    ];
  }
  if (slug === 'rw-aurigae') {
    const f = rwFade(d.stars[slug]);
    return [
      `At 3.8 to 5.0 µm RW Aurigae faded by a factor of about ${oneDp(f.factor)} between ${monthYear(f.first)} and ${monthYear(f.last)}, while a nearby star measured the same way showed no clear change within its larger scatter.`,
      'At shorter wavelengths we cannot tell: its changes there are no larger than the comparison star\'s.',
    ];
  }
  return [];
}

/** The limits, said in the same breath as the result. */
export function limitSentence(slug) {
  if (slug === 'r-draconis') {
    return 'These are relative brightnesses only. The centre of the star saturates every SPHEREx detector, so we measure the unsaturated ring around it and compare each exposure with the star\'s own average at the same wavelength. At 0.75 to 1.1 µm the size of the swing depends strongly on wavelength, so single exposures scatter well beyond the fitted curve.';
  }
  if (slug === 'rw-aurigae') {
    return 'Relative brightness only, from the unsaturated ring around the saturated centre. SPHEREx saw it on three visits about six months apart, so we cannot say what it did in between.';
  }
  return '';
}

const quantile = (sorted, q) => {
  const i = (sorted.length - 1) * q, lo = Math.floor(i), hi = Math.ceil(i);
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (i - lo);
};

/**
 * Exposures grouped into short runs (a new run after a gap of more than `gap` days, or once a run
 * spans `span` days), each summarised by its median and the 16th to 84th percentile spread.
 * Rows are [mjd, rel, err, pass, flag]; missing and flagged rows are left out. Pure.
 * @returns {{mjd: number, med: number, lo: number, hi: number, n: number}[]}
 */
export function binMedians(rows, { gap = 5, span = 15, minN = 3 } = {}) {
  const keep = rows.filter((r) => r[1] != null && Number.isFinite(r[1]) && !r[4]).sort((p, q) => p[0] - q[0]);
  const runs = [];
  for (const r of keep) {
    const cur = runs[runs.length - 1];
    if (cur && r[0] - cur[cur.length - 1][0] <= gap && r[0] - cur[0][0] <= span) cur.push(r);
    else runs.push([r]);
  }
  return runs.filter((g) => g.length >= minN).map((g) => {
    const y = g.map((r) => r[1]).sort((p, q) => p - q);
    return { mjd: g.reduce((t, r) => t + r[0], 0) / g.length, med: quantile(y, 0.5), lo: quantile(y, 0.16), hi: quantile(y, 0.84), n: g.length };
  });
}

export const AVERAGE_LABEL = '1 = average';

/** Axis words: plain, with readable dates, or the position in the cycle when folded. */
export function axisText(folded, period = 246.12) {
  return folded
    ? { x: `Position in its ${Math.round(period)}-day cycle`, y: 'Brightness compared with its average' }
    : { x: '', y: 'Brightness compared with its average', tickformat: '%b %Y' };
}

/** Tick labels for the folded view: the catalogue peak and the halfway point, over two cycles. */
export const CYCLE_TICKS = { tickvals: [0, 0.5, 1, 1.5, 2], ticktext: ['peak', 'halfway', 'peak', 'halfway', 'peak'] };

const BIN = { 'r-draconis': { gap: 5, span: 15, minN: 3 }, 'rw-aurigae': { gap: 20, span: 60, minN: 3 } };
const rowsOf = (slug, b) => (slug === 'rw-aurigae' ? b.points.map((p) => [p[0], p[1], 0, p[2], '']) : b.points);

function singleTrace(name, rows, { colour, folded }) {
  const keep = rows.filter((p) => p[1] != null && !p[4]);
  let x = keep.map((p) => (folded ? foldPhase(p[0], folded.period, folded.t0) : mjdToIso(p[0])));
  let y = keep.map((p) => p[1]);
  if (folded) { x = [...x, ...x.map((v) => v + 1)]; y = [...y, ...y]; }
  return { type: 'scatter', mode: 'markers', name: `${name}, single exposures`, x, y, showlegend: false, hoverinfo: 'skip',
    marker: { size: 4, color: colour, opacity: 0.22 } };
}

function medianTrace(name, bins, { colour, hollow = false, folded }) {
  let x = bins.map((m) => (folded ? foldPhase(m.mjd, folded.period, folded.t0) : mjdToIso(m.mjd)));
  let k = bins;
  if (folded) { x = [...x, ...x.map((v) => v + 1)]; k = [...bins, ...bins]; }
  return {
    type: 'scatter', mode: 'markers', name, x, y: k.map((m) => m.med),
    customdata: k.map((m) => [m.n, mjdToIso(m.mjd)]),
    error_y: { type: 'data', symmetric: false, array: k.map((m) => m.hi - m.med), arrayminus: k.map((m) => m.med - m.lo),
      thickness: 1.2, width: 0, color: hollow ? 'rgba(141,140,134,0.55)' : colour },
    marker: hollow ? { size: 7, color: 'rgba(0,0,0,0)', line: { color: PLOT.muted, width: 1.5 } }
      : { size: 9, color: colour, line: { color: '#0c0d10', width: 1 } },
    hovertemplate: `%{customdata[1]}<br>%{y:.2f} × its average<br>median of %{customdata[0]} exposures<extra>${name}</extra>`,
  };
}

function curveTrace(band, period) {
  const xs = Array.from({ length: 121 }, (_, i) => (2 * i) / 120);
  const { mean, semi_amp: a, phase_of_max: m } = band.fit;
  return { type: 'scatter', mode: 'lines', name: `Fit at ${Math.round(period)} days, ${band.label}`, hoverinfo: 'skip', showlegend: false,
    x: xs, y: xs.map((p) => mean + a * Math.cos(2 * Math.PI * (p - m))), line: { color: COLOUR[band.det], width: 1.5, dash: 'dot' } };
}

function shownBands(slug, s) {
  const dets = slug === 'rw-aurigae' ? s.headline_dets || [] : s.bands.map((b) => b.det);
  return { star: s.bands.filter((b) => dets.includes(b.det)), ctrl: s.control.bands.filter((b) => dets.includes(b.det)) };
}

/**
 * Plotly traces. Main marks are medians of short runs of exposures with their spread; single
 * exposures are drawn faint behind them and left out of the key. R Draconis can also be folded on
 * the catalogue period over two cycles, with the fitted cycle drawn. RW Aurigae has no period.
 */
export function seriesTraces(slug, d, { folded }) {
  const s = d?.stars?.[slug];
  if (!s || (folded && slug === 'rw-aurigae')) return [];
  const fold = folded ? { period: s.catalogue.period_days, t0: s.catalogue.t0_max_mjd } : null;
  const { star, ctrl } = shownBands(slug, s);
  const opt = BIN[slug];
  return [
    ...ctrl.map((b) => singleTrace(`Comparison star, ${b.label}`, rowsOf(slug, b), { colour: PLOT.muted, folded: fold })),
    ...star.map((b) => singleTrace(`${s.name}, ${b.label}`, rowsOf(slug, b), { colour: COLOUR[b.det], folded: fold })),
    ...(folded ? star.map((b) => curveTrace(b, s.catalogue.period_days)) : []),
    ...ctrl.map((b) => medianTrace(`Comparison star, ${b.label}`, binMedians(rowsOf(slug, b), opt), { hollow: true, folded: fold })),
    ...star.map((b) => medianTrace(`${s.name}, ${b.label}`, binMedians(rowsOf(slug, b), opt), { colour: COLOUR[b.det], folded: fold })),
  ];
}

/**
 * The top of the y axis: room for every median with its bar and the fitted cycle, in steps of 0.5;
 * and how many single exposures lie above it (the caller says so in words).
 */
export function yView(traces) {
  const tops = traces.filter((t) => !/single exposures/.test(t.name))
    .flatMap((t) => t.y.map((y, i) => y + (t.error_y?.array?.[i] ?? 0)));
  const top = Math.max(1.5, Math.ceil((Math.max(...tops) * 1.08) / 0.5) * 0.5);
  const clipped = traces.filter((t) => /single exposures/.test(t.name)).flatMap((t) => t.y).filter((y) => y > top).length;
  return { top, clipped };
}

export function clippedNote(n) {
  if (!n) return '';
  return n === 1 ? '1 single exposure lies above the top of the chart.' : `${n} single exposures lie above the top of the chart.`;
}

/** The key drawn above the chart (in place of Plotly's legend, which is cramped on a phone). */
export function keyItems(slug, d) {
  const s = d?.stars?.[slug];
  if (!s) return [];
  const { star } = shownBands(slug, s);
  return [
    ...star.map((b) => ({ label: `${s.name}, ${dashes(b.label)}`, colour: COLOUR[b.det], hollow: false })),
    { label: 'Comparison star, measured the same way', colour: PLOT.muted, hollow: true },
  ];
}

/** What one mark stands for, from the data. */
export function markNote(slug, d) {
  const s = d?.stars?.[slug];
  if (!s) return '';
  const { star, ctrl } = shownBands(slug, s);
  const ns = [...star, ...ctrl].flatMap((b) => binMedians(rowsOf(slug, b), BIN[slug]).map((m) => m.n));
  const run = slug === 'rw-aurigae' ? 'from one visit' : 'taken within about two weeks';
  return `Each mark is the median of ${Math.min(...ns)} to ${Math.max(...ns)} exposures ${run}; its bar covers the middle two thirds of them. Faint dots are single exposures.`;
}

/** About 20 plain words per star, for the simple view's answer card and the results table. */
export function shortFinding(slug, d) {
  if (!d || variabilityProblem(d)) return '';
  if (slug === 'r-draconis') {
    const r = d.stars[slug];
    const f = Math.round(r.bands[0].fit.ratio_pk);
    const words = ['', 'one', 'two', 'three', 'four', 'five'][f] || String(f);
    return `R Draconis brightens and fades every ${Math.round(r.catalogue.period_days)} days; SPHEREx saw its infrared light change about ${words}fold between bright and faint.`;
  }
  if (slug === 'rw-aurigae') {
    const f = rwFade(d.stars[slug]);
    return `RW Aurigae dimmed to about ${Math.round(100 / f.factor / 5) * 5}% of its earlier infrared brightness between ${monthYear(f.first)} and ${monthYear(f.last)}.`;
  }
  return '';
}

/** The limit in one short plain sentence, said straight after the finding. */
export function plainLimit(slug) {
  if (!VARIABLE_SLUGS.has(slug)) return '';
  return 'The star is too bright for the centre of the camera image (it saturates), so we measure the light around it and can only compare it with itself.';
}

const pct = (x) => `${Math.round(x * 100)}%`;

/** [label, text] pairs for the results page: what held, what failed, and choices made after seeing data. */
export function findingsList(d) {
  const r = d.stars['r-draconis'], w = d.stars['rw-aurigae'];
  const [blue, red] = r.bands;
  const ctrl = Math.max(...r.control.bands.map((c) => c.semi_amp / r.bands.find((b) => b.det === c.det).fit.semi_amp),
    ...r.bands.map((b) => (r.control.second?.semi_amp?.[b.det] ?? 0) / b.fit.semi_amp));
  const ps = r.period_search;
  const f = rwFade(w);
  const rwPass = (b) => `${b.label}: ${b.passes.map((p) => `${p.rel.toFixed(2)} ± ${p.err.toFixed(2)}`).join(', ')}`;
  return [
    ['R Draconis, what held', `At ${blue.label} and ${red.label} the brightness of the unsaturated ring follows the catalogue cycle across ${r.n_exposures} exposures from ${monthYear(r.span[0])} to ${monthYear(r.span[1])}: peak to peak ${blue.fit.mag_pk.toFixed(2)} mag (${blue.fit.mag_pk_68[0].toFixed(2)} to ${blue.fit.mag_pk_68[1].toFixed(2)}, 68% over resampled passes) and ${red.fit.mag_pk.toFixed(2)} mag (${red.fit.mag_pk_68[0].toFixed(2)} to ${red.fit.mag_pk_68[1].toFixed(2)}), with maximum ${blue.fit.phase_of_max.toFixed(2)} and ${red.fit.phase_of_max.toFixed(2)} cycles after the catalogue date. Two stars of similar brightness measured the same way swing at most ${pct(ctrl)} as much. Leaving out any one pass changes the amplitude by at most ${pct(Math.max(blue.drop_one_pass.max_amp_change, red.drop_one_pass.max_amp_change))} and moves the maximum by at most ${Math.max(blue.drop_one_pass.max_phase_shift, red.drop_one_pass.max_phase_shift).toFixed(2)} cycles.`],
    ['R Draconis, period', `Our own data alone give a best period of ${ps.best_days} days, but resampling whole passes moves it between ${ps.range_68[0]} and ${ps.range_68[1]} days (68%). We do not measure the period independently; we fold on the catalogue's ${r.catalogue.period_days} days (AAVSO VSX).`],
    ['R Draconis, NEOWISE', `NEOWISE per-visit medians from ${r.neowise.years} (${r.neowise.visits} visits) follow the same catalogue cycle, semi-amplitude ${r.neowise.semi_amp_mag.W1} mag in W1 and ${r.neowise.semi_amp_mag.W2} mag in W2. WISE also saturates on R Draconis, so this is a consistency check, not a calibration.`],
    ...r.failed.map((x) => [`R Draconis, not shown: ${x.band}`, `${x.why[0].toUpperCase()}${x.why.slice(1)}.`]),
    ['RW Aurigae', `Per visit, relative to its own average (${w.bands.find((b) => b.det === 5).passes.map((p) => monthYear(p.date)).join(', ')}): ${w.bands.filter((b) => (w.headline_dets || []).includes(b.det)).map(rwPass).join('; ')}. A factor of about ${oneDp(f.factor)} from first to last visit. The comparison star, ${w.control.name}, shows no clear change in the same bands (visit medians within ${f.ctrlPct}% of its average, uncertainties up to ${f.ctrlErr.toFixed(2)}); it is fainter than RW Aurigae there, so its points scatter more.`],
    ['RW Aurigae, not shown', `At 0.75-3.8 µm the changes between visits (up to ${pct(Math.max(...w.bands.filter((b) => b.det <= 4).flatMap((b) => b.passes.map((p) => Math.abs(p.rel - 1)))))}) are no larger than the comparison star's, so we cannot tell. In the 14 November draft only ${w.core_unsaturated.n} of ${w.core_unsaturated.of} exposures had an unsaturated centre, too few for a light curve; the ring method was applied afterwards.`],
    ['Choices made after seeing results', `We wrote down ${r.checks.written_before_looking} ways the R Draconis analysis could fail before re-running it, and publish only the bands that passed; the 14 November draft also quoted 1.65-2.4 and 2.4-3.8 µm. One written test, that the ring must not follow the local background more closely than it follows time, failed at 4.4-5.0 µm. We kept that band after seeing that the background ring is itself about half starlight: measured alone it shows the same cycle at the same phase for R Draconis and is flat for both comparison stars, and zodiacal light does not follow the cycle. Bright and faint dates are quoted only for passes with ${r.min_pass_exposures_for_dates} or more exposures, decided after seeing that the brightest pass otherwise had ${Math.min(...r.passes.filter((p) => p.rel >= r.brightest_pass.rel).map((p) => p.n))}. For RW Aurigae no failure criteria were written before we looked, and its bright comparison star was chosen after the faint ones, and measured in RW Aurigae\'s own frames because the archive's frame search was down.`],
  ];
}
