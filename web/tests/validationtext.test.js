import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  verdictLabel, fmt, fmtSigned, fmtPct, fmtSigma, viewHref, builtText, summaryCells,
  residualText, framesText, yearSpan, rangeText, reportProblem, groupRows, motionText, countsText,
  provisionalLabel, faintTypesText, motionLabel, weakTestNote,
} from '../js/validationtext.js';

test('a provisional chip says which kind: a neighbour, or a faint object with an open-ended range', () => {
  assert.equal(provisionalLabel({ provisional: 'A catalogued source ...' }), 'Provisional');
  assert.equal(provisionalLabel({ provisional: 'x', provisional_kind: 'neighbour' }), 'Provisional');
  assert.equal(provisionalLabel({ provisional: 'x', provisional_kind: 'faint', range_open_cold: true }), 'Provisional: faint, open-ended range');
  assert.equal(provisionalLabel({ provisional: 'x', provisional_kind: 'faint' }), 'Provisional: faint');
  assert.equal(provisionalLabel({ provisional: null, provisional_kind: 'faint' }), null);
  assert.equal(provisionalLabel(undefined), null);
});

test('types given to faint objects are described apart, and not at all when there are none', () => {
  assert.equal(faintTypesText({ passed: 8, total: 8 }), '');
  assert.equal(faintTypesText({ faint: { passed: 0, failed: 0, open_ended: 0 } }), '');
  const one = faintTypesText({ faint: { passed: 1, failed: 0, open_ended: 1 } });
  assert.match(one, /That one was given to an object too faint/);
  const full = faintTypesText({ passed: 8, total: 8, provisional: 2, faint: { passed: 1, failed: 0, open_ended: 1 } });
  assert.match(full, /^In all we gave 9 types: the 8 scored above \(8 contain the published type, 2 of them provisional\) and one more\. That one/);
  assert.match(one, /It contains the published type, with a range that is open at one end\./);
  assert.match(one, /counted apart from the types above\.$/);
  assert.match(faintTypesText({ faint: { passed: 0, failed: 1, open_ended: 0 } }), /It does not contain the published type\./);
  assert.match(faintTypesText({ faint: { passed: 2, failed: 1, open_ended: 1 } }), /and 3 more\. Those were given .* 2 of them contain the published type \(1 with a range that is open at one end\)\./);
  assert.doesNotMatch(one, /the tool|refuse|undefined|NaN/i);
});

test('a weak-test pass is labelled and counted for the note under the scoreboard', () => {
  const weak = { verdict: 'pass', weak_test: true };
  assert.equal(motionLabel(weak), 'Consistent (weak)');
  assert.equal(motionLabel({ verdict: 'pass', weak_test: false }), 'Pass');
  assert.equal(motionLabel({ verdict: 'fail', weak_test: true }), 'Differs');
  const rows = [{ motion: weak }, { motion: weak }, { motion: { verdict: 'pass' } }];
  assert.equal(weakTestNote(rows), 'For 2 slow stars agreement only shows we measure no false motion.');
  assert.equal(weakTestNote(rows.slice(1)), 'For 1 slow star agreement only shows we measure no false motion.');
  assert.equal(weakTestNote([]), '');
});

test('verdict labels, unknown falls back', () => {
  assert.equal(verdictLabel('pass'), 'Pass');
  assert.equal(verdictLabel('not_applicable'), 'Not applicable');
  assert.equal(verdictLabel('nonsense'), 'Unknown');
});

test('numbers: missing is a dash, signs use a real minus', () => {
  assert.equal(fmt(null), '—');
  assert.equal(fmt(3.14159, 2), '3.14');
  assert.equal(fmtSigned(-43.3), '−43.3');
  assert.equal(fmtSigned(9.1), '+9.1');
  assert.equal(fmtSigned(-0.01), '0.0');
  assert.equal(fmtPct(0.655), '+0.66%');
  assert.equal(fmtSigma(7.285), '7.3 σ');
  assert.equal(fmtSigma(undefined), '—');
});

test('view link uses the site query format and never trusts odd input', () => {
  assert.equal(viewHref('epsilon-indi-b'), './?target=epsilon-indi-b');
  assert.equal(viewHref(undefined), './');
});

test('last built reads ISO in UTC', () => {
  assert.equal(builtText('2026-11-14T18:24:40Z'), '14 Nov 2026, 18:24 UTC');
  assert.equal(builtText('garbage'), null);
  assert.equal(builtText(null), null);
});

