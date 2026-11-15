import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { bandSets, defaultBands, resolveBands, activeFrames, handoverYear, nearestIndex, passFrames } from '../js/framesets.js';
import { validateManifest } from '../js/manifest.js';

const m = validateManifest(JSON.parse(readFileSync(new URL('./fixtures/gallery/synthetic-fast-mover/manifest.json', import.meta.url)))).manifest;

test('band sets are ordered WISE first then by wavelength', () => {
  assert.deepEqual(bandSets(m.frames).map((s) => s.band), ['W1', 'W2', 'spx-b1', 'spx-b2', 'spx-b3', 'spx-b4', 'spx-b5', 'spx-b6']);
});

test('default is WISE W2 with the SPHEREx band that holds 4.6 µm', () => {
  assert.deepEqual(defaultBands(m.frames), ['W2', 'spx-b6']);
});

test('URL bands are filtered, with a fallback', () => {
  assert.deepEqual(resolveBands(['W1', 'nope'], m.frames), ['W1']);
  assert.deepEqual(resolveBands(['nope'], m.frames), ['W2', 'spx-b6']);
  assert.deepEqual(resolveBands(null, m.frames), ['W2', 'spx-b6']);
  assert.deepEqual(resolveBands(null, m.frames, 'spherex'), ['spx-b6']);
});

test('active frames and handover', () => {
  const a = activeFrames(m.frames, ['W2']);
  assert.ok(a.length && a.every((f) => f.band === 'W2'));
  const h = handoverYear(m.frames);
  assert.ok(h > 2024.4 && h < 2025.4, String(h));
  assert.equal(handoverYear(a), null);
  assert.equal(nearestIndex(a, a[3].mjd + 10), 3);
});

test('the fixture passes group into three six-band passes', () => {
  const spx = m.frames.filter((f) => f.mission === 'SPHEREx');
  const anchors = [...new Set(spx.map((f) => passFrames(m.frames, f.mjd).map((p) => p.frame.id).join()))];
  assert.equal(anchors.length, 3);
  for (const f of spx) assert.ok(passFrames(m.frames, f.mjd).some((p) => p.frame.id === f.id));
});
