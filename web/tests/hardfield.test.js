import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { validateManifest } from '../js/manifest.js';
import { verdictTiles } from '../js/verdict.js';
import { fieldHeadline } from '../js/fieldnote.js';
import { nothingVisible, noMotionReason } from '../js/summary.js';
import { motionSentence } from '../js/simpletext.js';
import { hatchPixels, GAP_KEY } from '../js/gaphatch.js';
import { viewFacts } from '../js/facts.js';

const GLARE = 'This spot is so bright in the infrared that it overloads both WISE and SPHEREx: most of the images show glare and detector artefacts rather than the object itself, and the flat patches in them are where there is no usable measurement.';
const THIN = 'only 3 clean detections over 1.01 years; we need at least 4 over 3 years to tell motion from parallax and noise';

function hard(extra = {}) {
  return validateManifest({
    schema: 1, center: { ra: 266.4, dec: -29 }, size_px: 10, fov_arcsec: 10,
    frames: [
      { id: 'a', mission: 'WISE', band: 'W2', image: 'a.png', mjd: 55300, flag_fraction: 0.4,
        no_data_fraction: 0.33, no_data_near_target: 1, gaps_image: 'frames/a-gaps.png' },
      { id: 'b', mission: 'SPHEREx', band: 'spx-b1', image: 'b.png', mjd: 61000, centroid_px: [5, 5], centroid_err_arcsec: 0.3 },
    ],
    field: { saturated: true, saturated_missions: ['SPHEREx', 'WISE'], crowded: null, no_data_near_target: { WISE: 1 } },
    motion_not_measured: { reason: THIN, n_detections: 3, baseline_years: 1.01 },
    measured_motion: null,
    warnings: [GLARE, `Motion not measured: ${THIN}.`],
    ...extra,
  }).manifest;
}

test('the new fields pass through validation, with safe defaults', () => {
  const m = hard();
  assert.deepEqual(m.field, { saturated: true, crowded: null, saturated_missions: ['SPHEREx', 'WISE'] });
  assert.deepEqual(m.motion_not_measured, { reason: THIN, n_detections: 3, baseline_years: 1.01 });
  assert.equal(m.frames[0].gaps_image, 'frames/a-gaps.png');
  assert.equal(m.frames[0].no_data_fraction, 0.33);
  assert.equal(m.frames[0].no_data_near_target, 1);
  assert.equal(m.frames[1].gaps_image, null);
  assert.equal(m.frames[1].no_data_fraction, null);
  const old = hard({ field: undefined, motion_not_measured: 'nonsense', frames: [{ id: 'a', mission: 'WISE', band: 'W2', image: 'a.png', mjd: 1, no_data_fraction: 7 }] });
  assert.equal(old.field, null);
  assert.equal(old.motion_not_measured, null);
  assert.equal(old.frames[0].no_data_fraction, null);
});

test('glare leads: the pipeline sentence, only when field.saturated', () => {
  assert.equal(fieldHeadline(hard()), GLARE);
  assert.equal(fieldHeadline(hard({ field: { saturated: false, crowded: true } })), null);
  assert.equal(fieldHeadline(hard({ field: undefined })), null);
});

test('a thin motion reads "Not measured" with the reason in a few words', () => {
  const tile = verdictTiles(hard())[0];
  assert.equal(tile.value, 'Not measured');
  assert.equal(tile.sub, 'only 3 clean detections over 1.01 years');
  assert.equal(noMotionReason(hard()), `Only 3 clean detections over 1.01 years; we need at least 4 over 3 years to tell motion from parallax and noise.`);
  assert.match(motionSentence(hard()), /^We could not measure a motion: only 3 clean detections over 1\.01 years; we need/);
});

test('glare is not "nothing visible", and US 708-like views still are', () => {
  const blind = hard({ motion_not_measured: null, frames: [{ id: 'a', mission: 'WISE', band: 'W2', image: 'a.png', mjd: 55300 }] });
  assert.equal(nothingVisible(blind), false);
  assert.equal(verdictTiles(blind)[0].value, 'Not measured');
  const faint = hard({ field: { saturated: false }, motion_not_measured: null, warnings: [], frames: [{ id: 'a', mission: 'WISE', band: 'W2', image: 'a.png', mjd: 55300 }] });
  assert.equal(nothingVisible(faint), true);
  assert.equal(verdictTiles(faint)[0].value, 'Nothing visible here');
  assert.equal(fieldHeadline(faint), null);
});

test('the hatch marks every fourth diagonal inside the gaps, and nothing outside', () => {
  const w = 8, h = 8, mask = new Uint8ClampedArray(w * h * 4);
  for (let y = 0; y < h; y += 1) for (let x = 0; x < 4; x += 1) mask[(y * w + x) * 4] = 255;
  const out = hatchPixels(mask, w, h);
  const on = (x, y) => out[(y * w + x) * 4 + 3] > 0;
  assert.ok(on(0, 0) && on(3, 1) && !on(1, 0));
  for (let y = 0; y < h; y += 1) for (let x = 4; x < w; x += 1) assert.ok(!on(x, y));
  assert.ok(out[3] < 128); // faint
  assert.equal(GAP_KEY('a'), 'gaps:a');
});

test('Simple says what to look for in glare', async () => {
  const { lookFor } = await import('../js/simplelook.js');
  assert.match(lookFor(hard()), /^The ring marks where the object is; what you see around it is mostly its glare/);
});

test('no motion facts for a view whose motion was not measured', () => {
  assert.deepEqual(viewFacts(hard()).map((f) => f.title), ['Images', 'Latest look']);
});

test('an ordinary gallery view is not a hard field and shows no banner', () => {
  const m = validateManifest(JSON.parse(readFileSync(new URL('../gallery/barnards-star/manifest.json', import.meta.url)))).manifest;
  assert.equal(m.field.saturated, false);
  assert.equal(fieldHeadline(m), null);
  assert.equal(m.motion_not_measured, null);
  assert.ok(m.frames.every((f) => f.gaps_image === null || f.gaps_image.endsWith('-gaps.png')));
});
