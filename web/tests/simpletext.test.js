import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { validateManifest } from '../js/manifest.js';
import { motionSentence, whatSentence, partialSentence, missionLine, frameCaption, plainDate } from '../js/simpletext.js';
import { parseState, serializeState, viewMode } from '../js/urlstate.js';

const load = (slug) => validateManifest(JSON.parse(readFileSync(new URL(`./fixtures/gallery/${slug}/manifest.json`, import.meta.url)))).manifest;
const fast = load('synthetic-fast-mover');
const still = load('synthetic-no-motion');

test('a fast mover: how far over how many years, and against the catalogue', () => {
  const s = motionSentence(fast);
  assert.match(s, /^It is moving: over the 16 years we could measure it, it crossed 48 arcseconds of sky, about 2\.98 arcseconds a year\./);
  assert.match(s, /catalogue/);
});

test('a motion inside its error is not called a motion', () => {
  const m = { ...fast, measured_motion: { ...fast.measured_motion, pmra_masyr: 20, pmdec_masyr: -10, err_masyr: 20 } };
  assert.match(motionSentence(m), /^We see no motion we can measure over 16 years\.$/);
});

test('the catalogue clause can be left to the measured-against-catalogue pill', () => {
  const s = motionSentence(fast, { withCatalogue: false });
  assert.match(s, /^It is moving: over the 16 years we could measure it, it crossed 48 arcseconds of sky, about 2\.98 arcseconds a year\.$/);
});

test('a short baseline is said in plain years', () => {
  const m = { ...fast, measured_motion: { ...fast.measured_motion, baseline_years: 0.8 } };
  assert.match(motionSentence(m), /^It is moving: in under a year of measurements it crossed /);
  const one = { ...fast, measured_motion: { ...fast.measured_motion, baseline_years: 1.2 } };
  assert.match(motionSentence(one), /^It is moving: over the year we could measure it, it crossed /);
  const still2 = { ...fast, measured_motion: { ...fast.measured_motion, baseline_years: 1.2, pmra_masyr: 1, pmdec_masyr: 1, err_masyr: 20 } };
  assert.equal(motionSentence(still2), 'We see no motion we can measure over 1 year.');
});

test('a motion smaller than one image pixel says it is too small to see', () => {
  const pix = fast.fov_arcsec / fast.size_px;
  const yrs = fast.measured_motion.baseline_years;
  const tiny = (pix * 0.5 / yrs) * 1000; // half a pixel over the whole baseline, in mas/yr
  const m = { ...fast, target: { ...fast.target, pmra_masyr: tiny, pmdec_masyr: 0 },
    measured_motion: { ...fast.measured_motion, pmra_masyr: tiny, pmdec_masyr: 0, err_masyr: tiny / 10, err_pmra_masyr: tiny / 10, err_pmdec_masyr: tiny / 10 } };
  assert.match(motionSentence(m), /too small to see in these images/);
  assert.doesNotMatch(motionSentence(fast), /too small/);
});

test('a motion that differs from the catalogue says so', () => {
  const m = { ...fast, measured_motion: { ...fast.measured_motion, pmra_masyr: -1000, pmdec_masyr: 0, err_masyr: 10, err_pmra_masyr: 10, err_pmdec_masyr: 10 } };
  assert.match(motionSentence(m), /differs from the catalogue/);
});

test('no measured motion gives the reason in one clause', () => {
  // Found in one image only: too few to fit, with the reason.
  const once = { ...still, frames: still.frames.map((f, i) => ({ ...f, centroid_px: i === 0 ? [10, 10] : null })) };
  const s = motionSentence(once);
  assert.match(s, /^We could not measure a motion: /);
  assert.ok(s.endsWith('.'));
  // Found in no image at all: nothing visible, which is not our failure.
  assert.match(motionSentence({ ...still, frames: still.frames.map((f) => ({ ...f, centroid_px: null })) }), /^Nothing is visible at this position/);
});

test('what it is: a type, never stronger than the spectrum', () => {
  assert.match(whatSentence(fast), /^Its SPHEREx spectrum looks most like a brown dwarf of type about Y0\./);
  const prov = { ...fast, match: { ...fast.match, provisional: 'a neighbour may add light' } };
  assert.match(whatSentence(prov), /provisional/);
  assert.match(whatSentence(fast, { knownType: 'T8' }), /Its published type is T8\.$/);
});

test('what it is: no match stays unclassified or unsaid, with the reason', () => {
  const none = { ...fast, match: null, warnings: ['Every SPHEREx spectrum point is unusable (538 where the target saturates the detector), so there is no spectrum to judge.'] };
  assert.match(whatSentence(none), /^We cannot say what it is from SPHEREx: /);
  const refused = { ...fast, match: null, warnings: [] };
  assert.match(whatSentence(refused), /^We leave it unclassified/);
  for (const m of [fast, none, refused, still]) assert.doesNotMatch(whatSentence(m), /Planet X|discover/i);
});

test('a partial view says so in a few words', () => {
  assert.equal(partialSentence(fast), null);
  assert.match(partialSentence({ ...fast, degraded: true, warnings: [] }), /^This view is partial/);
});

test('missions and dates in plain words', () => {
  assert.match(missionLine(fast.frames), /^\d+ images: \d+ from WISE \(20\d\d to 20\d\d\) and \d+ from SPHEREx \(20\d\d(?: to 20\d\d)?\)\.$/);
  assert.equal(plainDate('2025-05-03T12:00:00'), '3 May 2025');
  assert.equal(frameCaption({ mission: 'SPHEREx', date: '2025-05-03' }), 'SPHEREx image, 3 May 2025');
  assert.equal(frameCaption(null), '');
});

test('mode: bare links are Advanced (full), simple comes from the URL or the stored choice', () => {
  assert.equal(viewMode(parseState('?target=x')), 'full');
  assert.equal(viewMode(parseState('?target=x'), 'simple'), 'simple');
  assert.equal(viewMode(parseState('?target=x&mode=full'), 'simple'), 'full');
  assert.equal(viewMode(parseState('?target=x&mode=advanced'), 'simple'), 'full');
  assert.equal(viewMode(parseState('?target=x&mode=simple&frame=a1')), 'simple');
  // An expert link without a mode stays Advanced even for someone who chose Simple.
  for (const q of ['?target=x&frame=a1', '?target=x&bands=W2', '?target=x&cmp=diff', '?target=x&spec=s1', '?target=x&embed=1', '?target=x&preset=spherex']) {
    assert.equal(viewMode(parseState(q), 'simple'), 'full', q);
  }
  assert.match(serializeState({ ...parseState('?target=x'), mode: 'simple' }), /mode=simple/);
  assert.doesNotMatch(serializeState({ ...parseState('?target=x'), mode: 'full' }), /mode=/);
  assert.equal(parseState('?target=x&mode=nonsense').mode, null);
});
