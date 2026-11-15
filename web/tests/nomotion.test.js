import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { noMotionHeadline, noMotionReason } from '../js/summary.js';
import { nameBands } from '../js/labels.js';
import { validateManifest } from '../js/manifest.js';

const frame = (centroid) => ({ centroid_px: centroid ? [1, 1] : null });

test('no measured motion: the pipeline\'s own sentence, else a count of detections', () => {
  const m = { measured_motion: null, warnings: ['7 of 366 SPHEREx spectrum points are left out.', 'The target was not detected in any frame.'], frames: [] };
  assert.equal(noMotionHeadline(m), 'Not measured: the target was not detected in any frame.');
  assert.equal(noMotionReason({ measured_motion: null, warnings: [], frames: [frame(true), frame(false)] }), 'The object was found in only 1 frame, too few to measure a motion.');
  assert.equal(noMotionHeadline({ measured_motion: null, warnings: [], frames: [] }), 'Not measured: the object was not found in any frame.');
  assert.equal(noMotionHeadline({ measured_motion: { pmra_masyr: 1, pmdec_masyr: 1 }, warnings: [], frames: [] }), null);
  // A note about one frame is not the reason for the whole view.
  assert.equal(noMotionHeadline({ measured_motion: null, warnings: ['W1 frame of Nov 2010: the object was not detected (it is faint at 3.4 µm).'], frames: [] }), 'Not measured: the object was not found in any frame.');
  // Detections left out of the fit: the view's own sentence, not a count of frames.
  const blended = '3 detections are left out of the motion fit because a catalogued source of similar brightness lies within the area the position is fitted over.';
  const three = { measured_motion: null, warnings: ['7 of 366 SPHEREx spectrum points are left out.', blended], frames: [frame(true), frame(true), frame(true)] };
  assert.equal(noMotionReason(three), blended);
  assert.equal(noMotionHeadline(three), `Not measured: ${blended}`);
  // A proper noun at the start keeps its capital.
  assert.equal(noMotionHeadline({ measured_motion: null, warnings: ['WISE: not detected in any frame.'], frames: [] }), 'Not measured: WISE: not detected in any frame.');
});

test('real view with no detections gets a headline', { skip: !existsSync(new URL('../gallery/cwise-2021-1524/manifest.json', import.meta.url)) }, () => {
  const m = validateManifest(JSON.parse(readFileSync(new URL('../gallery/cwise-2021-1524/manifest.json', import.meta.url)))).manifest;
  // The gallery is rebuilt from time to time, so check the shape, not one sentence.
  assert.equal(m.measured_motion, null);
  assert.match(noMotionHeadline(m), /^Not measured: \S.+\.$/);
});

test('band ids in pipeline text are named as the page names them', () => {
  const frames = [{ mission: 'SPHEREx', band: 'spx-b6', wavelength_um: [4.42, 5.0] }, { mission: 'WISE', band: 'W2', wavelength_um: [4, 5.2] }];
  assert.equal(nameBands('position disagrees with spx-b6 at the same epoch', frames), 'position disagrees with SPHEREx 4.42–5.0 µm at the same epoch');
  assert.equal(nameBands('disagrees with W2', frames), 'disagrees with W2');
  assert.equal(nameBands('unknown spx-b9 stays', frames), 'unknown spx-b9 stays');
});
