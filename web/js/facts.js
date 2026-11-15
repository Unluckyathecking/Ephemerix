// A few plain facts worked out from a view's own numbers, each with a one-line "How:".
// Pure: `viewFacts` takes a validated manifest (manifest.js) and returns [{title, text, how}].
// A fact is left out when its input is missing or not significant. `factsBlock` builds the
// DOM list of cards with dom.js helpers.

import { el, shortDate } from './dom.js';
import { gaiaCounterpart } from './gaiacheck.js';

const fin = Number.isFinite;

export const MOON_ARCSEC = 1800; // the full Moon is about half a degree wide
// Facts derived from the motion (Moon crossing, heading, sideways speed) need the motion to be at
// least this many times its error, so a figure like "53,000 years" is not printed from a motion
// known to 30%. The headline's own rule (summary.js, 3 sigma) only says whether there is a motion.
export const MIN_MOTION_SIGMA = 5;
export const MIN_PARALLAX_SIGMA = 5;
export const KM_S_PER_AU_YR = 4.74; // 1 au a year in km/s
export const EARTH_ORBIT_KM_S = 29.8;
const LY_PER_PARSEC = 3.2616;
const LIGHT_MIN_PER_AU = 499.005 / 60;
const DAYS_PER_YEAR = 365.25;
const COMPASS = ['north', 'north-east', 'east', 'south-east', 'south', 'south-west', 'west', 'north-west'];

/** A number to `sig` significant figures, with thousands separators ("1,800", "0.15"). */
export function roundSig(x, sig = 2) {
  if (!fin(x) || x === 0) return '0';
  const digits = Math.max(0, sig - 1 - Math.floor(Math.log10(Math.abs(x))));
  return Number(x.toPrecision(sig)).toLocaleString('en-GB', { maximumFractionDigits: digits });
}

/** Direction on the sky of a motion (mas/yr, east and north) in words, and the angle east of north. */
export function direction(pmra, pmdec) {
  const deg = ((Math.atan2(pmra, pmdec) * 180) / Math.PI + 360) % 360;
  return { deg, word: COMPASS[Math.round(deg / 45) % 8] };
}

/** The measured motion when it is at least MIN_MOTION_SIGMA from zero, else null. */
function significantMotion(m) {
  const mm = m.measured_motion;
  if (!mm || !fin(mm.pmra_masyr) || !fin(mm.pmdec_masyr) || !fin(mm.err_masyr) || mm.err_masyr <= 0) return null;
  const total = Math.hypot(mm.pmra_masyr, mm.pmdec_masyr);
  return total / mm.err_masyr >= MIN_MOTION_SIGMA ? { ...mm, total } : null;
}

/** The target's Gaia DR3 row when its parallax is positive and at least MIN_PARALLAX_SIGMA. */
function gaiaParallax(m) {
  const c = gaiaCounterpart(m);
  const g = c?.status === 'match' ? c.source : null;
  if (!g || !fin(g.parallax_mas) || !fin(g.parallax_error_mas) || g.parallax_error_mas <= 0) return null;
  return g.parallax_mas > 0 && g.parallax_mas / g.parallax_error_mas >= MIN_PARALLAX_SIGMA ? g : null;
}

/** "8.16 ± 0.01 arcsec a year": the headline's precision (summary.js describeMotion). */
const asecYr = (masyr, errMasyr = null) =>
  `${(masyr / 1000).toFixed(2)}${fin(errMasyr) ? ` ± ${(errMasyr / 1000).toFixed(2)}` : ''} arcsec a year`;
const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;
const yearOf = (mjd) => new Date((mjd - 40587) * 86400000).getUTCFullYear();
const yearRange = (a, b) => (a === b ? `in ${a}` : `from ${a} to ${b}`);

function motionFacts(mv) {
  const years = MOON_ARCSEC / (mv.total / 1000);
  const span = mv.method === 'all_frames' ? `all ${mv.n_frames} W2 images fitted at once`
    : `${mv.n_detections} detections`;
  const over = fin(mv.baseline_years) ? ` over ${roundSig(mv.baseline_years, 2)} years` : '';
  // Same precision as the view's headline (summary.js describeMotion): 0.01 arcsec a year.
  const measured = `Our measured motion, ${asecYr(mv.total, mv.err_masyr)}, from ${span}${over}`;
  const dir = direction(mv.pmra_masyr, mv.pmdec_masyr);
  return [
    { title: 'Against the Moon',
      text: `Crosses the width of the full Moon in about ${roundSig(years, 2)} years.`,
      how: `${measured}; the full Moon is about ${MOON_ARCSEC.toLocaleString('en-GB')} arcsec wide.` },
    { title: 'Heading',
      text: `Moves towards the ${dir.word} of the sky.`,
      how: `Direction of our measured motion: ${Math.round(dir.deg)}° east of north.` },
  ];
}

