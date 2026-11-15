// Difference and sum of two frames, from decoded 8-bit PNG pixels. Pure.
// The PNGs are stretched for display, so this is a display difference, not photometry.

import { setLabel } from './labels.js';

export const MODES = { diff: 'B minus A', sum: 'A plus B' };

/**
 * Can frames A and B be combined? Only within one frame set: same mission, band and stretch.
 * @returns {{ok: boolean, reason: string|null}}
 */
export function compareAllowed(a, b) {
  if (!a || !b) return { ok: false, reason: 'Pick two frames.' };
  if (a.id === b.id) return { ok: false, reason: 'A and B are the same frame. Pick two different dates.' };
  if (a.band !== b.band) {
    return { ok: false, reason: `A is ${setLabel(a)} and B is ${setLabel(b)}. Each image set has its own wavelength and its own brightness stretch, so subtracting across sets shows the difference in processing, not a change in the sky. Pick both frames from the same set.` };
  }
  return { ok: true, reason: null };
}

/** Default pair: the first and last frame of `band` (null if it has fewer than two). */
export function defaultPair(frames, band) {
  const own = frames.filter((f) => f.band === band);
  return own.length >= 2 ? [own[0], own.at(-1)] : null;
}

const DAYS_PER_YEAR = 365.25;
const first = (own) => own.reduce((x, f) => (f.mjd < x.mjd ? f : x));
const last = (own) => own.reduce((x, f) => (f.mjd > x.mjd ? f : x));
/** Is score list s greater than t, comparing element by element? */
const beats = (s, t) => {
  const i = s.findIndex((v, k) => v !== t[k]);
  return i >= 0 && s[i] > t[i];
};

/**
 * Opening pair for the frames that are playing: the earliest and the latest frame of one set,
 * the set spanning the most whole years (so a mover has moved), then the one whose two ends
 * both show the object, then the longest span. Null if no set has two frames.
 * @param {{id: string, band: string, mjd: number, centroid_px?: number[]|null}[]} playing
 * @returns {[object, object]|null}
 */
export function playingPair(playing) {
  const bands = [...new Set((playing || []).map((f) => f.band))];
  let best = null;
  for (const band of bands) {
    const own = playing.filter((f) => f.band === band);
    if (own.length < 2) continue;
    const a = first(own), b = last(own), span = b.mjd - a.mjd;
    const score = [Math.floor(span / DAYS_PER_YEAR), !!a.centroid_px + !!b.centroid_px, span];
    if (!best || beats(score, best.score)) best = { pair: [a, b], score };
  }
  return best?.pair ?? null;
}

/** One line under the pickers: which two dates are combined, and how far apart. */
export function pairCaption(a, b, mode, label, fmt) {
  const years = Math.abs(b.mjd - a.mjd) / DAYS_PER_YEAR;
  const gap = years >= 1.5 ? `${Math.round(years)} years apart` : `${Math.round(years * 12)} months apart`;
  const what = mode === 'sum' ? 'A + B (mean)' : 'B − A';
  return `${what}: A is ${fmt(a.date)}, B is ${fmt(b.date)}, ${gap}, ${label}.`;
}

/**
 * Combine two RGBA pixel arrays of equal length (greyscale: the red channel is read).
 * diff: 128 + (B - A) / 2, so unchanged pixels are mid-grey, B-only light is bright, A-only dark.
 * sum:  (A + B) / 2, the mean, so it stays inside the display range.
 * @param {Uint8ClampedArray|number[]} a
 * @param {Uint8ClampedArray|number[]} b
 * @param {'diff'|'sum'} mode
 * @returns {Uint8ClampedArray}
 */
export function combinePixels(a, b, mode) {
  if (a.length !== b.length || a.length % 4) throw new RangeError('Pixel arrays must be RGBA and the same size.');
  const out = new Uint8ClampedArray(a.length);
  for (let i = 0; i < a.length; i += 4) {
    const v = mode === 'sum' ? (a[i] + b[i]) / 2 : 128 + (b[i] - a[i]) / 2;
    out[i] = out[i + 1] = out[i + 2] = Math.round(v);
    out[i + 3] = 255;
  }
  return out;
}
