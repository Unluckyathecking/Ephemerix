import { test } from 'node:test';
import assert from 'node:assert/strict';
import { vettingRows, vettingLines } from '../js/vetting.js';
import { validateManifest } from '../js/manifest.js';

const base = { schema: 1, center: { ra: 1, dec: 1 }, size_px: 10, fov_arcsec: 10,
  frames: [{ id: 'a', mission: 'WISE', band: 'W2', image: 'a.png', mjd: 55000 }] };

test('both numbers with plain explanations', () => {
  const rows = vettingRows({ w1_mag: 17.9, w2_mag: 14.6, w1_w2: 3.3, reduced_pm_w2: 22.1, catalogue: 'CatWISE2020' });
  assert.deepEqual(rows.map((r) => r.key), ['w1w2', 'hw2', 'mags']);
  assert.equal(rows[0].value, '3.30 mag, from CatWISE2020');
  assert.match(rows[0].help, /large value suggests a cold brown dwarf/i);
  assert.equal(rows[1].value, '22.1 mag');
  assert.match(rows[1].help, /faint for how fast it moves/);
  assert.match(rows[1].help, /white dwarf/);
});

test('null fields are hidden, absent block gives nothing', () => {
  assert.deepEqual(vettingRows(null), []);
  assert.deepEqual(vettingRows({ w1_mag: null, w2_mag: 15.9, w1_w2: null, reduced_pm_w2: null, catalogue: null }), []);
  assert.deepEqual(vettingRows({ reduced_pm_w2: 19 }).map((r) => r.key), ['hw2']);
  assert.deepEqual(vettingLines({ w1_w2: 1.234 }), ['W1−W2 colour: 1.23 mag']);
});

test('the validator keeps vetting and drops junk', () => {
  const v = validateManifest({ ...base, vetting: { w1_w2: 2.5, reduced_pm_w2: 'x', catalogue: 'CatWISE2020' } }).manifest.vetting;
  assert.deepEqual(v, { w1_mag: null, w2_mag: null, w1_w2: 2.5, reduced_pm_w2: null, catalogue: 'CatWISE2020' });
  assert.equal(validateManifest({ ...base, vetting: { w1_w2: null } }).manifest.vetting, null);
  assert.equal(validateManifest(base).manifest.vetting, null);
});
