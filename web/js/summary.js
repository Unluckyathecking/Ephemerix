// Plain-language motion text and the forum-ready vetting summary. Pure functions.

import { formatRa, formatDec } from './coords.js';
import { motionVector } from './sky.js';
import { notBrownDwarf, typeRangeText, pairText, showsType, passSummary, hasPair } from './matchtext.js';
import { noMatchReason } from './flags.js';
import { vettingLines } from './vetting.js';
import { gaiaCounterpart } from './gaiacheck.js';
import { SITE } from './site.js';

const POINTS = ['north', 'north-east', 'east', 'south-east', 'south', 'south-west', 'west', 'north-west'];

/** Compass word for a position angle (deg east of north). */
export function compassWord(pa) {
  return POINTS[Math.round((((pa % 360) + 360) % 360) / 45) % 8];
}

/**
 * Describe a proper motion for a newcomer.
 * @returns {{arcsecPerYear:number, pa:number, words:string, exact:string} | null}
 */
/**
 * What a measured motion rests on. `allFrames`: no single image shows the object clearly
 * enough to measure its position, so all the W2 images were fitted at once
 * (measured_motion.method "all_frames"); there are then no detections to count.
 * `short` continues "Measured motion ..."; `sentence` stands alone, without a full stop.
 * @param {{method?: string|null, n_frames?: number|null, n_detections?: number|null}|null} mm
 * @returns {{allFrames: boolean, short: string, sentence: string}}
 */
export function motionBasis(mm) {
  if (mm?.method === 'all_frames') {
    const all = Number.isFinite(mm.n_frames) ? `all ${mm.n_frames} W2 images` : 'all the W2 images';
    return { allFrames: true,
      short: `from ${all} fitted at once, as no single image shows the object`,
      sentence: `No single image shows the object clearly enough to measure its position, so this motion comes from fitting ${all} at once` };
  }
  const n = mm?.n_detections;
  return { allFrames: false, short: n > 0 ? `from ${n} detections` : '', sentence: `From ${n ?? 'several'} detections` };
}

export function describeMotion(pmra, pmdec, errMasyr = null) {
  if (!Number.isFinite(pmra) || !Number.isFinite(pmdec)) return null;
  const { total, pa } = motionVector(pmra, pmdec);
  const arcsecPerYear = total / 1000;
  const err = Number.isFinite(errMasyr) ? ` ± ${(errMasyr / 1000).toFixed(2)}` : '';
  // A direction is only given when the motion clears its error: none under 2 sigma, hedged under 3.
  const sigma = Number.isFinite(errMasyr) && errMasyr > 0 ? total / errMasyr : Infinity;
  const toward = sigma < 2 ? ', too small against its error to give a direction'
    : ` toward the ${compassWord(pa)}${sigma < SIGNIFICANT_SIGMA ? ' (direction uncertain)' : ''}`;
  const words = arcsecPerYear < 0.01
    ? 'no measurable motion'
    : `${arcsecPerYear.toFixed(2)}${err} arcsec per year${toward}`;
  const exact = `pmRA ${pmra.toFixed(1)}, pmDec ${pmdec.toFixed(1)} mas/yr, PA ${pa.toFixed(0)}°`;
  return { arcsecPerYear, pa, words, exact };
}

const SIGNIFICANT_SIGMA = 3;

// Warnings saying that images are missing from a partial view (src/pxs/sources.py, src/pxs/wise/search.py).
const IMAGES_MISSING = /(WISE images|SPHEREx data) could not be loaded|search for WISE frames from .+ failed|(WISE|SPHEREx) stacks.* failed/i;
// The catalogue neighbour checks did not run (src/pxs/blend.py CHECKS_NOT_RUN).
const NEIGHBOURS_UNCHECKED = /checks for neighbours .* could not be run/i;

/** True when a partial view lacks some of its images: it cannot say what is not in the sky. */
export function imagesMissing(m) {
  return m.degraded === true && (m.warnings || []).some((w) => IMAGES_MISSING.test(w));
}

/** True when a partial view could not check for neighbouring stars, so a spectral type is unconfirmed. */
export function neighboursUnchecked(m) {
  return m.degraded === true && (m.warnings || []).some((w) => NEIGHBOURS_UNCHECKED.test(w));
}

/** True when a star-field view found the object in no image at all (no motion, no centroid). */
export function nothingVisible(m) {
  // In glare (field.saturated) the object is hidden, not absent: the glare sentence says why.
  // With images missing, or a motion the pipeline could not measure, nothing was established.
  if (imagesMissing(m) || m.motion_not_measured) return false;
  return !m.solar_system && !m.field?.saturated && !m.measured_motion && !(m.frames || []).some((f) => f.centroid_px);
}

/**
 * Is the measured motion a motion? Larger than 0.01 arcsec a year and than three times its error.
 * Every headline (verdict strip, hero, Talk summary, simple view) uses this one rule.
 * @param {{pmra_masyr: number, pmdec_masyr: number, err_masyr?: number|null}|null} mm
 */
