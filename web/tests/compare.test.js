import { test } from 'node:test';
import assert from 'node:assert/strict';
import { combinePixels, compareAllowed, defaultPair } from '../js/compare.js';

// Grey RGBA pixels from a list of values.
const px = (...v) => Uint8ClampedArray.from(v.flatMap((x) => [x, x, x, 255]));
const grey = (arr) => [...arr].filter((_, i) => i % 4 === 0);

test('difference: fixed stars cancel to mid-grey, a mover is a dark/bright pair', () => {
  const a = px(10, 200, 10, 90);   // index 1: a fixed star; index 3: the mover in A
  const b = px(10, 200, 90, 10);   // the star unchanged; the mover now at index 2
  const d = grey(combinePixels(a, b, 'diff'));
  assert.equal(d[0], 128);          // background: unchanged
  assert.equal(d[1], 128);          // fixed star cancels
  assert.ok(d[2] > 128);            // where it went: bright
  assert.ok(d[3] < 128);            // where it was: dark
  assert.deepEqual(d, [128, 128, 168, 88]);
});

test('difference stays in range at the extremes', () => {
  assert.deepEqual(grey(combinePixels(px(0, 255), px(255, 0), 'diff')), [255, 1]);
});

test('sum is the mean, so it never clips', () => {
  assert.deepEqual(grey(combinePixels(px(255, 0, 100), px(255, 0, 51), 'sum')), [255, 0, 76]);
  const out = combinePixels(px(1), px(3), 'sum');
  assert.deepEqual([...out], [2, 2, 2, 255]);
});

test('mismatched arrays are refused', () => {
  assert.throws(() => combinePixels(px(1, 2), px(1), 'diff'), RangeError);
});

const f = (id, band, mission = 'SPHEREx', wl = [4.42, 5.0]) => ({ id, band, mission, wavelength_um: wl });

test('only frames of one set can be combined, with a reason otherwise', () => {
  assert.deepEqual(compareAllowed(f('a', 'spx-b6'), f('b', 'spx-b6')), { ok: true, reason: null });
  const cross = compareAllowed(f('a', 'W2', 'WISE', [4, 5.2]), f('b', 'spx-b6'));
  assert.equal(cross.ok, false);
  assert.match(cross.reason, /WISE W2 \(4\.6 µm\) and B is SPHEREx 4\.42–5\.0 µm/);
  assert.match(cross.reason, /stretch/);
  assert.match(compareAllowed(f('a', 'x'), f('a', 'x')).reason, /same frame/);
  assert.equal(compareAllowed(null, f('a', 'x')).ok, false);
});

test('default pair is the first and last frame of the set', () => {
  const frames = [f('1', 'W2'), f('2', 'spx-b6'), f('3', 'W2'), f('4', 'W2')];
  assert.deepEqual(defaultPair(frames, 'W2').map((x) => x.id), ['1', '4']);
  assert.equal(defaultPair(frames, 'spx-b6'), null);
});