function distanceFacts(g, mv) {
  const out = [{
    title: 'Distance',
    text: `${roundSig((1000 / g.parallax_mas) * LY_PER_PARSEC, 2)} light-years away.`,
    how: `Gaia DR3 parallax, ${roundSig(g.parallax_mas, 4)} ± ${roundSig(g.parallax_error_mas, 2)} mas: distance is 1 / parallax.`,
  }];
  if (mv) {
    const kms = (KM_S_PER_AU_YR * (mv.total / 1000)) / (g.parallax_mas / 1000);
    out.push({
      title: 'Sideways speed',
      text: `Moves across our line of sight at about ${roundSig(kms, 2)} km/s, ${roundSig(kms / EARTH_ORBIT_KM_S, 2)} times Earth's speed around the Sun.`,
      how: `4.74 × our measured motion (${asecYr(mv.total)}) / Gaia DR3 parallax (${roundSig(g.parallax_mas / 1000, 3)} arcsec); Earth orbits at ${EARTH_ORBIT_KM_S} km/s.`,
    });
  }
  return out;
}

/** Distance from the Sun at the latest pass with an ephemeris (JPL Horizons, in the manifest). */
function sunFact(ss) {
  const rows = ss.passes.flatMap((p) => p.ephemeris.filter((e) => fin(e.r_au) && fin(e.mjd)));
  if (!rows.length) return [];
  const last = rows.reduce((a, b) => (b.mjd > a.mjd ? b : a));
  const lmin = last.r_au * LIGHT_MIN_PER_AU;
  const hours = lmin >= 120 ? ` (about ${roundSig(lmin / 60, 2)} hours)` : '';
  return [{
    title: 'From the Sun',
    text: `${roundSig(last.r_au, 3)} au from the Sun: sunlight takes ${Math.round(lmin)} minutes to get there${hours}.`,
    how: `JPL Horizons distance at our latest SPHEREx pass; 1 au is ${roundSig(LIGHT_MIN_PER_AU, 3)} light-minutes.`,
  }];
}

function latestLook(date) {
  return { title: 'Latest look', text: `SPHEREx last looked on ${shortDate(date)}.`,
    how: 'The date of the newest SPHEREx image in this view.' };
}

/** A Solar System body: SPHEREx passes, not the sky-fixed sub-stacks of the one pass shown. */
function passFacts(ss) {
  const passes = ss.passes.filter((p) => p.date_end);
  if (!passes.length) return [];
  const ends = passes.map((p) => p.date_end).sort();
  const y = (iso) => new Date(iso).getUTCFullYear();
  const n = passes.reduce((s, p) => s + (fin(p.n_frames) ? p.n_frames : 0), 0);
  return [
    { title: 'Images',
      text: `SPHEREx looked ${plural(passes.length, 'time')}, ${yearRange(y(passes[0].date_start || ends[0]), y(ends.at(-1)))}.`,
      how: `Counted from this view: ${plural(passes.length, 'SPHEREx pass')}${n ? ` with ${n} images` : ''}.` },
    { ...latestLook(ends.at(-1)), how: 'The end of the newest SPHEREx pass in this view.' },
  ];
}

function coverageFacts(m) {
  if (m.solar_system) return passFacts(m.solar_system);
  const frames = m.frames.filter((f) => fin(f.mjd));
  if (!frames.length) return [];
  const mjds = frames.map((f) => f.mjd);
  const span = (Math.max(...mjds) - Math.min(...mjds)) / DAYS_PER_YEAR;
  const missions = [...new Set(frames.map((f) => f.mission))].join(' and ');
  const out = [{
    title: 'Images',
    text: span >= 1
      ? `${frames.length} images over ${Math.round(span)} years.`
      : `${plural(frames.length, 'image')}.`,
    how: `Counted from this view: ${missions} images ${yearRange(yearOf(Math.min(...mjds)), yearOf(Math.max(...mjds)))}.`,
  }];
  const spx = frames.filter((f) => f.mission === 'SPHEREx');
  if (spx.length) out.push(latestLook(spx.reduce((a, b) => (b.mjd > a.mjd ? b : a)).date));
  return out;
}

/**
 * @param {object} m validated manifest
 * @returns {{title: string, text: string, how: string}[]}
 */
export function viewFacts(m) {
  if (!m || !Array.isArray(m.frames)) return [];
  const mv = significantMotion(m);
  const g = m.solar_system ? null : gaiaParallax(m);
  return [
    ...(mv ? motionFacts(mv) : []),
    ...(g ? distanceFacts(g, mv) : []),
    ...(m.solar_system ? sunFact(m.solar_system) : []),
    ...coverageFacts(m),
  ];
}

/** The facts a view already states elsewhere (the data tile and the simple video line count the images). */
export const SHOWN_ELSEWHERE = ['Images'];

/** A short list of fact cards, or null when there are none. `omit`: titles to leave out. */
export function factsBlock(m, { omit = [] } = {}) {
  const facts = viewFacts(m).filter((f) => !omit.includes(f.title));
  if (!facts.length) return null;
  return el('ul', { class: 'facts', 'aria-label': 'Facts from our measurements' }, facts.map((f) =>
    el('li', { class: 'fact' }, [
      el('p', { class: 'fact-title', text: f.title }),
      el('p', { class: 'fact-text', text: f.text }),
      el('p', { class: 'fact-how', text: `How: ${f.how}` }),
    ])));
}

/** The fact cards under a heading, as a card section; null when there are none. */
export function factsSection(m) {
  const list = factsBlock(m, { omit: SHOWN_ELSEWHERE });
  return list ? el('section', { class: 'card facts-card', 'aria-labelledby': 'facts-h' }, [
    el('h2', { id: 'facts-h', text: 'In plain numbers' }), list,
  ]) : null;
}
