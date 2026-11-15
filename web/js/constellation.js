// Which IAU constellation a J2000 position lies in: precess to B1875.0, then look it up in the
// Roman (1987) table of the Delporte boundaries (constellation-data.js).

import { ROMAN_ROWS, CONSTELLATION_NAMES } from './constellation-data.js';

const RAD = Math.PI / 180;
const ARCSEC = RAD / 3600;

// B1875.0 is JD 2405889.25855 (Besselian epoch); J2000.0 is JD 2451545.0.
const T_B1875 = (2405889.25855 - 2451545.0) / 36525;

/**
 * Precess an equatorial position from J2000.0 to the mean equinox of B1875.0.
 * IAU 1976 precession angles (Lieske 1977) with the rigorous formulas of Meeus,
 * Astronomical Algorithms, 2nd ed., ch. 21. Returns RA in degrees [0, 360) and Dec in degrees.
 */
export function precessToB1875(ra, dec) {
  const t = T_B1875;
  const zeta = (2306.2181 * t + 0.30188 * t * t + 0.017998 * t ** 3) * ARCSEC;
  const z = (2306.2181 * t + 1.09468 * t * t + 0.018203 * t ** 3) * ARCSEC;
  const theta = (2004.3109 * t - 0.42665 * t * t - 0.041833 * t ** 3) * ARCSEC;
  const a = ra * RAD, d = dec * RAD;
  const A = Math.cos(d) * Math.sin(a + zeta);
  const B = Math.cos(theta) * Math.cos(d) * Math.cos(a + zeta) - Math.sin(theta) * Math.sin(d);
  const C = Math.sin(theta) * Math.cos(d) * Math.cos(a + zeta) + Math.cos(theta) * Math.sin(d);
  const ra1 = Math.atan2(A, B) + z;
  return { ra: (((ra1 / RAD) % 360) + 360) % 360, dec: Math.asin(Math.max(-1, Math.min(1, C))) / RAD };
}

/**
 * The constellation containing a J2000 position.
 * @returns {{abbr: string, name: string}}
 */
export function constellationOf(ra, dec) {
  const p = precessToB1875(ra, dec);
  const hours = p.ra / 15;
  for (const [lo, hi, decLow, abbr] of ROMAN_ROWS) {
    if (hours >= lo && hours < hi && p.dec >= decLow) return { abbr, name: CONSTELLATION_NAMES[abbr] };
  }
  // The table covers the whole sphere; this only guards against NaN input.
  return { abbr: '', name: '' };
}
