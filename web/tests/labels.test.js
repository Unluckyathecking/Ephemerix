import { test } from 'node:test';
import assert from 'node:assert/strict';
import { formatUm, windowLabel, setLabel, shortLabel } from '../js/labels.js';

test('wavelengths keep hundredths only when they matter', () => {
  assert.equal(formatUm(0.75), '0.75');
  assert.equal(formatUm(1.10), '1.1');
  assert.equal(formatUm(5.0), '5.0');
  assert.equal(formatUm(2.42), '2.42');
  assert.equal(formatUm(4.4), '4.4');
  assert.equal(formatUm(NaN), '?');
});

test('the six SPHEREx detector bands', () => {
  const windows = [[0.75, 1.10], [1.10, 1.65], [1.65, 2.42], [2.42, 3.82], [3.82, 4.42], [4.42, 5.00]];
  const labels = windows.map((w, i) => setLabel({ mission: 'SPHEREx', band: `spx-b${i + 1}`, wavelength_um: w }));
  assert.deepEqual(labels, ['SPHEREx 0.75–1.1 µm', 'SPHEREx 1.1–1.65 µm', 'SPHEREx 1.65–2.42 µm',
    'SPHEREx 2.42–3.82 µm', 'SPHEREx 3.82–4.42 µm', 'SPHEREx 4.42–5.0 µm']);
  for (const l of labels) assert.doesNotMatch(l, /spx-b/);
});

test('WISE uses nominal band centres, not passband midpoints', () => {
  assert.equal(setLabel({ mission: 'WISE', band: 'W2', wavelength_um: [4.0, 5.2] }), 'WISE W2 (4.6 µm)');
  assert.equal(setLabel({ mission: 'WISE', band: 'W1', wavelength_um: [2.8, 3.8] }), 'WISE W1 (3.4 µm)');
  assert.equal(setLabel({ mission: 'WISE', band: 'odd', wavelength_um: [3, 4] }), 'WISE 3.5 µm');
});

test('frame sets from framesets.js (window field) and fallbacks', () => {
  assert.equal(setLabel({ mission: 'SPHEREx', band: 'spx-b6', window: [4.4, 5.0] }), 'SPHEREx 4.4–5.0 µm');
  assert.equal(setLabel({ mission: 'SPHEREx', band: 'x', wavelength_um: null }), 'SPHEREx x');
  assert.equal(shortLabel({ mission: 'SPHEREx', band: 'spx-b1', wavelength_um: [0.75, 1.1] }), '0.75–1.1 µm');
  assert.equal(shortLabel({ mission: 'WISE', band: 'W2', wavelength_um: [4, 5.2] }), 'W2');
  assert.equal(windowLabel(null), null);
});
