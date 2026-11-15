import { test } from 'node:test';
import assert from 'node:assert/strict';
import { bodyRecoveryProblem, recoveryRows, rateText, controlText, limitText } from '../js/validationbodies.js';

const row = (bin, n, k, ci95) => ({ bin, n, k, ci95 });
const DATA = {
  by_predicted_v: [row('10-12', 18, 18, [0.81, 1]), row('17-18', 15, 15, [0.78, 1]), row('18-19', 20, 16, [0.56, 0.94]),
    row('19-20', 46, 22, [0.33, 0.63]), row('20-21', 48, 5, [0.03, 0.23]), row('22-24', 0, 0, [null, null])],
  faintest_reliable_bin: '18-19',
  false_detections: { passes: { n: 551, k: 4, ci95: [0.002, 0.019] } },
  before: { by_predicted_v: [row('19-20', 46, 29, [0.48, 0.77])], false_detections: { passes: { n: 551, k: 34, ci95: [0.0431, 0.0852] } } },
};

test('problem: missing pieces are named, a full file passes', () => {
  assert.equal(bodyRecoveryProblem(null), 'not an object');
  assert.equal(bodyRecoveryProblem({}), 'no recovery table');
  assert.equal(bodyRecoveryProblem({ by_predicted_v: [] }), 'no control rates');
  assert.equal(bodyRecoveryProblem(DATA), null);
});

test('rows skip empty bins and carry the interval and the old-rule count', () => {
  const rows = recoveryRows(DATA);
  assert.equal(rows.length, 5);
  const r = rows.find((x) => x.bin === '19-20');
  assert.equal(r.before, 29);
  assert.equal(r.lo, 0.33);
  assert.ok(Math.abs(r.frac - 22 / 46) < 1e-9);
  assert.equal(rows[0].before, null);
});

test('rate text with interval, and a dash when there is nothing', () => {
  assert.equal(rateText(DATA.false_detections.passes), '4 of 551 (0.7%; 95% interval 0.2–1.9%)');
  assert.equal(rateText({ n: 0, k: 0 }), '—');
});

test('control text gives before and after', () => {
  const t = controlText(DATA);
  assert.match(t, /34 of 551 \(6\.2%/);
  assert.match(t, /counts 4 of 551/);
  assert.doesNotMatch(controlText({ ...DATA, before: undefined }), /old rule/);
});

test('limit text: bright passes all recovered, faintest reliable bin, the fall-off', () => {
  const t = limitText(DATA);
  assert.match(t, /brighter than V 18 was recovered \(33 of 33\)/);
  assert.match(t, /V 18–19/);
  assert.match(t, /48% at V 19–20, 10% at V 20–21/);
});
