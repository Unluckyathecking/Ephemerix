import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { reachRank, bestReach, reachText, depthLinesFor, caseSeries, fortneySeries } from '../js/planetxdata.js';

const data = JSON.parse(readFileSync(new URL('../data/planetx-limits.json', import.meta.url)));

test('reach strings sort around the grid edges', () => {
  assert.ok(reachRank('<200') < 200);
  assert.ok(reachRank('>1500') > 1500);
  assert.equal(reachRank(375), 375);
});

test('best reach takes the furthest band for each of lo, nom, hi', () => {
  const c = { reach_au: { d: { A: { lo: '<200', nom: 300, hi: 450 }, B: { lo: 225, nom: 275, hi: '>1500' } } } };
  assert.deepEqual(bestReach(c, 'd'), { lo: 225, nom: 300, hi: '>1500' });
  assert.equal(bestReach(c, 'missing'), null);
});

test('reach text', () => {
  assert.equal(reachText({ lo: 225, nom: 350, hi: 550 }), '350 au (225 to 550)');
  assert.equal(reachText({ lo: '<200', nom: '<200', hi: '<200' }), 'under 200 au');
  assert.equal(reachText(null), '–');
});

test('committed table: depth lines per band and series lengths agree', () => {
  const spx = depthLinesFor(data, 'SPHEREx D2');
  assert.ok(spx.some((d) => d.key === 'spx_one_map_channel' && d.shallow < d.deep));
  assert.ok(!spx.some((d) => d.key === 'wise'));
  assert.deepEqual(depthLinesFor(data, 'WISE W1').map((d) => d.key), ['wise']);
  const s = caseSeries(data, data.cases[0], 'SPHEREx D1');
  assert.equal(s.nom.length, s.x.length);
  assert.ok(s.hi[0] <= s.nom[0] && s.nom[0] <= s.lo[0]); // brighter = smaller magnitude
  assert.equal(fortneySeries(data, 'SPHEREx D1'), null);
  assert.equal(fortneySeries(data, 'WISE W2').bright.length, s.x.length);
});
