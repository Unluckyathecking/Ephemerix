// "What was rejected": the frames that lost most pixels to quality flags, the frames where the
// object was not found, and the per-frame reasons the pipeline wrote. Pure; only manifest data.

import { setLabel, nameBands } from './labels.js';

// Frame notes that say nothing about rejection (flags.js treats them as routine too).
const ROUTINE = [/^frame quality unknown/i, /^registered to \d+ gaia/i];
// Below this share, dropped pixels are the usual cosmic rays and bad pixels.
export const ROUTINE_SHARE = 0.1;

const pct = (x) => `${Math.max(1, Math.round(x * 100))}%`;

/**
 * @param {object} m validated manifest
 * @param {number} limit frames listed per group
 * @returns {null | {flagged: {frame: object, text: string}[], flaggedNote: string, missed: {frame: object, text: string}[],
 *   missedNote: string, reasons: {text: string, n: number}[]}}  null when nothing was rejected
 */
export function rejectedSummary(m, limit = 5) {
  const frames = m.frames || [];
  const label = (f) => `${f.date.slice(0, 10)}, ${setLabel(f)}`;

  const known = frames.filter((f) => Number.isFinite(f.flag_fraction));
  const withFlags = known.filter((f) => f.flag_fraction > 0).sort((a, b) => b.flag_fraction - a.flag_fraction);
  const flagged = withFlags.slice(0, limit).map((f) => ({ frame: f, text: `${label(f)}: ${pct(f.flag_fraction)} of pixels dropped` }));
  const big = withFlags.filter((f) => f.flag_fraction >= ROUTINE_SHARE).length;
  const every = known.length === frames.length ? 'Every frame' : `Each of the ${known.length} frames with a flagged share`;
  const flaggedNote = !withFlags.length ? ''
    : big ? `${big} of ${known.length} frames lost ${pct(ROUTINE_SHARE)} or more of their pixels to quality flags (cosmic rays, saturated or bad pixels), so their brightness is less certain.`
      : `${every} kept at least ${pct(1 - ROUTINE_SHARE)} of its pixels; the few per cent dropped are routine cosmic rays and bad pixels.`;

  // A Solar System body is measured at its predicted position, never searched for, so "not found" does not apply.
  const misses = m.solar_system ? [] : frames.filter((f) => !f.centroid_px);
  const missed = misses.slice(0, limit).map((f) => ({ frame: f, text: label(f) }));
  const bySet = new Map();
  for (const f of misses) bySet.set(setLabel(f), (bySet.get(setLabel(f)) || 0) + 1);
  const totals = new Map();
  for (const f of frames) totals.set(setLabel(f), (totals.get(setLabel(f)) || 0) + 1);
  const missedNote = misses.length
    ? `The object was not found in ${misses.length} of ${frames.length} frames (${[...bySet].map(([s, n]) => `${s}: ${n} of ${totals.get(s)}`).join('; ')}). Those frames still blink, but give no position to the measured motion.`
    : '';

  // Pipeline notes may name a frame set by its id ("disagrees with spx-b6"); name it as the page does.
  const counts = new Map();
  for (const f of frames) {
    for (const w of new Set((f.warnings || []).map((x) => nameBands(x, frames)))) {
      if (!ROUTINE.some((re) => re.test(w))) counts.set(w, (counts.get(w) || 0) + 1);
    }
  }
  const reasons = [...counts].sort((a, b) => b[1] - a[1]).map(([w, n]) => ({ text: `${w.charAt(0).toUpperCase()}${w.slice(1)}: ${n} frame${n === 1 ? '' : 's'}.`, n }));

  if (!withFlags.length && !misses.length && !reasons.length) return null;
  return { flagged, flaggedNote, missed, missedNote, reasons };
}
