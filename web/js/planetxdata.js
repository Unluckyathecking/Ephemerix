// Pure helpers for the Planet X page: read web/data/planetx-limits.json (written by
// `python -m pxs.planetx`). No DOM here, so node:test can cover it.

/** A reach value is a number of au, "<200" (fainter even at 200 au) or ">1500". */
export function reachRank(v) {
  if (typeof v === 'number') return v;
  const n = Number(String(v).slice(1));
  return String(v).startsWith('<') ? n - 1 : n + 1;
}

const better = (a, b) => (reachRank(a) >= reachRank(b) ? a : b);

/** Furthest reach over the bands of one depth, separately for lo, nom and hi. */
export function bestReach(caseBlock, depthKey) {
  const perBand = Object.values(caseBlock.reach_au?.[depthKey] || {});
  if (!perBand.length) return null;
  return perBand.reduce((acc, r) => ({ lo: better(acc.lo, r.lo), nom: better(acc.nom, r.nom), hi: better(acc.hi, r.hi) }));
}

const au = (v) => (typeof v === 'number' ? String(v) : String(v));

/** "350 au (225 to 550)", or "under 200 au" when even the bright end is not reached. */
export function reachText(r) {
  if (!r) return '–';
  if (typeof r.hi === 'string' && r.hi.startsWith('<')) return `under ${r.hi.slice(1)} au`;
  return `${au(r.nom)} au (${au(r.lo)} to ${au(r.hi)})`;
}

/** Where Planet Nine is predicted, in au (Batygin et al. 2019). */
export const P9_RANGE_AU = [400, 800];

/** A reach value as a number for a plot, clipped to the grid ("<200" is 200, ">1500" is 1500). */
const plotAu = (v) => (typeof v === 'number' ? v : Number(String(v).slice(1)));

/**
 * One bar per planet for the reach chart: dark (lo) to bright (hi) end, the most likely value
 * (nom) and its words. [{key, label, lo, nom, hi, text}]
 */
export function reachBars(data, depthKey) {
  return data.cases.map((c) => ({ key: c.key, label: c.label, r: bestReach(c, depthKey) })).filter((x) => x.r).map(({ key, label, r }) => ({
    key, label, lo: plotAu(r.lo), nom: plotAu(r.nom), hi: plotAu(r.hi),
    text: typeof r.nom === 'number' ? `${r.nom} au` : r.nom.startsWith('<') ? `under ${r.nom.slice(1)} au` : `beyond ${r.nom.slice(1)} au`,
  }));
}

/**
 * The page's answer in plain words, from the 10-Earth-mass case against one SPHEREx all-sky map
 * per channel: {verdict, detail}, or null if that case is missing.
 */
export function leadAnswer(data) {
  const c = data.cases.find((x) => x.key === 'se10');
  const r = c && bestReach(c, 'spx_one_map_channel');
  if (!r) return null;
  const [near, far] = P9_RANGE_AU;
  const verdict = reachRank(r.hi) < near ? 'Probably not.'
    : reachRank(r.nom) < near ? 'Only just, and only if the planet is bright and on the near side of where it is predicted.'
      : 'Yes, over part of the range where it is predicted.';
  const detail = `In one SPHEREx map of the whole sky, a planet of 10 Earth masses would stand out from the noise to about ${reachText(r)}, dark to bright, against ${near} to ${far} au where Planet Nine is predicted. An estimate of reach, not a detection.`;
  return { verdict, detail };
}

/** Depth lines that apply to one band: [{key, label, kind, per, shallow, deep}]. */
export function depthLinesFor(data, band) {
  return data.depths.filter((d) => d.ab[band]).map((d) => ({
    key: d.key, label: d.label, kind: d.kind, per: d.per, shallow: d.ab[band][0], deep: d.ab[band][1],
  }));
}

/** x and the lo/nom/hi magnitude curves of one case in one band. */
export function caseSeries(data, caseBlock, band) {
  const c = caseBlock.ab[band];
  return { x: data.distances_au, lo: c.lo, nom: c.nom, hi: c.hi };
}

/** Fortney et al. 2016 methane-depleted thermal range for a WISE band, or null. */
export function fortneySeries(data, band) {
  const f = data.fortney_methane_depleted?.ab?.[band];
  return f ? { x: data.distances_au, faint: f.lo, bright: f.hi } : null;
}
