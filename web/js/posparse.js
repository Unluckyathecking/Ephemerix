// Read a typed sky position in any common format and say plainly what we understood.
// Wraps coords.parsePosition; adds labels ("RA 133.7 Dec -7.2"), units ("deg"), and the compact
// "J085510.83-071442.5". Pure.

import { parsePosition, formatRa, formatDec, CoordError } from './coords.js';

const COMPACT = /^j?(\d{2})(\d{2})(\d{2}(?:\.\d+)?)([+-])(\d{2})(\d{2})(\d{2}(?:\.\d+)?)$/i;

/** Text with labels and spelled-out units removed; null when what is left is not numbers and unit marks. */
function clean(text) {
  const t = String(text ?? '').trim();
  if (!t) return null;
  const c = t.replace(/\s+/g, '').match(COMPACT);
  if (c) return { text: `${c[1]} ${c[2]} ${c[3]} ${c[4]}${c[5]} ${c[6]} ${c[7]}`, compact: true };
  const s = t.replace(/\b(right\s+ascension|declination|r\.?a\.?|decl?\.?)\s*[:=]?/gi, ' ').replace(/(\d)\s*deg(rees)?\b/gi, '$1°');
  // Only numbers, signs, separators and h/m/s/d unit marks may remain.
  if (!/^[\d\s.,;:+\-hmsd°'"′″]+$/i.test(s)) return null;
  if (!/\d/.test(s) || /[a-z]{2}/i.test(s.replace(/\d\s*[hmsd]/gi, ''))) return null;
  return { text: s, compact: false };
}

/**
 * @param {string} text
 * @returns {null | {ok: true, ra: number, dec: number, said: string} | {ok: false, message: string}}
 *   null when the text does not look like a position (treat it as a name)
 */
export function readPosition(text) {
  const c = clean(text);
  if (!c) return null;
  let p;
  try {
    p = parsePosition(c.text);
  } catch (err) {
    return { ok: false, message: err instanceof CoordError ? err.message : 'That position could not be read.' };
  }
  const decimal = !c.compact && c.text.replace(/[hdms°'"′″:,;]/gi, ' ').trim().split(/\s+/).length === 2;
  const sexa = `${formatRa(p.ra)}, ${formatDec(p.dec)}`;
  const deg = `RA ${p.ra.toFixed(5)}°, Dec ${p.dec.toFixed(5)}°`;
  const said = decimal
    ? `We read this as ${deg} (decimal degrees), which is ${sexa}.`
    : `We read this as RA ${formatRa(p.ra)} (hours), Dec ${formatDec(p.dec)} (degrees), which is ${deg}.`;
  return { ok: true, ra: p.ra, dec: p.dec, said };
}
