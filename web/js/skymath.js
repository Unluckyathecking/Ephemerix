// Coordinate maths for the all-sky locator. Pure functions, degrees in and out.
// Frames: equatorial J2000 (ICRS to well under an arcsecond), galactic, and ecliptic of J2000.

const RAD = Math.PI / 180;
const norm360 = (x) => ((x % 360) + 360) % 360;
const clamp1 = (x) => Math.max(-1, Math.min(1, x));

// Galactic frame, defined in J2000 equatorial coordinates by the north galactic pole and the
// galactic longitude of the north celestial pole. Values as adopted for Hipparcos
// (ESA 1997, The Hipparcos and Tycho Catalogues, vol. 1, section 1.5.3) and used by astropy:
// pole at RA 192.85948, Dec +27.12825; l of the north celestial pole 122.93192.
export const GAL_POLE_RA = 192.85948;
export const GAL_POLE_DEC = 27.12825;
export const GAL_NCP_L = 122.93192;

// Mean obliquity of the ecliptic at J2000: 23.4393 degrees (IAU 2006: 84381.406 arcsec).
export const OBLIQUITY = 23.4393;

/** Galactic {l, b} of an equatorial J2000 position. */
export function eqToGal(ra, dec) {
  const d = dec * RAD, dp = GAL_POLE_DEC * RAD, da = (ra - GAL_POLE_RA) * RAD;
  const b = Math.asin(clamp1(Math.sin(d) * Math.sin(dp) + Math.cos(d) * Math.cos(dp) * Math.cos(da)));
  const y = Math.cos(d) * Math.sin(da);
  const x = Math.sin(d) * Math.cos(dp) - Math.cos(d) * Math.sin(dp) * Math.cos(da);
  return { l: norm360(GAL_NCP_L - Math.atan2(y, x) / RAD), b: b / RAD };
}

/** Equatorial J2000 {ra, dec} of a galactic position. */
export function galToEq(l, b) {
  const bb = b * RAD, dp = GAL_POLE_DEC * RAD, dl = (GAL_NCP_L - l) * RAD;
  const dec = Math.asin(clamp1(Math.sin(bb) * Math.sin(dp) + Math.cos(bb) * Math.cos(dp) * Math.cos(dl)));
  const y = Math.cos(bb) * Math.sin(dl);
  const x = Math.sin(bb) * Math.cos(dp) - Math.cos(bb) * Math.sin(dp) * Math.cos(dl);
  return { ra: norm360(GAL_POLE_RA + Math.atan2(y, x) / RAD), dec: dec / RAD };
}

/** Ecliptic {lon, lat} (J2000 mean ecliptic) of an equatorial J2000 position. */
export function eqToEcl(ra, dec) {
  const a = ra * RAD, d = dec * RAD, e = OBLIQUITY * RAD;
  const lat = Math.asin(clamp1(Math.sin(d) * Math.cos(e) - Math.cos(d) * Math.sin(e) * Math.sin(a)));
  const lon = Math.atan2(Math.sin(a) * Math.cos(d) * Math.cos(e) + Math.sin(d) * Math.sin(e), Math.cos(a) * Math.cos(d));
  return { lon: norm360(lon / RAD), lat: lat / RAD };
}

/** Equatorial J2000 {ra, dec} of an ecliptic position. */
export function eclToEq(lon, lat) {
  const a = lon * RAD, b = lat * RAD, e = OBLIQUITY * RAD;
  const dec = Math.asin(clamp1(Math.sin(b) * Math.cos(e) + Math.cos(b) * Math.sin(e) * Math.sin(a)));
  const ra = Math.atan2(Math.sin(a) * Math.cos(b) * Math.cos(e) - Math.sin(b) * Math.sin(e), Math.cos(a) * Math.cos(b));
  return { ra: norm360(ra / RAD), dec: dec / RAD };
}

// Hammer-Aitoff equal-area projection (closed form both ways). Unit-free output with
// x in [-2*sqrt(2), 2*sqrt(2)] and y in [-sqrt(2), sqrt(2)].
export const HAMMER_HALF_WIDTH = 2 * Math.SQRT2;
export const HAMMER_HALF_HEIGHT = Math.SQRT2;

/** Hammer-Aitoff {x, y} for a longitude in (-180, 180] and a latitude, both degrees. */
export function hammer(lon, lat) {
  const l = lon * RAD, p = lat * RAD;
  const den = Math.sqrt(1 + Math.cos(p) * Math.cos(l / 2));
  return { x: (2 * Math.SQRT2 * Math.cos(p) * Math.sin(l / 2)) / den, y: (Math.SQRT2 * Math.sin(p)) / den };
}

/** Inverse of `hammer`; null outside the ellipse. */
export function hammerInverse(x, y) {
  if ((x / HAMMER_HALF_WIDTH) ** 2 + (y / HAMMER_HALF_HEIGHT) ** 2 > 1) return null;
  const q = (x / 4) ** 2 + (y / 2) ** 2;
  const z = Math.sqrt(1 - q);
  return { lon: (2 * Math.atan2(z * x, 2 * (2 * z * z - 1))) / RAD, lat: Math.asin(clamp1(z * y)) / RAD };
}

/**
 * Chart position of an equatorial position: Hammer-Aitoff centred on RA 12h, with RA
 * increasing to the left as on a sky chart. Same units as `hammer`.
 */
export function skyToChart(ra, dec) {
  const lon = norm360(ra) - 180;
  const h = hammer(lon, dec);
  return { x: -h.x, y: h.y };
}

/** Inverse of `skyToChart` (north is +y); null outside the map. */
export function chartToSky(x, y) {
  const h = hammerInverse(-x, y);
  return h && { ra: norm360(h.lon + 180), dec: h.lat };
}
