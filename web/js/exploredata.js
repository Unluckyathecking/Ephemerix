// Star data and hit-testing for the sky map. Pure (no DOM): the page fetches the JSON files and
// hands them here.

import { toVec } from './exploreproj.js';

/**
 * Decode web/data/stars.json (quantised, brightest first) into typed arrays.
 * @returns {{n: number, xyz: Float64Array, ra: Float64Array, dec: Float64Array, mag: Float32Array, bv: Float32Array}}
 */
export function decodeStars(json) {
  const n = json.ra.length;
  const xyz = new Float64Array(n * 3), ra = new Float64Array(n), dec = new Float64Array(n);
  const mag = new Float32Array(n), bv = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    ra[i] = json.ra[i] / 1000;
    dec[i] = json.dec[i] / 1000;
    mag[i] = json.mag[i] / 10;
    bv[i] = json.bv[i] == null ? NaN : json.bv[i] / 10;
    const v = toVec(ra[i], dec[i]);
    xyz[i * 3] = v[0]; xyz[i * 3 + 1] = v[1]; xyz[i * 3 + 2] = v[2];
  }
  return { n, xyz, ra, dec, mag, bv };
}

/** Faintest magnitude drawn at a field width (degrees): fewer stars when the whole sky is in view. */
export function magLimit(fov) {
  if (fov >= 200) return 5.0;
  if (fov <= 20) return 6.5;
  return 5.0 + (1.5 * (200 - fov)) / 180;
}

/** Count of stars (from the bright end) no fainter than `limit`; the array is sorted brightest first. */
export function countBrighter(mag, limit) {
  let lo = 0, hi = mag.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (mag[mid] <= limit) lo = mid + 1; else hi = mid;
  }
  return lo;
}

/** Dot radius in CSS pixels: brighter is bigger, and everything grows a little as we zoom in. */
export function starRadius(mag, fov) {
  const boost = fov >= 120 ? 0.85 : 0.85 + (0.75 * Math.log2(120 / fov)) / Math.log2(60);
  return Math.max(0.5, Math.min(6, (0.55 + 0.5 * (6.5 - mag)) * boost));
}

/** A star colour from B-V: blue-white for hot stars, warm for cool ones; ink grey when unknown. */
export function starColour(bv) {
  if (!Number.isFinite(bv)) return '#e9e6df';
  if (bv < 0) return '#c4d4ff';
  if (bv < 0.3) return '#e2e8ff';
  if (bv < 0.6) return '#f4f1e8';
  if (bv < 1.0) return '#ffe7c2';
  if (bv < 1.4) return '#ffd29a';
  return '#ffb98a';
}

/**
 * Nearest item to (x, y) within `radius` pixels.
 * @param {Array<{x: number, y: number}>} points
 * @returns {number} its index, or -1
 */
export function hitTest(points, x, y, radius) {
  let best = -1, bestD = radius * radius;
  for (let i = 0; i < points.length; i++) {
    const p = points[i];
    if (!p) continue;
    const d = (p.x - x) ** 2 + (p.y - y) ** 2;
    if (d <= bestD) { best = i; bestD = d; }
  }
  return best;
}

/** Mean direction of a constellation's line stars, as {ra, dec}, for its label. */
export function labelPosition(stars, lines) {
  let x = 0, y = 0, z = 0;
  const seen = new Set();
  for (const poly of lines) for (const i of poly) {
    if (seen.has(i)) continue;
    seen.add(i);
    x += stars.xyz[i * 3]; y += stars.xyz[i * 3 + 1]; z += stars.xyz[i * 3 + 2];
  }
  const r = Math.hypot(x, y, z);
  if (!r) return null;
  return { ra: ((Math.atan2(y, x) * 180) / Math.PI + 360) % 360, dec: (Math.asin(z / r) * 180) / Math.PI };
}
