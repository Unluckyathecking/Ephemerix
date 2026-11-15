import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { validateManifest } from '../js/manifest.js';
import { motionSignificant, vettingSummary } from '../js/summary.js';
import { verdictTiles } from '../js/verdict.js';
import { heroReadout } from '../js/herovisual.js';
import { motionPill, lookFor } from '../js/simplelook.js';

const fast = validateManifest(JSON.parse(readFileSync(new URL('./fixtures/gallery/synthetic-fast-mover/manifest.json', import.meta.url)))).manifest;
// The Galactic-centre case: 0.61 ± 0.95 arcsec a year from 3 detections over a year, no catalogue motion.
const weak = { ...fast, track: [], target: { ...fast.target, pmra_masyr: null, pmdec_masyr: null },
  measured_motion: { ...fast.measured_motion, pmra_masyr: 500, pmdec_masyr: -350, err_masyr: 950, err_pmra_masyr: 950, err_pmdec_masyr: 950, baseline_years: 1.0, n_detections: 3 } };

test('a motion within 3 sigma of zero is not significant', () => {
  assert.equal(motionSignificant(fast.measured_motion), true);
  assert.equal(motionSignificant(weak.measured_motion), false);
  assert.equal(motionSignificant({ pmra_masyr: 30, pmdec_masyr: 0, err_masyr: 10 }), false); // exactly 3 sigma
  assert.equal(motionSignificant({ pmra_masyr: 31, pmdec_masyr: 0, err_masyr: 10 }), true);
  assert.equal(motionSignificant({ pmra_masyr: 5, pmdec_masyr: 0, err_masyr: null }), false); // under 0.01 arcsec a year
  assert.equal(motionSignificant(null), false);
});

test('the verdict strip says "No motion we can measure" with the figure and its error, never the bare number', () => {
  const t = verdictTiles(weak).find((x) => x.key === 'motion');
  assert.equal(t.value, 'No motion we can measure');
  assert.equal(t.sub, '0.61 ± 0.95″ a year, within its error');
  assert.equal(t.tone, 'quiet');
  assert.match(verdictTiles(fast).find((x) => x.key === 'motion').value, /″ a year$/);
});

test('the Talk summary, the hero readout and the simple view use the same rule', () => {
  assert.match(vettingSummary(weak, 'L'), /Measured motion: no motion we can measure \(0\.61 ± 0\.95 arcsec per year, within its error\)/);
  const hero = heroReadout(weak);
  assert.ok(!hero.some((r) => r.value === '0.61″ a year'), JSON.stringify(hero));
  assert.equal(motionPill(weak), null);
  assert.doesNotMatch(lookFor(weak), /drift/);
});
