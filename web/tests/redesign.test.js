// Pure pieces of the redesign: the one name constant, the scoreboard words, the verdict
// tiles, the missing-WISE wording, and the label placement on the plot and the track.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { SITE, NAV, CREDITS, pageTitle } from '../js/site.js';
import { scoreTiles, cardMarks, notDetected, validationFor } from '../js/scoreboard.js';
import { verdictTiles, isRefusal, bodyOutcome } from '../js/verdict.js';
import { missingWise, missingParts, headlineFor, noTypeWhy } from '../js/notes.js';
import { featureLabels } from '../js/spectrum.js';
import { labelledTicks } from '../js/overlays.js';
import { heroReadout } from '../js/herovisual.js';
import { toolResult, starterLine } from '../js/gallery.js';
import { validateManifest } from '../js/manifest.js';

const WEB = new URL('../', import.meta.url);
const load = (slug) => validateManifest(JSON.parse(readFileSync(new URL(`./fixtures/gallery/${slug}/manifest.json`, import.meta.url)))).manifest;

test('the name lives in js/site.js only: no page or other module spells it out', () => {
  const pages = readdirSync(WEB).filter((f) => f.endsWith('.html'));
  assert.equal(pages.length, 6); // index, validation, planetx, search, explore, status
  for (const f of pages) assert.ok(!readFileSync(new URL(f, WEB), 'utf8').includes(SITE.name), `${f} repeats the name`);
  const js = readdirSync(new URL('js/', WEB)).filter((f) => f.endsWith('.js') && f !== 'site.js');
  for (const f of js) assert.ok(!readFileSync(new URL(`js/${f}`, WEB), 'utf8').includes(SITE.name), `js/${f} repeats the name`);
  assert.equal(pageTitle('How well it works'), `How well it works · ${SITE.name}`);
  assert.equal(pageTitle(), `${SITE.name}: ${SITE.tagline}`);
});