test('summary row counts refusals separately', () => {
  const cells = summaryCells({ motion: { passed: 5, total: 6 }, type: { passed: 4, total: 4, refused: 1 } });
  assert.deepEqual(cells.map((c) => c.value), ['5 of 6', '4 of 4', '1']);
  assert.equal(cells[2].label, 'target unclassified');
  assert.deepEqual(summaryCells(null).map((c) => c.value), ['0 of 0', '0 of 0', '0']);
});

test('residual text names the frame and the native pixel', () => {
  const t = residualText({ max_px: 2.2, max_arcsec: 2.2, max_native_px: 0.36, mission: 'SPHEREx', frame_id: 'spx-b2-2026a' });
  assert.equal(t, '2.2″ (0.36 SPHEREx pixel) in spx-b2-2026a');
  assert.equal(residualText({ max_px: null }), 'no frame with a detection');
});

test('frame and year text', () => {
  assert.equal(framesText({ frames: 46, epochs: 23 }), '46 frames, 23 epochs');
  assert.equal(framesText({ frames: 1, epochs: 1 }), '1 frame, 1 epoch');
  assert.equal(yearSpan({ first_year: 2010, last_year: 2010 }), '2010 only');
  assert.equal(yearSpan({ first_year: 2010, last_year: 2024 }), '2010 to 2024');
  assert.equal(yearSpan({ first_year: null }), '—');
});

test('range text honours open ends', () => {
  assert.equal(rangeText({ range: ['T1', 'T3'] }), 'T1 to T3');
  assert.equal(rangeText({ range: ['Y0', 'Y1'], range_open_cold: true }), 'Y0 to Y1 or colder');
  assert.equal(rangeText({ range: ['T8', 'T8'] }), 'T8');
  assert.equal(rangeText({}), '—');
});

test('report problems', () => {
  assert.match(reportProblem(null), /not an object/);
  assert.match(reportProblem({ schema: 2 }), /version/);
  assert.match(reportProblem({ schema: 1, targets: [] }), /incomplete/);
  assert.equal(reportProblem({ schema: 1, targets: [], summary: {} }), null);
});

test('rows are grouped in a fixed order, unknown groups last, empty groups dropped', () => {
  const rows = [{ slug: 'a', group: 'benchmark' }, { slug: 'b', group: 'brief' }, { slug: 'c', group: 'odd' }, { slug: 'd' }];
  const g = groupRows(rows);
  assert.deepEqual(g.map((x) => x.key), ['brief', 'benchmark', 'other']);
  assert.deepEqual(g[2].rows.map((r) => r.slug), ['c', 'd']);
  assert.equal(g[0].label, 'Brief targets');
});

test('motion text never prints undefined or NaN when nothing was measured', () => {
  const m = {
    verdict: 'not_applicable', reason: 'The target was not detected in any frame, so no motion was measured.',
    catalogue: { pmra: 7, pmdec: -980, total_arcsec_yr: 0.98 }, measured: { pmra: null, pmdec: null, total_arcsec_yr: null },
    diff: { pmra: null, pmdec: null, total_pct: null }, err_masyr: { pmra: null, pmdec: null }, sigma: null,
    baseline_years: null, n_detections: null,
  };
  const t = motionText(m);
  assert.equal(t.catalogue, '7.0, -980.0');
  assert.equal(t.measured, '—');
  assert.equal(t.diff, '—');
  assert.equal(t.error, '—');
  assert.equal(t.sigma, '—');
  assert.equal(t.baseline, '—');
  assert.equal(t.detections, '0');
  for (const v of Object.values(t)) assert.doesNotMatch(v, /undefined|NaN/);
  assert.equal(motionText({}).catalogue, '—');
});

test('a motion fitted on all images at once counts images, not detections', () => {
  const m = { method: 'all_frames', n_frames: 23, n_detections: 0, baseline_years: 13.96 };
  assert.equal(motionText(m).detections, '23 images at once');
  assert.equal(motionText({ method: 'all_frames', n_detections: 0 }).detections, 'all images at once');
  assert.equal(motionText({ n_detections: 25 }).detections, '25');
});

test('counts text adds up and uses the real target count', () => {
  const c = { passed: 10, failed: 3, refused: 0, not_applicable: 4 };
  assert.equal(countsText(c), '10 passed, 3 failed, 4 not applicable');
  assert.equal(countsText({ passed: 9, failed: 1, refused: 5, not_applicable: 2 }), '9 passed, 1 failed, 5 unclassified, 2 not applicable');
});