export function motionSignificant(mm) {
  if (!mm || !Number.isFinite(mm.pmra_masyr) || !Number.isFinite(mm.pmdec_masyr)) return false;
  const total = Math.hypot(mm.pmra_masyr, mm.pmdec_masyr);
  const err = Number.isFinite(mm.err_masyr) ? mm.err_masyr : 0;
  return total >= 10 && total > SIGNIFICANT_SIGMA * err;
}

/** "0.61 ± 0.95″ a year, within its error": the figure kept beside the honest headline. */
export function insignificantText(mm, unit = '″ a year') {
  const total = Math.hypot(mm.pmra_masyr, mm.pmdec_masyr) / 1000;
  const err = Number.isFinite(mm.err_masyr) ? ` ± ${(mm.err_masyr / 1000).toFixed(2)}` : '';
  return `${total.toFixed(2)}${err}${unit.startsWith('″') ? '' : ' '}${unit}, within its error`;
}

/** One sentence comparing measured motion to the catalogue value, or null if either is missing. */
export function compareMotion(measured, target) {
  if (!measured || !Number.isFinite(target?.pmra_masyr) || !Number.isFinite(target?.pmdec_masyr)) return null;
  const dx = measured.pmra_masyr - target.pmra_masyr;
  const dy = measured.pmdec_masyr - target.pmdec_masyr;
  const diff = Math.hypot(dx, dy);
  const cat = Math.hypot(target.pmra_masyr, target.pmdec_masyr);
  const err = Number.isFinite(measured.err_masyr) && measured.err_masyr > 0 ? measured.err_masyr : null;
  if (err != null && diff <= 3 * err) {
    return diff < 5 ? 'Agrees with the catalogue motion (difference under 0.01 arcsec/yr).'
      : `Agrees with the catalogue motion (they differ by ${(diff / 1000).toFixed(2)} arcsec/yr, within the measurement error).`;
  }
  const pct = cat > 0 ? ` (${((diff / cat) * 100).toFixed(0)}% of the catalogue value)` : '';
  return `Differs from the catalogue motion by ${(diff / 1000).toFixed(2)} arcsec/yr${pct}. Check the frames by eye.`;
}

const AGREE_SIGMA = 3;

/**
 * The headline of the motion panel: measured against catalogue in one plain sentence.
 * Components are tested one by one against their own errors, so a disagreement can say which.
 * @returns {{text: string, agree: boolean}|null} null when either motion is missing
 */
export function motionHeadline(measured, target) {
  if (!measured || !Number.isFinite(target?.pmra_masyr) || !Number.isFinite(target?.pmdec_masyr)) return null;
  const m = Math.hypot(measured.pmra_masyr, measured.pmdec_masyr) / 1000;
  const c = Math.hypot(target.pmra_masyr, target.pmdec_masyr) / 1000;
  const err = (k) => {
    const e = measured[`err_${k}_masyr`];
    return Number.isFinite(e) && e > 0 ? e : (Number.isFinite(measured.err_masyr) && measured.err_masyr > 0 ? measured.err_masyr : null);
  };
  const parts = [['pmra', 'right-ascension (east-west)'], ['pmdec', 'declination (north-south)']].map(([k, name]) => {
    const diff = measured[`${k}_masyr`] - target[`${k}_masyr`];
    const e = err(k);
    return { name, diff, off: e != null && Math.abs(diff) > AGREE_SIGMA * e };
  });
  const lead = `Measured ${m.toFixed(2)} arcsec/yr; the catalogue says ${c.toFixed(2)}`;
  const bad = parts.filter((p) => p.off);
  if (!bad.length) return { text: `${lead}: they agree.`, agree: true };
  const where = bad.map((p) => `${p.name} part by ${(Math.abs(p.diff) / 1000).toFixed(2)} arcsec/yr`).join(' and the ');
  return { text: `${lead}. They differ in the ${where}, more than the measurement error allows. Check the frames by eye.`, agree: false };
}

// A whole-view statement ("The target was not detected in any frame."), not a note about one frame.
const NOT_DETECTED = /^the (?:target|object) was not detected\b|\bnot detected in (?:any|enough)\b/i;

// A whole-view statement about the motion fit ("3 detections are left out of the motion fit because ...").
const MOTION_FIT = /\bmotion fit\b/i;

/**
 * Why no motion was measured, in one sentence: the pipeline's own warning when it says the object
 * was not detected or its detections were left out of the fit, else a count. Null when a motion was measured.
 * @param {object} m validated manifest
 * @returns {string|null}
 */
export function noMotionReason(m) {
  if (m.measured_motion) return null;
  // A motion was fitted but rests on too little (docs/api.md `motion_not_measured`): the pipeline's reason.
  const thin = m.motion_not_measured?.reason;
  if (thin) return `${thin.charAt(0).toUpperCase()}${thin.slice(1).replace(/\.$/, '')}.`;
  // A partial view that found nothing has not looked everywhere: it could not check, it did not find "nothing".
  if (imagesMissing(m) && !(m.frames || []).some((f) => f.centroid_px)) return 'This could not be checked: some of the images did not load, so an object here may be in the ones that are missing.';
  const w = (m.warnings || []).find((x) => NOT_DETECTED.test(x) && !/spectrum/i.test(x));
  if (w) return w;
  // Detections that exist but were left out of the fit (blended with a neighbour): the view's own sentence.
  const fit = (m.warnings || []).find((x) => MOTION_FIT.test(x));
  if (fit) return fit;
  const n = (m.frames || []).filter((f) => f.centroid_px).length;
  return n ? `The object was found in only ${n} frame${n === 1 ? '' : 's'}, too few to measure a motion.` : 'The object was not found in any frame.';
}