test('every page mounts the shared chrome, and the nav names six places', () => {
  for (const f of ['app.js', 'validation.js', 'planetx.js', 'searchpage.js', 'explore.js', 'status.js']) {
    assert.match(readFileSync(new URL(`js/${f}`, WEB), 'utf8'), /mountChrome\(/, f);
  }
  assert.deepEqual(NAV.map((n) => n.key), ['gallery', 'status', 'explore', 'validation', 'planetx', 'search']);
});

test('the footer credits every data source and service the tool uses', () => {
  const all = CREDITS.join(' ');
  for (const name of ['SPHEREx', 'WISE', 'IRSA', 'Gaia DR3', 'CatWISE2020', 'Astro Data Lab', 'JPL Horizons', 'Small-Body Database', 'Sesame', 'SPIFF', 'Plotly']) {
    assert.ok(all.includes(name), `${name} is not credited`);
  }
});

const SUMMARY = { targets: 17, motion: { passed: 10, failed: 3, total: 13, not_applicable: 4 }, type: { passed: 9, failed: 1, total: 10, refused: 5, not_applicable: 2 }, degraded: 8 };

test('scoreboard strip: the counts come from the report, failures beside the passes', () => {
  const [motion, type, refused] = scoreTiles(SUMMARY);
  assert.deepEqual([motion.value, motion.of, motion.fail], ['10', 'of 13', '3 differ']);
  assert.deepEqual([type.value, type.of, type.fail], ['9', 'of 10', '1 differs']);
  assert.deepEqual([refused.value, refused.fail], ['5', null]);
  assert.equal(scoreTiles({ motion: { passed: 2, failed: 0, total: 2 }, type: {} })[0].fail, null);
  assert.deepEqual(scoreTiles(null).map((t) => t.value), ['0', '0', '0']);
  assert.equal(type.calm, null);
  assert.equal(scoreTiles({ ...SUMMARY, type: { passed: 8, failed: 0, total: 8, refused: 7, provisional: 2 } })[1].calm, '2 provisional');
});

test('gallery marks: agrees, differs, refused, not detected, provisional', () => {
  const v = (motion, type, extra = {}) => ({ motion: { verdict: motion, reason: extra.reason }, type: { verdict: type, provisional: extra.provisional } });
  assert.deepEqual(cardMarks(v('pass', 'pass')), [{ tone: 'pass', text: 'Motion agrees' }, { tone: 'pass', text: 'Type agrees' }]);
  assert.equal(cardMarks({ motion: { verdict: 'pass', weak_test: true }, type: { verdict: 'pass' } })[0].text, 'Motion consistent (weak test)');
  assert.deepEqual(cardMarks(v('fail', 'refused')).map((m) => m.text), ['Motion differs', 'Unclassified']);
  assert.deepEqual(cardMarks(v('not_applicable', 'fail', { reason: 'The target was not detected in any frame, so no motion was measured.' })).map((m) => m.text), ['Not detected', 'Type differs']);
  assert.deepEqual(cardMarks(v('not_applicable', 'not_applicable')).map((m) => m.text), ['No motion check', 'No type check']);
  assert.deepEqual(cardMarks(v('pass', 'pass', { provisional: 'treat the type as provisional' })).at(-1), { tone: 'provisional', text: 'Provisional' });
  assert.deepEqual(cardMarks(null), []);
  const report = { targets: [{ slug: 'a', ...v('not_applicable', 'pass', { reason: 'not detected in any frame' }) }, { slug: 'b', ...v('pass', 'pass') }] };
  assert.equal(notDetected(report.targets).length, 1);
  assert.equal(validationFor(report, 'b').motion.verdict, 'pass');
  assert.equal(validationFor(null, 'b'), null);
});

test('verdict tiles: a typed mover reads motion, type and data at a glance', () => {
  const m = load('synthetic-fast-mover');
  const [motion, spectrum, data] = verdictTiles(m, { published: 'Y0' });
  assert.deepEqual([motion.key, motion.href, motion.tone], ['motion', '#motion', 'good']);
  assert.match(motion.value, /^2\.9\d″ a year$/);
  assert.match(motion.sub, /^agrees with the catalogue \(2\.9\d\)$/);
  assert.deepEqual([spectrum.href, spectrum.value, spectrum.sub, spectrum.tone], ['#spectrum', 'About Y0', 'published: Y0', 'good']);
  assert.equal(verdictTiles(m)[1].sub, 'high confidence');
  assert.equal(data.href, '#data');
  assert.match(data.value, /^\d+ images/);
});

test('verdict tiles: a provisional type keeps its value and is marked calmly, not as a warning', () => {
  const m = load('synthetic-fast-mover');
  const prov = { ...m, match: { ...m.match, provisional: 'A catalogued source 4.9 arcsec away may contribute; treat the type as provisional.' } };
  const t = verdictTiles(prov, { published: 'Y0' })[1];
  assert.deepEqual([t.value, t.sub, t.tone], ['About Y0', 'provisional; published: Y0', 'calm']);
});

test('verdict tiles: a body pass that is only marginal is said calmly; a miss is said plainly', () => {
  const ss = (outcome) => ({ shown_pass: 'a', passes: [{ id: 'a', outcome }, { id: 'b', outcome: 'detected' }], reflectance: [{ band_depths: [{ detected: true }] }] });
  const body = (outcome) => ({ ...load('synthetic-fast-mover'), match: null, solar_system: ss(outcome) });
  assert.equal(bodyOutcome(ss('marginal')), 'marginal');
  assert.equal(bodyOutcome({ passes: [] }), 'detected');
  const marginal = verdictTiles(body('marginal'))[1];
  assert.deepEqual([marginal.value, marginal.tone], ['Marginal detection', 'calm']);
  assert.match(marginal.sub, /one band only/);
  assert.deepEqual([verdictTiles(body('not detected'))[1].value, verdictTiles(body('not detected'))[1].tone], ['Not detected', 'quiet']);
  assert.deepEqual([verdictTiles(body('detected'))[1].value, verdictTiles(body('detected'))[1].tone], ['Ice bands seen', 'good']);
});

test('verdict tiles: no motion and a refusal say so with the reason', () => {
  const faint = load('synthetic-faint');
  assert.equal(isRefusal(faint), true);
  const [motion, spectrum] = verdictTiles(faint);
  assert.deepEqual([spectrum.value, spectrum.tone], ['Unclassified', 'warn']);
  assert.equal(spectrum.sub, 'too faint to classify');
  assert.ok(['Not measured', 'No measurable motion'].includes(motion.value) || /″ a year$/.test(motion.value));
  const blended = { ...faint, measured_motion: null, warnings: ['3 detections are left out of the motion fit because a catalogued source of similar brightness lies within the area the position is fitted over.'] };
  assert.deepEqual([verdictTiles(blended)[0].value, verdictTiles(blended)[0].sub], ['Not measured', '3 detections are left out of the motion fit']);
  const none = load('synthetic-no-motion');
  const tiles = verdictTiles(none);
  assert.equal(tiles[0].tone === 'bad', false);
  const sat = { ...none, match: null, spectra: [{ id: 's', points: [] }], warnings: ['Every SPHEREx spectrum point is unusable (357 where the target saturates the detector), so there is no spectrum to judge.'] };
  assert.equal(isRefusal(sat), false);
  assert.deepEqual([verdictTiles(sat)[1].value, verdictTiles(sat)[1].sub], ['No spectrum', 'the star saturates SPHEREx']);
});

test('verdict tiles: a partial build names what is missing, in the data tile', () => {
  const m = load('synthetic-fast-mover');
  const partial = { ...m, degraded: true, warnings: ['The IRSA search for WISE frames from 2010 (three-band) failed, so those frames are missing.'] };
  const d = verdictTiles(partial)[2];
  assert.equal(d.tone, 'warn');
  assert.match(d.value, /images, partial$/);
  assert.equal(d.sub, 'the 2010 three-band WISE frames are missing');
});

test('a failed WISE search is described by its own phase, never as 2013 to 2024 by default', () => {
  const failed = (phase) => `The IRSA search for WISE frames from ${phase} failed, so those frames are missing.`;
  assert.deepEqual(missingWise(failed('2010 (three-band)')), ['the 2010 three-band WISE frames']);
  assert.deepEqual(missingWise(failed('2010 (cryogenic)')), ['the 2010 cryogenic WISE frames']);
  assert.deepEqual(missingWise(failed('2010-2011 (post-cryogenic)')), ['WISE frames from 2010 to 2011']);
  assert.deepEqual(missingWise(failed('2013-2024 (NEOWISE)')), ['WISE frames from 2013 to 2024']);
  assert.deepEqual(missingWise(failed('2010 (cryogenic), 2010 (three-band)')), ['the 2010 cryogenic WISE frames', 'the 2010 three-band WISE frames']);
  assert.deepEqual(missingWise('CatWISE2020 sources could not be fetched, so none are marked.'), []);
  // Only a gap of years is a headline; one missing 2010 season is not.
  assert.equal(headlineFor(failed('2010 (three-band)')), null);
  assert.equal(headlineFor(failed('2010-2011 (post-cryogenic)')), null);
  assert.match(headlineFor(failed('2013-2024 (NEOWISE)')), /^WISE frames from 2013 to 2024 are missing/);
  assert.deepEqual(missingParts([failed('2010 (three-band)'), 'Catalogue frame-quality scores were unavailable for the WISE frames from 2010 (cryogenic), so those frames were checked by their measured pixel noise instead.']),
    ['the 2010 three-band WISE frames']);
  assert.equal(noTypeWhy(['SPHEREx detects the object at only 12 wavelengths (1.7 to 4.2 µm), which is too little of the spectrum to classify it.'], true), 'too little of the spectrum detected');
});

test('molecule labels: a label that would collide goes to a second row; a narrow plot drops every second one', () => {
  const f = (label, a, b) => ({ label, wl_um: [a, b] });
  const feats = [f('H2O', 1.33, 1.5), f('CH4', 1.55, 1.75), f('CH4', 2.1, 2.4), f('CO', 2.29, 2.4), f('CO2', 4.2, 4.35)];
  const wide = featureLabels(feats);
  assert.deepEqual(wide.map((l) => l.row), [0, 1, 0, 1, 0]);
  assert.deepEqual(featureLabels(feats, true).map((l) => l.text), ['H2O', 'CH4', 'CO2']);
  assert.deepEqual(featureLabels([]), []);
});

test('track labels: first, middle and last tick only', () => {
  assert.deepEqual([...labelledTicks(18)], [0, 9, 17]);
  assert.deepEqual([...labelledTicks(2)], [0, 1]);
  assert.deepEqual([...labelledTicks(1)], [0]);
  assert.equal(labelledTicks(0).size, 0);
});

test('hero readout: measured against catalogue, type against published', () => {
  const m = load('synthetic-fast-mover');
  const [motion, type] = heroReadout(m, 'Y0');
  assert.match(motion.value, /^2\.9\d″ a year$/);
  assert.match(motion.sub, /^catalogue 2\.9\d: agrees$/);
  assert.equal(motion.ok, true);
  assert.deepEqual([type.value, type.sub], ['about Y0', 'published Y0']);
  assert.deepEqual(heroReadout(load('synthetic-no-motion')).filter((r) => /Type/.test(r.label)), []);
});

test('gallery row and starter card: the tool’s answer in plain words', () => {
  const m = load('synthetic-fast-mover');
  const t = { slug: 'x', name: 'X', tool_type: 'Y0', known_type: 'Y0' };
  assert.deepEqual(toolResult(t, m), { text: 'about Y0', why: false });
  assert.equal(starterLine(t, m, { motion: { verdict: 'pass' } }), 'The motion matches the catalogue measurement. The spectrum most closely matches Y0. Astronomers classify this object as Y0.');
  const faint = load('synthetic-faint');
  assert.deepEqual(toolResult({ slug: 'f' }, faint), { text: 'no type: too faint to classify', why: true });
  assert.match(starterLine({ slug: 'f' }, faint, null), /^No reliable spectral type \(too faint to classify\)\.$/);
  const dusty = { ...m, match: { ...m.match, class: 'not a brown dwarf' } };
  assert.deepEqual(toolResult({ ...t, tool_type: 'dust + star (dust 1200 K; star 3500 K)' }, dusty), { text: 'not a brown dwarf', why: false });
});
