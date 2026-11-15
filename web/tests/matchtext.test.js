import { test } from 'node:test';
import assert from 'node:assert/strict';
import { typeRangeText, classText, pairText, rangeSentence, notBrownDwarf, showsType, CONFIDENCE_WORDS, neutralClass, passSummary, matchDetails } from '../js/matchtext.js';
import { typeCall } from '../js/summary.js';
import { validateManifest } from '../js/manifest.js';

test('a one-type range is never shown as exact', () => {
  assert.equal(typeRangeText({ type_range: ['T8', 'T8'] }), 'about T8');
  assert.equal(typeRangeText({ type_range: ['T7', 'T9'] }), 'T7 to T9');
  assert.equal(typeRangeText({}), null);
  assert.equal(typeRangeText(null), null);
});

test('open ends at the template grid edges', () => {
  assert.equal(typeRangeText({ type_range: ['Y1', 'Y1'], range_open_cold: true }), 'Y1 or colder');
  assert.equal(typeRangeText({ type_range: ['Y0', 'Y1'], range_open_cold: true }), 'Y0 to Y1 or colder');
  assert.equal(typeRangeText({ type_range: ['M8', 'M8'], range_open_warm: true }), 'M8 or warmer');
  assert.equal(typeRangeText({ type_range: ['M8', 'L1'], range_open_warm: true }), 'M8 or warmer to L1');
});

test('class words, including not-a-brown-dwarf and uncertain', () => {
  assert.equal(classText({ class: 'brown dwarf' }), 'Class: brown dwarf.');
  assert.match(classText({ class: 'not a brown dwarf' }), /not a brown dwarf/);
  assert.match(classText({ class: 'uncertain' }), /uncertain/);
  assert.equal(classText({}), null);
  assert.equal(notBrownDwarf({ class: 'star' }), true);
  assert.equal(notBrownDwarf({ best: { type: 'star (4500 K)' } }), true);
  assert.equal(notBrownDwarf({ class: 'brown dwarf', best: { type: 'T8' } }), false);
  assert.equal(rangeSentence({ class: 'not a brown dwarf', type_range: ['L0', 'L2'] }), null);
  assert.match(rangeSentence({ type_range: ['T8', 'T8'] }), /^Likely type: about T8\./);
});

test('the blended pair line', () => {
  assert.equal(pairText({ pair: { types: ['T1', 'T6'], chi2: 80, delta_vs_single: 25.5 } }),
    'Fits better as two blended brown dwarfs, about T1 and T6.');
  assert.equal(pairText({ pair: { types: ['T1', 'T6'] } }), 'Fits better as two blended brown dwarfs, about T1 and T6.');
  assert.equal(pairText({ pair: null }), null);
  assert.equal(pairText({}), null);
});

test('confidence words talk about the class, not the subtype', () => {
  for (const w of Object.values(CONFIDENCE_WORDS)) assert.match(w, /star|class/i);
});

test('the validator keeps the new match fields and drops bad ones', () => {
  const base = { schema: 1, center: { ra: 1, dec: 1 }, size_px: 10, fov_arcsec: 10,
    frames: [{ id: 'a', mission: 'WISE', band: 'W2', image: 'a.png', mjd: 55000 }] };
  const m = validateManifest({ ...base, match: { best: { type: 'Y1' }, class: 'brown dwarf', type_range: ['Y1', 'Y1'],
    range_open_cold: true, pair: { types: ['T1', 'T6'], delta_vs_single: 9 } } }).manifest.match;
  assert.equal(m.class, 'brown dwarf');
  assert.deepEqual(m.type_range, ['Y1', 'Y1']);
  assert.equal(m.range_open_cold, true);
  assert.equal(m.range_open_warm, false);
  assert.deepEqual(m.pair, { types: ['T1', 'T6'], chi2: null, delta_vs_single: 9, model: null });
  const bad = validateManifest({ ...base, match: { best: { type: 'Y1' }, class: 'alien', type_range: ['Y1'], pair: { types: ['T1'] } } }).manifest.match;
  assert.equal(bad.class, null);
  assert.equal(bad.type_range, null);
  assert.equal(bad.pair, null);
});

test('an uncertain class states no subtype and no class confidence', () => {
  const m = { verdict: 'Does not look like any template.', class: 'uncertain', confidence: 'high', type_range: ['T7', 'T9'], best: { type: 'T8' } };
  assert.equal(showsType(m), false);
  assert.equal(rangeSentence(m), null);
  assert.doesNotMatch(typeCall(m), /likely type|high confidence/);
  assert.match(typeCall(m), /class uncertain/);
});

