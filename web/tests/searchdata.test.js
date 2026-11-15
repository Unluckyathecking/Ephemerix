import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { curveSeries, binText, peakText, peakTotals, range, crossing, brightnessReach, reachText } from '../js/searchdata.js';

const movers = JSON.parse(readFileSync(new URL('../data/movers.json', import.meta.url)));
const planetx = JSON.parse(readFileSync(new URL('../data/planetx-limits.json', import.meta.url)));

test('curve series drops empty bins', () => {
  const s = curveSeries([{ flux_ujy: 30, n: 0, frac: null, ci95: [0, 1] }, { flux_ujy: 60, n: 10, frac: 0.5, ci95: [0.2, 0.8] }]);
  assert.deepEqual(s, { x: [60], y: [0.5], lo: [0.2], hi: [0.8], n: [10] });
});

test('bin and peak text', () => {
  assert.equal(binText({ k: 42, n: 50, ci95: [0.715, 0.917] }), '42/50 (0.71–0.92)');
  assert.equal(binText({ k: 0, n: 0, ci95: [0, 1] }), '–');
  assert.equal(peakText(0, 6.2), '0');
  assert.equal(peakText(3, 9.83), '3 (max 9.8)');
});

test('crossing interpolates and reports the grid edges', () => {
  assert.equal(crossing([200, 300], [18, 20], 19), 250);
  assert.equal(crossing([200, 300], [19.5, 20], 19), '<200');
  assert.equal(crossing([200, 300], [17, 18], 19), '>300');
  assert.equal(reachText({ nom: 425, lo: '<200', hi: '>1500' }), 'about 425 au (under 200 to beyond 1500)');
});

test('committed summary: pooled limits and the documented totals', () => {
  const p = movers.pooled;
  assert.equal(p.limits.flux50_ujy, 68.4);
  assert.equal(p.limits.flux90_ujy, 106.1);
  assert.equal(binText(p.bins[1]), '307/567 (0.50–0.58)');
  assert.deepEqual(peakTotals(movers.fields, ['tno', 'blank']), { fields: 10, real: 17, null: 19 });
  assert.equal(movers.known_bodies.length, 3);
  assert.equal(movers.classifier.passed, false);
  const r = range(movers.fields, (f) => f.motion_limit_au);
  assert.ok(r[0] > 0 && r[1] <= 1000);
});

test('Planet X reach for the measured 50% limit is ordered dark < nominal < bright', () => {
  const rows = brightnessReach(planetx, movers.pooled.limits.ab1um50);
  assert.equal(rows.length, planetx.cases.length);
  const se10 = rows.find((r) => r.key === 'se10');
  assert.ok(typeof se10.nom === 'number' && se10.nom > 300 && se10.nom < 600);
  if (typeof se10.lo === 'number') assert.ok(se10.lo < se10.nom);
  if (typeof se10.hi === 'number') assert.ok(se10.hi > se10.nom);
});
