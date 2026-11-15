import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readPosition } from '../js/posparse.js';

const near = (a, b, tol = 1e-4) => assert.ok(Math.abs(a - b) < tol, `${a} vs ${b}`);

test('decimal degrees, with or without units and labels', () => {
  for (const t of ['133.7839 -7.2443', '133.7839, -7.2443', '133.7839° -7.2443°', '133.7839d -7.2443d',
    'RA 133.7839 Dec -7.2443', 'ra=133.7839 dec=-7.2443', '133.7839deg -7.2443deg']) {
    const r = readPosition(t);
    assert.equal(r?.ok, true, t);
    near(r.ra, 133.7839);
    near(r.dec, -7.2443);
    assert.match(r.said, /decimal degrees/, t);
  }
});

test('sexagesimal in the usual spellings', () => {
  for (const t of ['08 55 10.83 -07 14 42.5', '08:55:10.83 -07:14:42.5', '08h55m10.83s -07d14m42.5s',
    '08h 55m 10.83s, -07° 14′ 42.5″', 'J085510.83-071442.5', 'RA 08 55 10.83 Dec -07 14 42.5']) {
    const r = readPosition(t);
    assert.equal(r?.ok, true, t);
    near(r.ra, 133.795125);
    near(r.dec, -7.245139);
    assert.match(r.said, /hours/, t);
  }
});

test("the challenge brief's own text for WISE 0855 reads, however it is pasted", () => {
  for (const t of ['Right Ascension 08h55m10.831s, declination -7d14m42.53s', '08h55m10.831s, -7d14m42.53s',
    '08h55m10.831s -7d14m42.53s', '08 55 10.831 -07 14 42.53', '133.7951 -7.2451']) {
    const r = readPosition(t);
    assert.equal(r?.ok, true, t);
    near(r.ra, 133.7951, 2e-4);
    near(r.dec, -7.2451, 2e-4);
  }
});

test('says plainly what was understood', () => {
  const r = readPosition('133.78 -7.24');
  assert.match(r.said, /^We read this as RA 133\.78000°, Dec -7\.24000° \(decimal degrees\), which is 08 55 07\.20, -07 14 24\.0\.$/);
});

test('names are not positions', () => {
  for (const t of ['Barnard', 'WISE 0855-0714', '2MASS J0415', 'HD 209100', 'eps Ind', 'J0855-0714']) {
    assert.equal(readPosition(t), null, t);
  }
});

test('position-like text that is wrong explains why', () => {
  const r = readPosition('400 10');
  assert.equal(r.ok, false);
  assert.match(r.message, /RA/);
  assert.equal(readPosition('25 00 00 +10 00 00').ok, false);
  assert.equal(readPosition(''), null);
});