/** Headline for a panel with no measured motion: "Not measured: <reason>". Null when there is one. */
export function noMotionHeadline(m) {
  const why = noMotionReason(m);
  if (!why) return null;
  return `Not measured: ${/^[A-Z][a-z]/.test(why) ? why.charAt(0).toLowerCase() + why.slice(1) : why}`;
}

/** The type call in words. Confidence refers to the class call; the range carries the subtype. */
export function typeCall(match, warnings = []) {
  if (!match) {
    const why = noMatchReason(warnings);
    return why ? `no type call. ${why}` : 'No usable SPHEREx spectrum, so no type call.';
  }
  const conf = `${match.confidence} confidence in the class`;
  if (notBrownDwarf(match)) return `${match.verdict} (not a brown dwarf; ${conf}).`;
  if (match.class === 'uncertain') return `${match.verdict} (class uncertain: neither a brown dwarf nor a plain star fits clearly).`;
  const range = showsType(match) && !hasPair(match) ? typeRangeText(match) : null;
  const pair = pairText(match);
  return `${match.verdict} (${conf}${range ? `; likely type ${range}` : ''}).${pair ? ` ${pair}` : ''}`;
}

/**
 * Plain text for a Backyard Worlds Talk post, in the order a vetter reads it: where, how it
 * moves against the catalogue, the WISE colour, the Gaia check, what the spectrum says (or why
 * it says nothing), what to be wary of, and the link back.
 * @param {object} m validated manifest
 * @param {string} link shareable URL of this view
 */
export function vettingSummary(m, link) {
  const t = m.target;
  const lines = [];
  lines.push(`Candidate check: ${t.name || 'position'} `.trim());
  lines.push(`Position: RA ${formatRa(t.ra)}, Dec ${formatDec(t.dec)} (${t.ra.toFixed(5)}, ${t.dec.toFixed(5)} deg)` +
    (Number.isFinite(t.epoch) ? ` at epoch ${t.epoch}` : ''));
  const mm = m.measured_motion;
  const meas = mm && describeMotion(mm.pmra_masyr, mm.pmdec_masyr, mm.err_masyr);
  if (meas) {
    const base = Number.isFinite(mm.baseline_years) ? ` over ${mm.baseline_years.toFixed(1)} yr` : '';
    const basis = motionBasis(mm).short;
    const n = basis ? ` ${basis}` : '';
    // A motion within its own error is not a motion: say so, with the figure and its error.
    const words = motionSignificant(mm) ? meas.words : `no motion we can measure (${insignificantText(mm, 'arcsec per year')})`;
    lines.push(`Measured motion: ${words}${base}${n} [${meas.exact}]`);
  } else {
    lines.push(`Measured motion: not measured. ${noMotionReason(m)}`);
  }
  const cat = describeMotion(t.pmra_masyr, t.pmdec_masyr);
  lines.push(cat ? `Catalogue motion: ${cat.words} [${cat.exact}]` : 'Catalogue motion: unknown.');
  const cmp = compareMotion(mm, t);
  if (cmp) lines.push(cmp);
  lines.push(...vettingLines(m.vetting));
  const gaia = gaiaCounterpart(m);
  if (gaia?.text) lines.push(`Gaia DR3: ${gaia.text}`);
  lines.push(`Spectrum (SPHEREx): ${typeCall(m.match, m.warnings)}`);
  if (m.match?.best && m.match?.runner_up) lines.push(`Best template ${m.match.best.type}, runner-up ${m.match.runner_up.type}.`);
  const passes = passSummary(m.match);
  if (passes) lines.push(/[.!?]$/.test(passes) ? passes : `${passes}.`);
  if (m.match?.provisional) lines.push(`Provisional: ${m.match.provisional}`);
  const frameWarn = m.frames.filter((f) => f.warnings.length).length;
  if (frameWarn) lines.push(`${frameWarn} of ${m.frames.length} images carry a quality note.`);
  for (const w of m.warnings) lines.push(`Note: ${w}`);
  const y0 = m.frames[0]?.date.slice(0, 4), y1 = m.frames.at(-1)?.date.slice(0, 4);
  const missions = [...new Set(m.frames.map((f) => f.mission))].filter(Boolean).join(' and ');
  lines.push(`Checked with ${SITE.name}${missions ? ` on ${missions} images${y0 && y1 && y0 !== y1 ? `, ${y0} to ${y1}` : ''}` : ''}.`);
  lines.push(`View: ${link}`);
  return lines.join('\n');
}