test('the pair is stated once: not again when the verdict already names both types', () => {
  const pair = { types: ['T1', 'T6'], chi2: 80, delta_vs_single: 25.5 };
  assert.equal(pairText({ pair, verdict: 'Consistent with a blend of T1 and T6 brown dwarfs.' }), null);
  assert.match(pairText({ pair, verdict: 'Consistent with a cold brown dwarf, type T7 to T9.' }), /T1 and T6/);
  assert.match(pairText({ pair, verdict: 'Only T1 is named here.' }), /T1 and T6/);
});

test('medium confidence also covers "no template fits closely"', () => {
  assert.match(CONFIDENCE_WORDS.medium, /no template fits closely/);
  assert.doesNotMatch(CONFIDENCE_WORDS.medium, /star-like/);
});

test('not-a-brown-dwarf and uncertain are neutral, the rest are not', () => {
  assert.equal(neutralClass({ class: 'not a brown dwarf' }), true);
  assert.equal(neutralClass({ class: 'uncertain', confidence: 'low' }), true);
  assert.equal(neutralClass({ class: 'brown dwarf' }), false);
  assert.equal(neutralClass({ class: 'star' }), false);
  assert.equal(neutralClass(null), false);
});

test('per-pass summary: agree, disagree, and absent', () => {
  const p = (cls, type) => ({ id: type, label: type, class: cls, type });
  const bd = (t) => p('brown dwarf', t);
  assert.equal(passSummary({ per_pass: [bd('T8'), bd('T8'), bd('T8'), bd('T8')] }), 'All 4 passes agree: T8');
  assert.equal(passSummary({ per_pass: [bd('T8'), bd('T8'), bd('T7'), p('uncertain', 'T8')] }), 'Passes disagree: T8, T8, T7, uncertain');
  assert.equal(passSummary({ per_pass: [p('uncertain', null), p('uncertain', null)] }), 'All 2 passes agree: uncertain');
  assert.equal(passSummary({ per_pass: [bd('T8')] }), null);
  assert.equal(passSummary({ per_pass: [] }), null);
  assert.equal(passSummary({}), null);
  assert.equal(passSummary(null), null);
});

test('raw numbers go to the details rows, labelled as scores', () => {
  const rows = Object.fromEntries(matchDetails({ best: { type: 'T8', chi2: 160.2, dof: 78 }, runner_up: { type: 'T9', chi2: 210 },
    delta_chi2: 22.1, delta_class: 1016, bands_detected: ['H2O 1.4 um', 'CH4 3.3 um'],
    pair: { types: ['T1', 'T6'], chi2: 88.9, delta_vs_single: 44.7 } }));
  assert.equal(rows['Best template'], 'T8 (χ² 160.2 / 78 dof)');
  assert.match(rows['Score gap'], /^22\.1 \(runner-up score minus best score/);
  assert.match(rows['Class gap'], /^1016 /);
  assert.equal(rows['Molecular bands seen'], 'H2O 1.4 um, CH4 3.3 um');
  assert.match(rows['Blended pair'], /^T1 \+ T6, χ² 88\.9; 44\.7 better/);
  assert.doesNotMatch(JSON.stringify(rows), /Δχ²/);
  assert.deepEqual(matchDetails(null), []);
  assert.deepEqual(matchDetails({ best: { type: 'T8' } }), [['Best template', 'T8']]);
});

test('the validator keeps per_pass, delta_class and bands_detected, and drops junk', () => {
  const base = { schema: 1, center: { ra: 1, dec: 1 }, size_px: 10, fov_arcsec: 10,
    frames: [{ id: 'a', mission: 'WISE', band: 'W2', image: 'a.png', mjd: 55000 }] };
  const m = validateManifest({ ...base, match: { best: { type: 'T8' }, delta_class: 12, bands_detected: ['CH4', 3],
    per_pass: [{ id: 'p1', label: 'Nov 2025', class: 'brown dwarf', type: 'T8' }, null, 'x', { id: 'p2', class: 'alien' }, { id: 'p3', class: 'uncertain' }] } }).manifest.match;
  assert.equal(m.delta_class, 12);
  assert.deepEqual(m.bands_detected, ['CH4']);
  assert.deepEqual(m.per_pass.map((x) => [x.id, x.class, x.type]), [['p1', 'brown dwarf', 'T8'], ['p3', 'uncertain', null]]);
  assert.deepEqual(validateManifest({ ...base, match: { best: { type: 'T8' } } }).manifest.match.per_pass, []);
});

test('degraded is true only for a real true', () => {
  const base = { schema: 1, center: { ra: 1, dec: 1 }, size_px: 10, fov_arcsec: 10,
    frames: [{ id: 'a', mission: 'WISE', band: 'W2', image: 'a.png', mjd: 55000 }] };
  assert.equal(validateManifest({ ...base, degraded: true }).manifest.degraded, true);
  assert.equal(validateManifest({ ...base, degraded: 'true' }).manifest.degraded, false);
  assert.equal(validateManifest(base).manifest.degraded, false);
});
