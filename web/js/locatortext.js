// The plain-language lines under the all-sky locator, all computed from RA/Dec and the field size.

import { eqToGal, eqToEcl } from './skymath.js';
import { constellationOf } from './constellation.js';

export const MOON_ARCMIN = 31; // the full Moon is about 31 arcminutes across
const ECLIPTIC_NEAR_DEG = 5;

const signed = (x, digits = 0) => `${x < 0 ? '−' : '+'}${Math.abs(x).toFixed(digits)}°`;
const FRACTIONS = { 2: 'half', 3: 'one third', 4: 'one quarter', 5: 'one fifth', 6: 'one sixth', 7: 'one seventh', 8: 'one eighth', 9: 'one ninth', 10: 'one tenth' };

/** Galactic-latitude wording: the phrase, and whether the field is expected to be crowded. */
export function galacticPhrase(b) {
  const a = Math.abs(b);
  if (a > 30) return { phrase: 'far from the Milky Way', crowded: false };
  if (a < 10) return { phrase: 'close to the Milky Way’s plane, so the field is crowded', crowded: true };
  return { phrase: 'at moderate galactic latitude', crowded: false };
}

/** How the field compares with the full Moon, e.g. "about one eighth the width of the full Moon". */
export function scaleSentence(fovArcsec) {
  const arcmin = fovArcsec / 60;
  const rounded = Math.round(arcmin * 10) / 10;
  const size = Math.abs(arcmin - Math.round(arcmin)) < 0.05 ? Math.round(arcmin) : rounded;
  const head = `This image is ${size} ${size === 1 ? 'arcminute' : 'arcminutes'} across`;
  const ratio = arcmin / MOON_ARCMIN;
  if (ratio >= 1.3) return `${head}, about ${Math.round(ratio * 10) / 10} times the width of the full Moon.`;
  if (ratio > 0.77) return `${head}, about the width of the full Moon.`;
  const part = FRACTIONS[Math.round(1 / ratio)];
  return part ? `${head}, about ${part} the width of the full Moon.` : `${head}, under a tenth the width of the full Moon.`;
}

/**
 * Everything the locator says about a position.
 * @returns {{constellation: {abbr: string, name: string}, gal: {l: number, b: number}, ecl: {lon: number, lat: number},
 *   galactic: {phrase: string, crowded: boolean}, nearEcliptic: boolean, lines: string[], label: string}}
 */
export function describePosition(ra, dec, fovArcsec) {
  const constellation = constellationOf(ra, dec);
  const gal = eqToGal(ra, dec);
  const ecl = eqToEcl(ra, dec);
  const galactic = galacticPhrase(gal.b);
  const nearEcliptic = Math.abs(ecl.lat) <= ECLIPTIC_NEAR_DEG;
  const lines = [];
  if (constellation.name) lines.push(`In the constellation ${constellation.name}.`);
  lines.push(`Galactic latitude ${signed(gal.b, 1)}: ${galactic.phrase}.`);
  if (nearEcliptic) lines.push(`Ecliptic latitude ${signed(ecl.lat, 1)}: near the ecliptic, where planets and asteroids pass.`);
  if (fovArcsec > 0) lines.push(scaleSentence(fovArcsec));
  const where = `RA ${ra.toFixed(1)} degrees, Dec ${signed(dec, 1).replace('°', ' degrees')}`;
  const label = `Map of the whole sky. This view is at ${where}${constellation.name ? `, in ${constellation.name}` : ''}, `
    + `${galactic.phrase}.${nearEcliptic ? ' It is near the ecliptic.' : ''}`;
  return { constellation, gal, ecl, galactic, nearEcliptic, lines, label };
}
