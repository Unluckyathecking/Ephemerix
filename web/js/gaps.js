// Time gaps between frames: stretches with no images in the selected sets, and the cue shown
// when playback or stepping jumps across one. Pure.

import { decimalYear } from './sky.js';

export const GAP_MIN_YEARS = 1;
export const GAP_LONG_YEARS = 3;
export const GAP_MEDIAN_FACTOR = 5;

const median = (xs) => {
  const s = [...xs].sort((a, b) => a - b);
  return s.length ? s[Math.floor(s.length / 2)] : 0;
};

/**
 * Stretches much longer than the usual spacing: over 3 years, or over 5 times the median step
 * (and at least a year).
 * @param {object[]} frames in any order
 * @returns {{a: object, b: object, ya: number, yb: number, years: number}[]} a is the frame before the gap
 */
export function findGaps(frames) {
  const fs = [...frames].sort((p, q) => p.mjd - q.mjd);
  const ys = fs.map((f) => decimalYear(f.mjd));
  const steps = ys.slice(1).map((y, i) => y - ys[i]);
  const typical = median(steps.filter((d) => d > 0.02));
  const out = [];
  steps.forEach((d, i) => {
    if (d > GAP_LONG_YEARS || (d >= GAP_MIN_YEARS && d > GAP_MEDIAN_FACTOR * typical)) {
      out.push({ a: fs[i], b: fs[i + 1], ya: ys[i], yb: ys[i + 1], years: d });
    }
  });
  return out;
}

/** "no images 2011–2024": the whole years strictly between the two frames. */
export function gapLabel(g) {
  const from = Math.floor(g.ya) + 1, to = Math.ceil(g.yb) - 1;
  return from <= to ? `no images ${from}–${to}` : `no images for ${g.years.toFixed(1)} years`;
}

/** "15 years later" / "5 years earlier" when stepping from frame `prev` to `next` crosses a gap, else null. */
export function gapCue(prev, next, gaps) {
  if (!prev || !next || prev === next) return null;
  const [lo, hi] = prev.mjd < next.mjd ? [prev, next] : [next, prev];
  const crossed = gaps.filter((g) => g.a.mjd >= lo.mjd && g.b.mjd <= hi.mjd);
  if (!crossed.length) return null;
  const years = Math.round((hi.mjd - lo.mjd) / 365.25);
  return `${years} ${years === 1 ? 'year' : 'years'} ${prev.mjd < next.mjd ? 'later' : 'earlier'}`;
}
