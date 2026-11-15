import { test } from 'node:test';
import assert from 'node:assert/strict';
import { findGaps, gapLabel, gapCue } from '../js/gaps.js';

const mjd = (y) => 51544.5 + (y - 2000) * 365.25;
const fr = (ys) => ys.map((y, i) => ({ id: `f${i}`, mjd: mjd(y) }));

// UGPS 0722-like: WISE 2010 only, then SPHEREx 2025-26.
const ugps = fr([2010.27, 2010.77, 2025.4, 2025.5, 2026.1]);
// Barnard-like: 2010, hibernation, then half-yearly 2014-2024, SPHEREx 2025-26.
const full = fr([2010.2, 2010.7, ...Array.from({ length: 22 }, (_, i) => 2014.2 + i * 0.5), 2025.4, 2025.9, 2026.3]);

test('a 15 year hole is found and labelled with the whole years inside it', () => {
  const g = findGaps(ugps);
  assert.equal(g.length, 1);
  assert.equal(gapLabel(g[0]), 'no images 2011–2025');
  assert.ok(g[0].years > 14.5);
});

test('the 2011-2013 WISE hibernation counts as a gap, ordinary half-year spacing does not', () => {
  const g = findGaps(full);
  assert.equal(g.length, 1);
  assert.equal(gapLabel(g[0]), 'no images 2011–2014');
});

test('a short sequence with even spacing has no gap', () => {
  assert.deepEqual(findGaps(fr([2025.3, 2025.5, 2025.9, 2026.2])), []);
  assert.deepEqual(findGaps([]), []);
});

test('stepping across a gap gives a cue, in either direction; within a stretch it does not', () => {
  const g = findGaps(ugps);
  assert.equal(gapCue(ugps[1], ugps[2], g), '15 years later');
  assert.equal(gapCue(ugps[2], ugps[1], g), '15 years earlier');
  assert.equal(gapCue(ugps[0], ugps[1], g), null);
  assert.equal(gapCue(ugps[2], ugps[3], g), null);
  assert.equal(gapCue(ugps[4], ugps[0], g), '16 years earlier');
  assert.equal(gapCue(null, ugps[0], g), null);
});
