import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { compassWord, describeMotion, compareMotion, vettingSummary, typeCall, motionBasis } from '../js/summary.js';
import { validateManifest } from '../js/manifest.js';
import { SITE } from '../js/site.js';

const load = (slug) => validateManifest(JSON.parse(readFileSync(new URL(`./fixtures/gallery/${slug}/manifest.json`, import.meta.url)))).manifest;

test('compass words', () => {
  assert.equal(compassWord(0), 'north');
  assert.equal(compassWord(90), 'east');
  assert.equal(compassWord(300), 'north-west');
  assert.equal(compassWord(-10), 'north');
});

test('motion description', () => {
  const d = describeMotion(-8123.7, 673.2, 120);
  assert.match(d.words, /^8\.15 ± 0\.12 arcsec per year toward the west$/);
  assert.match(d.exact, /PA 275°/);
  assert.equal(describeMotion(null, 1), null);
  assert.equal(describeMotion(1, 1).words, 'no measurable motion');
});

test('no direction for a motion within twice its error, a hedged one under three times', () => {
  // R Draconis: 0.02 ± 0.02 arcsec a year.
  assert.equal(describeMotion(-22.27, -11.0, 20.03).words, '0.02 ± 0.02 arcsec per year, too small against its error to give a direction');
  assert.equal(describeMotion(-50, 0, 20).words, '0.05 ± 0.02 arcsec per year toward the west (direction uncertain)');
  assert.equal(describeMotion(-70, 0, 20).words, '0.07 ± 0.02 arcsec per year toward the west');
  assert.equal(describeMotion(-70, 0).words, '0.07 arcsec per year toward the west');
});

