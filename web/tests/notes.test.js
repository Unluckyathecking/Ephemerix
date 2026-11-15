import { test } from 'node:test';
import assert from 'node:assert/strict';
import { summariseNotes, headlineFor, degradedLine } from '../js/notes.js';
import { frameChip, frameMatters } from '../js/flags.js';

const IRSA = 'WISE frame-quality scores did not arrive from IRSA in time, so WISE frames were chosen by coverage alone (frames with unusual noise are still left out) and the 2010 three-band frames, which only that lookup lists, are missing.';
const CATWISE = 'CatWISE2020 sources could not be fetched, so none are marked.';
const NOSPEC = 'Every SPHEREx spectrum point is unusable (357 where the target saturates the detector, 1 where too much of the target is covered by bad pixels), so there is no spectrum to judge.';
const SAT = 'The target saturates some frames (W1, W2, spx-b1); positions there are less reliable.';
const GAIA = 'The spectrum is not classified because a Gaia star comes within one SPHEREx pixel of the target and is not clearly fainter than it, so it may supply much of the light at some wavelengths.';
const GAIA_MAY = 'The SPHEREx spectrum may include light from a Gaia star (G = 16.3) that comes within 5.2 arcsec of the target, less than one SPHEREx pixel.';
const NEOWISE = 'The IRSA search for WISE frames from 2013-2024 (NEOWISE) failed, so those frames are missing.';

test('Barnard-like warnings: four notes, one visible headline', () => {
  const n = summariseNotes([IRSA, NOSPEC, CATWISE, SAT], { degraded: true });
  assert.equal(n.count, 4);
  assert.deepEqual(n.headlines, ['No spectrum: the star saturates SPHEREx.']);
  assert.equal(n.degradedLine, 'Built while an archive service was unavailable; a few 2010 WISE frames and catalogue markers are missing.');
});

test('WISE 0855-like warnings name the neighbouring star', () => {
  const n = summariseNotes([IRSA, CATWISE, GAIA_MAY, GAIA], { degraded: true, hasMatch: false });
  assert.deepEqual(n.headlines, ['Spectrum not classified: a neighbouring star shares the pixel.']);
});

test('a neighbouring star that does not stop the match is still worth a line', () => {
  assert.deepEqual(summariseNotes([GAIA_MAY], { hasMatch: true }).headlines, ['The spectrum may include light from a neighbouring star.']);
  assert.deepEqual(summariseNotes([GAIA_MAY], { hasMatch: false }).headlines, []);
});

test('a failed NEOWISE search is a headline and is named in the degraded line', () => {
  const n = summariseNotes([IRSA, NEOWISE, CATWISE], { degraded: true });
  assert.match(n.headlines[0], /2013 to 2024/);
  assert.equal(n.degradedLine, 'Built while an archive service was unavailable; WISE frames from 2013 to 2024, a few 2010 WISE frames and catalogue markers are missing.');
});

test('live views keep their banner, so no degraded line; clean views have neither', () => {
  assert.equal(summariseNotes([IRSA], { degraded: true, live: true }).degradedLine, null);
  assert.equal(summariseNotes([], {}).degradedLine, null);
  assert.equal(summariseNotes([], {}).count, 0);
  assert.equal(degradedLine(['something odd']), 'Built while an archive service was unavailable, so some data is missing.');
});

test('background warnings give no headline and duplicates collapse', () => {
  assert.equal(headlineFor(CATWISE), null);
  assert.equal(summariseNotes([CATWISE, CATWISE], {}).count, 1);
  assert.equal(headlineFor('2 image(s) could not be loaded and show as “Image missing”.'), '2 image(s) could not be loaded.');
});

test('frame chip: routine notes stay quiet, reading-changing ones get a short label', () => {
  const routine = { flag_fraction: 0.0105, warnings: ['frame quality unknown for 15 frames', 'registered to 7 Gaia stars: frame offset -0.05" E, +0.14" N removed'] };
  assert.equal(frameChip(routine), null);
  const sat = { flag_fraction: 0.04, warnings: ['saturated', 'frame quality unknown for 12 frames', 'saturated core: position measured from the unsaturated wings'] };
  const c = frameChip(sat);
  assert.equal(c.short, 'saturated');
  assert.match(c.long, /saturated core/i);
  assert.deepEqual(frameMatters({ flag_fraction: 0.18, warnings: ['saturated', 'nearest source is a catalogued star, not the target'] }), ['saturated', 'found a known star', '18% flagged']);
  assert.equal(frameChip({ flag_fraction: 0.18, warnings: ['saturated', 'nearest source is a catalogued star, not the target'] }).short, '3 notes');
});
