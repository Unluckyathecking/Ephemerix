// Parse and format sky positions. Accepts decimal degrees ("133.78 -7.24")
// or sexagesimal RA in hours and Dec in degrees ("08 55 10.83 -07 14 42.5",
// "08:55:10.83 -07:14:42.5", "08h55m10.83s -07d14m42.5s").

export class CoordError extends Error {}

const NUM = /^[+-]?(\d+(\.\d*)?|\.\d+)$/;

function tokens(text) {
  return text
    .trim()
    .replace(/[,;]/g, ' ')
    .replace(/[hdms°'"′″:]/gi, ' ')
    .split(/\s+/)
    .filter(Boolean);
}

function checkNumbers(parts) {
  for (const p of parts) {
    if (!NUM.test(p)) throw new CoordError(`"${p}" is not a number.`);
  }
}

function sexagesimal(parts, label, max) {
  const [a, b = '0', c = '0'] = parts;
  const sign = a.trim().startsWith('-') ? -1 : 1;
  const whole = Math.abs(parseFloat(a));
  const min = parseFloat(b), sec = parseFloat(c);
  if (min >= 60 || sec >= 60) throw new CoordError(`${label}: minutes and seconds must be below 60.`);
  if (b.startsWith('-') || c.startsWith('-')) throw new CoordError(`${label}: only the first part may carry a sign.`);
  const v = sign * (whole + min / 60 + sec / 3600);
  if (Math.abs(v) > max) throw new CoordError(`${label} is out of range.`);
  return v;
}

/**
 * Parse a position string. Returns {ra, dec} in degrees or throws CoordError
 * with a message fit for the user.
 * @param {string} text
 */
export function parsePosition(text) {
  if (typeof text !== 'string' || !text.trim()) throw new CoordError('Enter a position, for example 133.7836 -7.2445.');
  const parts = tokens(text);
  checkNumbers(parts);
  let ra, dec;
  if (parts.length === 2) {
    ra = parseFloat(parts[0]);
    dec = parseFloat(parts[1]);
  } else if (parts.length === 4 || parts.length === 6) {
    const half = parts.length / 2;
    if (parts[0].startsWith('-')) throw new CoordError('RA cannot be negative.');
    const hours = sexagesimal(parts.slice(0, half), 'RA', 24);
    if (hours >= 24) throw new CoordError('RA hours must be below 24.');
    ra = hours * 15;
    dec = sexagesimal(parts.slice(half), 'Dec', 90);
  } else {
    throw new CoordError('Give RA and Dec as two decimal numbers in degrees, or as h m s and d m s.');
  }
  if (!(ra >= 0 && ra < 360)) throw new CoordError('RA must be between 0 and 360 degrees.');
  if (!(dec >= -90 && dec <= 90)) throw new CoordError('Dec must be between -90 and +90 degrees.');
  return { ra, dec };
}

/** Parse an optional number field; empty means null. Throws CoordError on junk. */
export function parseOptionalNumber(text, label) {
  if (text == null || String(text).trim() === '') return null;
  const s = String(text).trim();
  if (!NUM.test(s)) throw new CoordError(`${label} must be a number.`);
  return parseFloat(s);
}

function pad(n, width, digits) {
  const s = n.toFixed(digits);
  const [i, f] = s.split('.');
  return i.padStart(width, '0') + (f ? '.' + f : '');
}

function split(value, digits) {
  // Round once at the smallest unit so 59.995 s carries into minutes.
  const unit = 10 ** digits;
  let total = Math.round(Math.abs(value) * 3600 * unit);
  const sec = (total % (60 * unit)) / unit;
  total = Math.floor(total / (60 * unit));
  return [Math.floor(total / 60), total % 60, sec];
}

/** "08 55 10.83" style RA. */
export function formatRa(raDeg, digits = 2) {
  const [h, m, s] = split(raDeg / 15, digits);
  return `${pad(h % 24, 2, 0)} ${pad(m, 2, 0)} ${pad(s, 2, digits)}`;
}

/** "-07 14 42.5" style Dec. */
export function formatDec(decDeg, digits = 1) {
  const [d, m, s] = split(decDeg, digits);
  const sign = decDeg < 0 && (d || m || s) ? '-' : '+';
  return `${sign}${pad(d, 2, 0)} ${pad(m, 2, 0)} ${pad(s, 2, digits)}`;
}
