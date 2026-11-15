import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { rejectedSummary } from '../js/rejected.js';
import { validateManifest } from '../js/manifest.js';

const load = (path) => validateManifest(JSON.parse(readFileSync(new URL(path, import.meta.url)))).manifest;
const fixture = (slug) => load(`./fixtures/gallery/${slug}/manifest.json`);
const real = (slug) => load(`../gallery/${slug}/manifest.json`);

test('fast mover: worst-flagged frames first, misses grouped by set, reasons counted', () => {
  const r = rejectedSummary(fixture('synthetic-fast-mover'));
  assert.ok(r.flagged.length >= 2);
  assert.ok(r.flagged[0].frame.flag_fraction >= r.flagged[1].frame.flag_fraction);
  assert.match(r.flagged[0].text, /18% of pixels dropped$/);
  assert.match(r.flaggedNote, /lost 10% or more/);
  assert.match(r.missedNote, /not found in 10 of 44 frames/);
  assert.ok(r.reasons.some((x) => /^Saturated star nearby: \d+ frames?\.$/.test(x.text)));
  // Frame ids never reach the text (they hold raw band ids).
  const all = JSON.stringify([r.flagged, r.missed].flat().map((x) => x.text)) + r.missedNote + r.flaggedNote;
  assert.doesNotMatch(all, /spx-b|wise-w/);
});

test('routine notes and small shares are called routine', () => {
  const r = rejectedSummary(real('2mass-0415-0935'));
  assert.match(r.flaggedNote, /routine/);
  assert.ok(r.reasons.every((x) => !/frame quality unknown|registered to/i.test(x.text)));
});

test('the pipeline\'s own per-frame reason is surfaced', () => {
  const r = rejectedSummary(real('wise-0855-0714'));
  assert.ok(r.reasons.some((x) => x.text === 'Nearest source is a catalogued star, not the target: 20 frames.'), r.reasons);
  // Band ids inside the pipeline's notes are named as the page names them.
  assert.ok(r.reasons.some((x) => /disagrees with SPHEREx 4\.42–5\.0 µm at the same epoch/.test(x.text)), r.reasons);
  assert.ok(r.reasons.every((x) => !/spx-b/.test(x.text)));
});

test('a Solar System body is never "not found"; a clean view gives null', () => {
  assert.equal(rejectedSummary(real('haumea')).missed.length, 0);
  const clean = { frames: [{ date: '2025-01-01T00:00:00Z', mission: 'WISE', band: 'W2', wavelength_um: [4, 5.2], flag_fraction: 0, centroid_px: [1, 1], warnings: [] }] };
  assert.equal(rejectedSummary(clean), null);
});
