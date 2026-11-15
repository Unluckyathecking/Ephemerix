// SVG geometry for the all-sky locator: the map layout and path data for the graticule,
// the Milky Way band and the ecliptic. Pure functions (strings and numbers only).

import { skyToChart, galToEq, eclToEq, HAMMER_HALF_WIDTH, HAMMER_HALF_HEIGHT } from './skymath.js';

export const VIEW_W = 260;
export const VIEW_H = 150;
export const CENTER = { x: 137, y: 76 };
export const HALF_W = 112;
export const SCALE = HALF_W / HAMMER_HALF_WIDTH; // svg units per chart unit
export const HALF_H = HAMMER_HALF_HEIGHT * SCALE;
// A step this wide in chart units is a jump across the map edge, not a line.
const SEAM_JUMP = 1.6;

/** SVG {x, y} of an equatorial position (RA increasing to the left). */
export function toSvg(ra, dec) {
  const c = skyToChart(ra, dec);
  return { x: CENTER.x + SCALE * c.x, y: CENTER.y - SCALE * c.y };
}

const f1 = (n) => (Math.round(n * 10) / 10).toString();

/** Split a sampled curve into runs that do not cross the map edge. */
export function runs(points) {
  const out = [];
  let cur = [];
  let prev = null;
  for (const p of points) {
    const c = skyToChart(p.ra, p.dec);
    if (prev && Math.abs(c.x - prev.x) > SEAM_JUMP) { if (cur.length > 1) out.push(cur); cur = []; }
    cur.push(c);
    prev = c;
  }
  if (cur.length > 1) out.push(cur);
  return out;
}

const svgPoint = (c) => `${f1(CENTER.x + SCALE * c.x)} ${f1(CENTER.y - SCALE * c.y)}`;

/** Path data ("M..L..") for a sampled curve, broken at the map edge. */
export function curveD(points) {
  return runs(points).map((r) => `M${r.map(svgPoint).join('L')}`).join('');
}

const range = (from, to, step) => {
  const out = [];
  for (let v = from; v <= to + 1e-9; v += step) out.push(v);
  return out;
}

/** Curve of constant galactic latitude b, sampled every `step` degrees of longitude. */
export function galacticLatitudeD(b, step = 2) {
  return curveD(range(0, 360, step).map((l) => galToEq(l, b)));
}

/** The ecliptic as a closed-looking curve broken at the map edge. */
export function eclipticD(step = 2) {
  return curveD(range(0, 360, step).map((lon) => eclToEq(lon, 0)));
}

/** Meridians every 4h of RA and parallels every 30 degrees (the equator included). */
export function graticuleD() {
  const parts = [];
  for (let h = 0; h < 24; h += 4) {
    const ra = Math.min(h * 15, 359.999);
    parts.push(curveD(range(-90, 90, 5).map((dec) => ({ ra: ra || 0.001, dec }))));
  }
  for (const dec of [-60, -30, 0, 30, 60]) {
    parts.push(curveD(range(0, 360, 5).map((ra) => ({ ra: Math.min(Math.max(ra, 0.001), 359.999), dec }))));
  }
  return parts.join('');
}

/**
 * The band |b| < halfWidth around the galactic plane, as polygons (one per stretch that does
 * not cross the map edge): the upper edge forward, the lower edge back.
 */
export function galacticBandD(halfWidth, step = 1) {
  const edge = (b) => range(0, 360, step).map((l) => { const p = galToEq(l, b); return skyToChart(p.ra, p.dec); });
  const up = edge(halfWidth), down = edge(-halfWidth);
  const polys = [];
  let from = 0;
  const flush = (to) => {
    if (to - from >= 2) {
      const top = up.slice(from, to).map(svgPoint);
      const bottom = down.slice(from, to).map(svgPoint).reverse();
      polys.push(`M${top.concat(bottom).join('L')}Z`);
    }
  };
  for (let i = 1; i < up.length; i++) {
    if (Math.abs(up[i].x - up[i - 1].x) > SEAM_JUMP || Math.abs(down[i].x - down[i - 1].x) > SEAM_JUMP) { flush(i); from = i; }
  }
  flush(up.length);
  return polys.join('');
}
