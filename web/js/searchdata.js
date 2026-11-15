// Pure helpers for the blind-search page: read web/data/movers.json (written by
// `python -m pxs.movers.summary`) and web/data/planetx-limits.json. No DOM, so node:test covers it.

import { P9_RANGE_AU } from './planetxdata.js';

const num = (x, d = 0) => (x == null ? '–' : Number(x).toFixed(d));

/**
 * One plain sentence on the pilot search of the Planet Nine region, from p9-search.json: its
 * 50% limit against how far the most likely 10-Earth-mass planet would then be seen. Null when
 * the file is missing or incomplete.
 */
export function pilotSentence(p9) {
  const v = p9?.pooled?.vmag50;
  if (!Number.isFinite(v) || !Number.isFinite(p9?.area_deg2)) return null;
  const nom = (p9.planetx_reach?.at_pooled_flux50 || []).find((r) => r.key === 'se10')?.reach_nom_au;
  const [near, far] = P9_RANGE_AU;
  const reach = Number.isFinite(nom) && nom < near
    ? ` At that limit even the most likely 10-Earth-mass planet would be seen only to about ${Math.round(nom)} au, short of the ${near} to ${far} au where it is predicted.`
    : '';
  return `A smaller pilot over ${p9.area_deg2.toFixed(1)} square degrees where Planet Nine is predicted cannot test Planet Nine. It finds half of planted objects only down to V ${v.toFixed(1)} and rules out none of the favoured cases.${reach}`;
}

/**
 * The page's answer in plain words, from movers.json and (when it loaded) p9-search.json.
 * The pilot sentence is left out when the pilot file is missing or incomplete.
 */
export function searchLead(m, p9) {
  const k = m.known_bodies.length;
  const names = m.known_bodies.map((b) => b.name);
  const list = names.length > 1 ? `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}` : names.join('');
  const t = peakTotals(m.fields, ['tno', 'blank']);
  const thr = m.campaign?.threshold_snr ?? 7;
  const blind = `Given no positions, our search tries thousands of paths through ${m.fields.length} small patches of SPHEREx sky and picks out all ${k} known dwarf planets there, ${list}: a validation, not a discovery.`;
  const verdict = t.real <= t.null ? 'nothing new above the noise' : 'an excess we have not followed up, and no claimed new object';
  const nul = `Real sky: ${t.real} peaks at S/N ${thr} or above in ${t.fields} non-control fields; run backwards, where nothing real moves: ${t.null}. That is ${verdict}.`;
  const pilot = pilotSentence(p9);
  return [blind, nul, pilot].filter(Boolean).join(' ');
}

/** Plot series of one 8-bin completeness curve: bins with injections only. */
export function curveSeries(rows) {
  const ok = rows.filter((r) => r.n > 0 && r.frac != null);
  return { x: ok.map((r) => r.flux_ujy), y: ok.map((r) => r.frac), lo: ok.map((r) => r.ci95[0]), hi: ok.map((r) => r.ci95[1]), n: ok.map((r) => r.n) };
}

/** "42/50 (0.71–0.92)": recovered / injected with the 95% Wilson interval. */
export function binText(b) {
  return b.n ? `${b.k}/${b.n} (${num(b.ci95[0], 2)}–${num(b.ci95[1], 2)})` : '–';
}

/** "0", or "3 (max 9.8)" for a count of peaks with their highest S/N. */
export function peakText(count, max) {
  return count ? `${count} (max ${num(max, 1)})` : '0';
}

/** Totals of real-sky and mirrored-null peaks at S/N >= 7 over fields of one kind set. */
export function peakTotals(fields, kinds) {
  const fs = fields.filter((f) => kinds.includes(f.kind));
  return { fields: fs.length, real: fs.reduce((a, f) => a + f.peaks.real_ge7, 0), null: fs.reduce((a, f) => a + f.peaks.null_ge7, 0) };
}

/** [min, max] of a numeric field property, e.g. the per-field 50% flux or motion limit. */
export function range(fields, get) {
  const v = fields.map(get).filter((x) => x != null && Number.isFinite(x));
  return v.length ? [Math.min(...v), Math.max(...v)] : null;
}

/**
 * Distance (au) at which an AB-magnitude curve, rising with distance, reaches `lim`:
 * a number rounded to 5 au, "<first" if already fainter at the first grid distance,
 * ">last" if still brighter at the last.
 */
export function crossing(dist, mag, lim) {
  if (mag[0] > lim) return `<${dist[0]}`;
  for (let i = 1; i < mag.length; i += 1) {
    if (mag[i] > lim) {
      const t = (lim - mag[i - 1]) / (mag[i] - mag[i - 1]);
      return Math.round((dist[i - 1] + t * (dist[i] - dist[i - 1])) / 5) * 5;
    }
  }
  return `>${dist[dist.length - 1]}`;
}

/**
 * Brightness-only reach of each Planet X case for a limit in AB at 1 µm, read off the
 * planetx-limits.json curves of the band containing 1 µm: [{key, label, lo, nom, hi}].
 * lo is the darkest plausible version of the planet, hi the brightest.
 */
export function brightnessReach(planetx, abLimit, band = 'SPHEREx D1') {
  const d = planetx.distances_au;
  return planetx.cases.map((c) => {
    const ab = c.ab[band];
    return { key: c.key, label: c.label, lo: crossing(d, ab.lo, abLimit), nom: crossing(d, ab.nom, abLimit), hi: crossing(d, ab.hi, abLimit) };
  });
}

/** "about 425 au (under 200 to 600)" from a brightnessReach row. */
export function reachText(r) {
  const t = (v) => (typeof v === 'number' ? `${v}` : v.startsWith('<') ? `under ${v.slice(1)}` : `beyond ${v.slice(1)}`);
  return `about ${t(r.nom)} au (${t(r.lo)} to ${t(r.hi)})`;
}
