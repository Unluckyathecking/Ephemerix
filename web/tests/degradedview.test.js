// A live view built while archives were down must say what it could not check, never state a
// finding about the sky. Manifests here are shaped like real ones built on 15 Nov 2026 with
// IRSA's search, ESA Gaia and the Data Lab mirror not answering.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { validateManifest } from '../js/manifest.js';
import { verdictTiles } from '../js/verdict.js';
import { fieldHeadline } from '../js/fieldnote.js';
import { nothingVisible, noMotionReason, imagesMissing, neighboursUnchecked } from '../js/summary.js';
import { motionSentence } from '../js/simpletext.js';

const NO_WISE = 'WISE images could not be loaded; the archive did not answer.';
const PART_WISE = 'The IRSA search for WISE frames from 2010 (three-band), 2013-2024 (NEOWISE) failed, so those frames are missing.';
const CHECKS = 'CatWISE2020 sources could not be fetched, so the checks for neighbours that bias the measured positions or add light to the spectrum could not be run.';
const CATALOGUES = ['Gaia DR3 sources could not be fetched, so none are marked.', 'CatWISE2020 sources could not be fetched, so none are marked.', CHECKS];
const NO_WISE_REASON = 'the WISE images could not be loaded; a motion needs their years of positions';
const SPX_GLARE = 'This spot is so bright in the infrared that it overloads SPHEREx: most of the images show glare and detector artefacts rather than the object itself, and the flat patches in them are where there is no usable measurement.';

const spx = (id, extra = {}) => ({ id, mission: 'SPHEREx', band: 'spx-b6', image: `${id}.png`, mjd: 61000, date: '2025-11-20', ...extra });

function view(extra = {}) {
  return validateManifest({
    schema: 1, center: { ra: 161.33, dec: -5.21 }, size_px: 240, fov_arcsec: 240,
    frames: [spx('spx-b6-2025a'), spx('spx-b6-2026a', { mjd: 61200, date: '2026-06-08' })],
    measured_motion: null, motion_not_measured: null, degraded: true,
    field: { saturated: false, saturated_missions: [], crowded: null, no_data_near_target: { SPHEREx: 0 } },
    warnings: [NO_WISE, ...CATALOGUES, 'The target was not detected in any frame.', 'No proper motion is known, so no predicted path is drawn.'],
    ...extra,
  }).manifest;
}

const tile = (m, key) => verdictTiles(m).find((t) => t.key === key);

test('a view missing its WISE images says it could not check, not "Nothing visible here"', () => {
  const m = view(); // as the service answers today: no reason from the pipeline
  assert.equal(imagesMissing(m), true);
  assert.equal(nothingVisible(m), false);
  const t = tile(m, 'motion');
  assert.equal(t.value, 'Not measured');
  assert.equal(t.sub, 'this could not be checked: some of the images did not load');
  assert.match(noMotionReason(m), /^This could not be checked: some of the images did not load/);
  const simple = motionSentence(m);
  assert.doesNotMatch(simple, /Nothing is visible|too faint|too blue/);
  assert.match(simple, /could not be checked/);
});

test('with the pipeline naming the missing WISE images, the tile gives that reason', () => {
  const m = view({ motion_not_measured: { reason: NO_WISE_REASON, n_detections: 0, baseline_years: 0 },
    warnings: [`Motion not measured: ${NO_WISE_REASON}.`, NO_WISE, ...CATALOGUES] });
  assert.equal(nothingVisible(m), false);
  const t = tile(m, 'motion');
  assert.deepEqual([t.value, t.sub], ['Not measured', 'the WISE images could not be loaded']);
  assert.equal(noMotionReason(m), 'The WISE images could not be loaded; a motion needs their years of positions.');
  assert.doesNotMatch(motionSentence(m), /Nothing is visible/);
});

test('a view missing only some WISE years, with nothing found, also could not check', () => {
  const wise = { id: 'wise-w2-2010a', mission: 'WISE', band: 'W2', image: 'w.png', mjd: 55300, date: '2010-04-14' };
  const m = view({ frames: [wise, spx('spx-b6-2025a')], warnings: [PART_WISE, ...CATALOGUES, 'The target was not detected in any frame.'] });
  assert.equal(nothingVisible(m), false);
  assert.equal(tile(m, 'motion').sub, 'this could not be checked: some of the images did not load');
  // A detection in what did load keeps the usual, factual wording.
  const seen = view({ frames: [wise, spx('spx-b6-2025a', { centroid_px: [120, 120], centroid_err_arcsec: 0.4 })], warnings: [PART_WISE] });
  assert.match(noMotionReason(seen), /found in only 1 frame/);
});

test('a complete view that found nothing still says so', () => {
  const m = view({ degraded: false, warnings: ['The target was not detected in any frame.'] });
  assert.equal(imagesMissing(m), false);
  assert.equal(nothingVisible(m), true);
  assert.equal(tile(m, 'motion').value, 'Nothing visible here');
  // Catalogues down but every image present: the images were all looked at.
  assert.equal(nothingVisible(view({ warnings: [...CATALOGUES, 'The target was not detected in any frame.'] })), true);
});

test('the spectrum tile does not read as a finding when the neighbour checks could not run', () => {
  const stored = JSON.parse(readFileSync(new URL('../gallery/epsilon-indi-b/manifest.json', import.meta.url)));
  const whole = validateManifest(stored).manifest;
  assert.ok(whole.match && !neighboursUnchecked(whole));
  const before = tile(whole, 'spectrum');
  const part = validateManifest({ ...stored, degraded: true, warnings: [...stored.warnings, ...CATALOGUES] }).manifest;
  const t = tile(part, 'spectrum');
  assert.equal(t.value, 'Not confirmed');
  assert.match(t.sub, /catalogues of neighbouring stars did not load/);
  assert.notEqual(before.value, 'Not confirmed');
  // No match at all in a partial view: the reason is that it could not be checked.
  const none = tile(view({ spectra: stored.spectra }), 'spectrum');
  assert.match(none.sub, /^could not be checked: /);
  const unseen = view({ spectra: stored.spectra, warnings: [NO_WISE, 'The spectrum is not classified because the target was not found in any WISE or SPHEREx image, so nothing confirms that the light measured at its predicted position is the target\'s.'] });
  assert.equal(tile(unseen, 'spectrum').sub, 'could not be checked: the WISE images did not load');
});

test('glare recognised from SPHEREx alone leads the view with its own sentence', () => {
  const m = view({ field: { saturated: true, saturated_missions: ['SPHEREx'], crowded: null, no_data_near_target: { SPHEREx: 1 } },
    motion_not_measured: { reason: NO_WISE_REASON, n_detections: 0, baseline_years: 0 },
    warnings: [SPX_GLARE, `Motion not measured: ${NO_WISE_REASON}.`, NO_WISE, ...CATALOGUES] });
  assert.equal(fieldHeadline(m), SPX_GLARE);
  assert.deepEqual(m.field.saturated_missions, ['SPHEREx']);
  assert.equal(tile(m, 'motion').sub, 'the WISE images could not be loaded');
});
