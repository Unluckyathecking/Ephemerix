import { test } from 'node:test';
import assert from 'node:assert/strict';
import { frameFlag, explainWarning, flaggedNote, noMatchReason, missingNote } from '../js/flags.js';
import { validateManifest } from '../js/manifest.js';

test('clean frames get no badge', () => {
  assert.equal(frameFlag({ flag_fraction: 0, warnings: [] }), null);
  assert.equal(frameFlag({ flag_fraction: 0.004, warnings: [] }), null);
  assert.equal(frameFlag(null), null);
});

test('flagged share and warnings in plain words', () => {
  const b = frameFlag({ flag_fraction: 0.18, warnings: ['saturated'] });
  assert.equal(b.short, '18% flagged · saturated');
  assert.match(b.long, /18% of the pixels stacked into this image were dropped/);
  assert.match(b.long, /Saturated: a bright star overloaded the detector/);
  assert.equal(explainWarning('odd thing'), 'Odd thing.');
});

const spec = { points: [{ flagged: true }, { flagged: false }, { flagged: true }] };

test('flagged spectrum points are counted with reasons from warnings', () => {
  assert.equal(flaggedNote({ points: [{ flagged: false }] }), null);
  assert.equal(flaggedNote(spec, []), '2 of 3 points were flagged and left out of the fit (hollow grey dots).');
  assert.match(flaggedNote(spec, ['2 points flagged: saturated pixels nearby.', 'Unrelated note.']), /\(hollow grey dots\)\. 2 points flagged: saturated pixels nearby\.$/);
});

test('the reason for no type call comes from warnings, or nothing', () => {
  assert.equal(noMatchReason(['Synthetic test data.', 'Detected, but too faint to classify (S/N 3).']), 'Detected, but too faint to classify (S/N 3).');
  assert.equal(noMatchReason(['W1 frame missing.']), null);
  assert.equal(noMatchReason(), null);
});

test('flagged points with no flux are kept by the validator, not dropped', () => {
  const m = validateManifest({ schema: 1, center: { ra: 1, dec: 1 }, size_px: 10, fov_arcsec: 10,
    frames: [{ id: 'a', mission: 'WISE', band: 'W2', image: 'a.png', mjd: 55000 }],
    spectra: [{ id: 's', label: 'S', unit: 'mJy', points: [
      { wl_um: 1.0, flux: 1, err: 0.1, flagged: false },
      { wl_um: 3.3, flux: null, err: null, flagged: true, reason: 'saturated' },
      { wl_um: 2.0, flux: null, err: null, flagged: true },
      { wl_um: 4.0, flux: null, err: null, flagged: false }, // invalid: unflagged without flux
    ] }] }).manifest;
  const s = m.spectra[0];
  assert.equal(s.points.length, 1);
  assert.deepEqual(s.missing, [{ wl_um: 2.0, reason: null }, { wl_um: 3.3, reason: 'saturated' }]);
});

test('missing-flux note: count, per-point reasons, or the pipeline warning', () => {
  assert.equal(missingNote({ missing: [] }), null);
  assert.equal(missingNote({}), null);
  const per = missingNote({ missing: [{ wl_um: 1, reason: 'saturated' }, { wl_um: 2, reason: 'saturated' }, { wl_um: 3, reason: 'masked' }] });
  assert.match(per, /^3 points left out of this spectrum: no usable flux \(saturated 2 \/ masked 1\)\./);
  const warn = ['3 of 40 SPHEREx spectrum points are left out (2 where the target saturates the detector, 1 where too much of the target is covered by bad pixels).'];
  const viaWarning = missingNote({ missing: [{ wl_um: 1, reason: null }] }, warn);
  assert.match(viaWarning, /^1 point left out/);
  assert.match(viaWarning, /where the target saturates the detector \/ where too much of the target is covered by bad pixels/);
  assert.doesNotMatch(viaWarning, /\(2 /);
  assert.match(missingNote({ missing: [{ wl_um: 1, reason: null }] }, ['unrelated warning']), /^1 point left out of this spectrum: no usable flux\./);
});
