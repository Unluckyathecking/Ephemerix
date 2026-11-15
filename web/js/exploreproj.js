// View maths for the sky map on explore.html. The sphere is turned so the view centre sits at
// longitude 0, latitude 0, then drawn with the site's Hammer-Aitoff projection (skymath.js): close to
// undistorted near the middle of the screen, and the whole sky fits as one ellipse when zoomed out.
// North is up and RA increases to the left, as on a sky chart. Pure functions, degrees in and out.

import { hammer, hammerInverse, HAMMER_HALF_WIDTH, HAMMER_HALF_HEIGHT } from './skymath.js';

const RAD = Math.PI / 180;
const norm360 = (x) => ((x % 360) + 360) % 360;
const clampDec = (d) => Math.max(-90, Math.min(90, d));

export const MIN_FOV = 2; // degrees across the canvas at the closest zoom
const FIT = 0.94; // the whole-sky ellipse fills this share of the canvas

/** Unit vector [x, y, z] of an equatorial position. */
export function toVec(ra, dec) {
  const a = ra * RAD, d = dec * RAD;
  return [Math.cos(d) * Math.cos(a), Math.cos(d) * Math.sin(a), Math.sin(d)];
}

/** Great-circle separation in degrees. */
export function angularSep(ra1, dec1, ra2, dec2) {
  const a = toVec(ra1, dec1), b = toVec(ra2, dec2);
  const cross = Math.hypot(a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]);
  return Math.atan2(cross, a[0] * b[0] + a[1] * b[1] + a[2] * b[2]) / RAD;
}

/** The widest field (degrees across the canvas width) at which the whole sky still fits. */
export function maxFov(width, height) {
  const k = Math.min((FIT * width) / (2 * HAMMER_HALF_WIDTH), (FIT * height) / (2 * HAMMER_HALF_HEIGHT));
  return width / k / RAD;
}

/**
 * A view: centre (ra, dec), field width `fov` in degrees and the canvas size in CSS pixels.
 * Adds the rotation matrix and the scale (pixels per radian near the centre).
 */
export function makeView({ ra, dec, fov, width, height }) {
  const a = ra * RAD, d = dec * RAD;
  const ca = Math.cos(a), sa = Math.sin(a), cd = Math.cos(d), sd = Math.sin(d);
  // Rz(-ra) then Ry(dec): the centre goes to (1, 0, 0).
  const m = [cd * ca, cd * sa, sd, -sa, ca, 0, -sd * ca, -sd * sa, cd];
  return { ra: norm360(ra), dec: clampDec(dec), fov, width, height, m, k: width / (fov * RAD), cx: width / 2, cy: height / 2 };
}

/** Rotated longitude and latitude (degrees) of a unit vector: 0, 0 is the view centre. */
export function local(view, v) {
  const m = view.m;
  const x = m[0] * v[0] + m[1] * v[1] + m[2] * v[2];
  const y = m[3] * v[0] + m[4] * v[1] + m[5] * v[2];
  const z = m[6] * v[0] + m[7] * v[1] + m[8] * v[2];
  return { lon: Math.atan2(y, x) / RAD, lat: Math.asin(Math.max(-1, Math.min(1, z))) / RAD, cos: x };
}

/** Screen {x, y} of a unit vector, with `lon` (for seam checks) and `cos` (cosine of the distance from the centre). */
export function project(view, v) {
  const l = local(view, v);
  const h = hammer(l.lon, l.lat);
  return { x: view.cx - view.k * h.x, y: view.cy - view.k * h.y, lon: l.lon, cos: l.cos };
}

/** Sky position {ra, dec} under a screen point, or null off the sky. */
export function unproject(view, sx, sy) {
  const h = hammerInverse(-(sx - view.cx) / view.k, -(sy - view.cy) / view.k);
  if (!h) return null;
  const l = toVec(h.lon, h.lat);
  const m = view.m; // inverse rotation is the transpose
  const x = m[0] * l[0] + m[3] * l[1] + m[6] * l[2];
  const y = m[1] * l[0] + m[4] * l[1] + m[7] * l[2];
  const z = m[2] * l[0] + m[5] * l[1] + m[8] * l[2];
  return { ra: norm360(Math.atan2(y, x) / RAD), dec: Math.asin(Math.max(-1, Math.min(1, z))) / RAD };
}

/** True when a line between two rotated longitudes would jump across the hidden back of the sphere. */
export function crossesSeam(lonA, lonB) {
  return Math.abs(lonA - lonB) > 180;
}

/** New centre after dragging the sky by (dx, dy) screen pixels. RA wraps; Dec stops at the poles. */
export function pan(view, dx, dy) {
  const deg = 1 / (view.k * RAD);
  const cos = Math.max(Math.cos(view.dec * RAD), 0.2);
  return { ra: norm360(view.ra + (dx * deg) / cos), dec: clampDec(view.dec + dy * deg), fov: view.fov };
}

const clampFov = (fov, view) => Math.max(MIN_FOV, Math.min(maxFov(view.width, view.height), fov));

/** Centre and field after zooming by `factor` (2 = twice as close), keeping the sky under (sx, sy) in place. */
export function zoomAt(view, factor, sx, sy) {
  const fov = clampFov(view.fov / factor, view);
  const target = unproject(view, sx, sy);
  let next = { ra: view.ra, dec: view.dec, fov };
  if (!target) return next;
  for (let i = 0; i < 3; i++) {
    const v = makeView({ ...next, width: view.width, height: view.height });
    const p = project(v, toVec(target.ra, target.dec));
    if (Math.abs(p.lon) > 90) break;
    next = pan(v, sx - p.x, sy - p.y);
  }
  return next;
}

/** Clamp a requested field to what this canvas allows. */
export function fitFov(fov, width, height) {
  return Math.max(MIN_FOV, Math.min(maxFov(width, height), fov));
}
