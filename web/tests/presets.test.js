import { test } from 'node:test';
import assert from 'node:assert/strict';
import { presetBands, defaultBands, matchPreset, resolveBands, passFrames, PRESETS } from '../js/framesets.js';

const SPX = [[0.75, 1.1], [1.1, 1.65], [1.65, 2.42], [2.42, 3.82], [3.82, 4.42], [4.42, 5.0]];
let n = 0;
const frame = (mission, band, wl, mjd, centroid = true) =>
  ({ id: `f${n++}`, mission, band, wavelength_um: wl, mjd, centroid_px: centroid ? [1, 1] : null });

// Two WISE bands at two dates, six SPHEREx bands in two passes a few days apart inside each.
const both = [
  frame('WISE', 'W1', [2.8, 3.8], 55300), frame('WISE', 'W2', [4.0, 5.2], 55300),
  frame('WISE', 'W1', [2.8, 3.8], 60000), frame('WISE', 'W2', [4.0, 5.2], 60000),
  ...SPX.map((w, i) => frame('SPHEREx', `spx-b${i + 1}`, w, 60800 + i)),
  ...SPX.map((w, i) => frame('SPHEREx', `spx-b${i + 1}`, w, 60990 - i, i !== 2)),
].sort((a, b) => a.mjd - b.mjd);
const spxOnly = both.filter((f) => f.mission === 'SPHEREx');
const wiseOnly = both.filter((f) => f.mission === 'WISE');

test('presets pick the 4.6 µm pair, SPHEREx alone, all SPHEREx, everything', () => {
  assert.deepEqual(presetBands(both, 'wise-spherex'), ['W2', 'spx-b6']);
  assert.deepEqual(presetBands(both, 'spherex'), ['spx-b6']);
  assert.deepEqual(presetBands(both, 'spherex-all'), ['spx-b1', 'spx-b2', 'spx-b3', 'spx-b4', 'spx-b5', 'spx-b6']);
  assert.equal(presetBands(both, 'all').length, 8);
  assert.deepEqual(presetBands(both, 'nope'), []);
  assert.deepEqual(PRESETS.map((p) => p.id), ['wise-spherex', 'spherex', 'spherex-all', 'all']);
});

test('default is WISE + SPHEREx at 4.6 µm when both exist, else what there is', () => {
  assert.deepEqual(defaultBands(both), ['W2', 'spx-b6']);
  assert.deepEqual(defaultBands(spxOnly), ['spx-b6']);
  assert.deepEqual(defaultBands(wiseOnly), ['W2']);
  assert.deepEqual(presetBands(wiseOnly, 'spherex'), []);
});

test('SPHEREx only is one click from the default: it drops WISE and nothing else', () => {
  const d = defaultBands(both), s = presetBands(both, 'spherex');
  assert.deepEqual(d.filter((b) => !b.startsWith('W')), s);
});

test('a band list is recognised as a preset', () => {
  assert.equal(matchPreset(both, ['spx-b6', 'W2']), 'wise-spherex');
  assert.equal(matchPreset(both, ['spx-b6']), 'spherex');
  assert.equal(matchPreset(both, ['W1']), null);
});

test('explicit bands beat the preset, which beats the default', () => {
  assert.deepEqual(resolveBands(['W1'], both, 'spherex'), ['W1']);
  assert.deepEqual(resolveBands(null, both, 'spherex'), ['spx-b6']);
  assert.deepEqual(resolveBands(['nope'], both, 'spherex-all').length, 6);
  assert.deepEqual(resolveBands(null, both, 'bogus'), ['W2', 'spx-b6']);
  assert.deepEqual(resolveBands(null, wiseOnly, 'spherex'), ['W2']);
});

test('pass grouping clusters frames a few days apart and follows the nearest pass', () => {
  const first = passFrames(both, 55300);           // a WISE date: nearest pass is the first one
  assert.equal(first.length, 6);
  assert.ok(first.every((p) => p.frame && p.frame.mjd < 60900));
  const second = passFrames(both, 60995);
  assert.ok(second.every((p) => p.frame && p.frame.mjd > 60900));
  assert.deepEqual(second.map((p) => p.set.band), ['spx-b1', 'spx-b2', 'spx-b3', 'spx-b4', 'spx-b5', 'spx-b6']);
  const gappy = both.filter((f) => !(f.band === 'spx-b4' && f.mjd > 60900));
  assert.equal(passFrames(gappy, 60995).find((p) => p.set.band === 'spx-b4').frame, null);
  assert.deepEqual(passFrames(wiseOnly, 55300), []);
});