test('motion comparison', () => {
  assert.match(compareMotion({ pmra_masyr: -8100, pmdec_masyr: 650, err_masyr: 120 }, { pmra_masyr: -8123.7, pmdec_masyr: 673.2 }), /^Agrees/);
  assert.match(compareMotion({ pmra_masyr: -4000, pmdec_masyr: 0, err_masyr: 50 }, { pmra_masyr: -8000, pmdec_masyr: 0 }), /Differs .* 4\.00 arcsec\/yr \(50%/);
  assert.equal(compareMotion(null, { pmra_masyr: 1, pmdec_masyr: 1 }), null);
  assert.equal(compareMotion({ pmra_masyr: 1, pmdec_masyr: 1 }, { pmra_masyr: null, pmdec_masyr: null }), null);
});

test('star-like matches are called out', () => {
  const m = { verdict: 'Looks like a warm star.', confidence: 'medium', best: { type: 'star (4500 K)' } };
  assert.match(typeCall(m), /not a brown dwarf/);
  assert.match(typeCall(null), /no type call/);
});

test('vetting summary for the full fixture', () => {
  const m = load('synthetic-fast-mover');
  const text = vettingSummary(m, 'https://example.org/?target=synthetic-fast-mover');
  assert.match(text, /^Candidate check: SYNTHETIC fast mover/);
  assert.match(text, /Position: RA 10 00 02\.96, Dec \+20 00 16\.4/);
  assert.match(text, /Measured motion: 2\.9\d ± 0\.\d\d arcsec per year toward the north-west over 1[56]\.\d yr from \d+ detections/);
  assert.match(text, /Agrees with the catalogue motion/);
  assert.match(text, /Spectrum \(SPHEREx\): .*\(high confidence in the class; likely type about Y0\)/);
  assert.match(text, /W1−W2 colour: 3\.30 mag, from CatWISE2020 \(synthetic values\)/);
  assert.match(text, /Reduced proper motion H_W2: 2[12]\.\d mag/);
  assert.match(text, /Synthetic test data/);
  assert.match(text, /Gaia DR3: /);
  assert.match(text, /Spectrum \(SPHEREx\): /);
  assert.match(text, /\d+ of \d+ images carry a quality note\./);
  assert.match(text, new RegExp(`Checked with ${SITE.name} on WISE and SPHEREx images, 20\\d\\d to 20\\d\\d\\.`));
  assert.match(text, /View: https:\/\/example\.org\/\?target=synthetic-fast-mover$/);
});

test('vetting summary for the null fixture', () => {
  const text = vettingSummary(load('synthetic-no-motion'), 'L');
  assert.match(text, /Measured motion: not measured/);
  assert.match(text, /Catalogue motion: unknown/);
  assert.match(text, /no type call/);
  assert.doesNotMatch(text, /Agrees|Differs/);
});

test('vetting summary for the faint fixture gives the reason for no type call', () => {
  const text = vettingSummary(load('synthetic-faint'), 'L');
  assert.match(text, /Spectrum \(SPHEREx\): no type call\. Detected, but too faint to classify/);
  assert.match(text, /Catalogue motion: unknown/);
  assert.doesNotMatch(text, /W1−W2|H_W2/);
});

test('the Talk summary gives the per-pass agreement and leaves out raw fit scores', () => {
  const m = load('synthetic-fast-mover');
  m.match = { ...m.match, delta_chi2: 22.1, per_pass: [{ id: 'a', label: 'A', class: 'brown dwarf', type: 'Y0' }, { id: 'b', label: 'B', class: 'brown dwarf', type: 'Y0' }] };
  const text = vettingSummary(m, 'http://x/');
  assert.doesNotMatch(text, /score gap|delta chi2|22\.1/);
  assert.match(text, /Best template Y0, runner-up /);
  assert.match(text, /All 2 passes agree: Y0\./);
  m.match = { ...m.match, per_pass: [] };
  assert.doesNotMatch(vettingSummary(m, 'http://x/'), /passes/);
});

test('motion headline: agreement in plain words, with the two speeds', async () => {
  const { motionHeadline } = await import('../js/summary.js');
  const h = motionHeadline({ pmra_masyr: 2221.77, pmdec_masyr: 533.17, err_masyr: 6.01, err_pmra_masyr: 6.01, err_pmdec_masyr: 6.0 },
    { pmra_masyr: 2214.2, pmdec_masyr: 536.1 });
  assert.equal(h.text, 'Measured 2.28 arcsec/yr; the catalogue says 2.28: they agree.');
  assert.equal(h.agree, true);
});

test('motion headline: says which component disagrees, neutrally', async () => {
  const { motionHeadline } = await import('../js/summary.js');
  const h = motionHeadline({ pmra_masyr: 3991.1, pmdec_masyr: -2510.18, err_masyr: 5.95, err_pmra_masyr: 5.95, err_pmdec_masyr: 5.95 },
    { pmra_masyr: 3981.977, pmdec_masyr: -2466.832 });
  assert.equal(h.agree, false);
  assert.match(h.text, /^Measured 4\.71 arcsec\/yr; the catalogue says 4\.68\. They differ in the declination \(north-south\) part by 0\.04 arcsec\/yr/);
  assert.equal(motionHeadline(null, { pmra_masyr: 1, pmdec_masyr: 1 }), null);
});

test('a motion fitted on all images at once never claims detections', () => {
  const all = { method: 'all_frames', n_frames: 23, n_detections: 0 };
  const b = motionBasis(all);
  assert.equal(b.allFrames, true);
  assert.equal(b.short, 'from all 23 W2 images fitted at once, as no single image shows the object');
  assert.equal(b.sentence, 'No single image shows the object clearly enough to measure its position, so this motion comes from fitting all 23 W2 images at once');
  assert.match(motionBasis({ method: 'all_frames' }).short, /^from all the W2 images fitted at once/);
  // older manifests have no method: they count detections as before
  assert.deepEqual(motionBasis({ n_detections: 21 }), { allFrames: false, short: 'from 21 detections', sentence: 'From 21 detections' });
  assert.equal(motionBasis({ n_detections: null }).sentence, 'From several detections');
  assert.equal(motionBasis({ n_detections: 0 }).short, '');
});

test('vetting summary of an all-images motion says where the motion comes from', () => {
  const raw = JSON.parse(readFileSync(new URL('./fixtures/gallery/synthetic-fast-mover/manifest.json', import.meta.url)));
  const m = validateManifest({ ...raw, measured_motion: { ...raw.measured_motion, method: 'all_frames', n_frames: 23, n_detections: 0 } }).manifest;
  assert.equal(m.measured_motion.method, 'all_frames');
  assert.equal(m.measured_motion.n_frames, 23);
  const text = vettingSummary(m, 'https://example.org/');
  assert.match(text, /Measured motion: .* yr from all 23 W2 images fitted at once, as no single image shows the object \[/);
  assert.doesNotMatch(text, /detections \[/);
  // a manifest without a method keeps a null method and its detection count
  const old = validateManifest(raw).manifest.measured_motion;
  assert.equal(old.method, null);
  assert.equal(old.n_frames, null);
});
