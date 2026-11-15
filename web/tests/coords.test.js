import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parsePosition, parseOptionalNumber, formatRa, formatDec, CoordError } from '../js/coords.js';

const close = (a, b, eps = 1e-6) => assert.ok(Math.abs(a - b) < eps, `${a} vs ${b}`);

test('decimal degrees', () => {
  const p = parsePosition('133.7836 -7.2445');
  close(p.ra, 133.7836); close(p.dec, -7.2445);
  const q = parsePosition('  10.5, +3 ');
  close(q.ra, 10.5); close(q.dec, 3);
});

test('sexagesimal with spaces, colons and letters agree', () => {
  const expected = { ra: (8 + 55 / 60 + 10.83 / 3600) * 15, dec: -(7 + 14 / 60 + 42.5 / 3600) };
  for (const s of ['08 55 10.83 -07 14 42.5', '08:55:10.83 -07:14:42.5', '08h55m10.83s -07d14m42.5s', "08h55m10.83s -07°14'42.5\""]) {
    const p = parsePosition(s);
    close(p.ra, expected.ra); close(p.dec, expected.dec);
  }
});

test('negative zero declination keeps its sign', () => {
  close(parsePosition('12 00 00 -00 30 00').dec, -0.5);
  close(parsePosition('12 00 -00 30').dec, -0.5);
  close(parsePosition('12 00 00 +00 30 00').dec, 0.5);
});

test('rejects bad input with clear messages', () => {
  const bad = ['', 'abc def', '24 00 00 +10 00 00', '10 60 00 +10 00 00', '10 00 00 +10 00 60',
    '400 10', '10 95', '1 2 3', '10 00 00 +91 00 00', '-01 00 00 +10 00 00'];
  for (const s of bad) assert.throws(() => parsePosition(s), CoordError, s);
});

test('optional numbers', () => {
  assert.equal(parseOptionalNumber('', 'pm'), null);
  assert.equal(parseOptionalNumber(' -812.5 ', 'pm'), -812.5);
  assert.throws(() => parseOptionalNumber('12x', 'pm'), CoordError);
});

test('formatting round-trips and carries seconds', () => {
  assert.equal(formatRa(133.7951292), '08 55 10.83');
  assert.equal(formatDec(-7.2451389), '-07 14 42.5');
  assert.equal(formatDec(-0.5), '-00 30 00.0');
  assert.equal(formatRa(359.99999999), '00 00 00.00');
  assert.equal(formatDec(10 + 59 / 60 + 59.99 / 3600), '+11 00 00.0');
  const p = parsePosition(`${formatRa(201.123456, 3)} ${formatDec(-45.6789, 2)}`);
  close(p.ra, 201.123456, 1e-5); close(p.dec, -45.6789, 1e-5);
});
