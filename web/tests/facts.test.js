import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { viewFacts, roundSig, direction, MIN_MOTION_SIGMA } from '../js/facts.js';
import { validateManifest } from '../js/manifest.js';

const load = (slug) => validateManifest(JSON.parse(readFileSync(new URL(`../gallery/${slug}/manifest.json`, import.meta.url)))).manifest;
const titles = (fs) => fs.map((f) => f.title);

function sky(extra = {}) {
  return validateManifest({
    schema: 1, center: { ra: 10, dec: 10 }, size_px: 10, fov_arcsec: 10,
    target: { ra: 10, dec: 10, epoch: 2016, pmra_masyr: 0, pmdec_masyr: 1000 },
    frames: [
      { id: 'a', mission: 'WISE', band: 'W2', image: 'a.png', mjd: 55300, date: '2010-04-14T00:00:00Z' },
      { id: 'b', mission: 'SPHEREx', band: 'spx-b6', image: 'b.png', mjd: 61000, date: '2025-11-25T00:00:00Z' },
    ],
    ...extra,
  }).manifest;
}

test('rounding and direction words', () => {
  assert.equal(roundSig(1800, 2), '1,800');
  assert.equal(roundSig(0.1534, 2), '0.15');
  assert.equal(roundSig(173.6, 2), '170');
  assert.equal(direction(0, 10).word, 'north');
  assert.equal(direction(-10, 0).word, 'west');
  assert.equal(direction(10, 10).word, 'north-east');
});

test("Barnard's Star: Moon crossing, heading, distance, speed, images, SPHEREx date", () => {
  const f = viewFacts(load('barnards-star'));
  assert.deepEqual(titles(f), ['Against the Moon', 'Heading', 'Distance', 'Sideways speed', 'Images', 'Latest look']);
  assert.match(f[0].text, /^Crosses the width of the full Moon in about 170 years\.$/);
  assert.match(f[0].how, /^Our measured motion, 10\.41 ± 0\.01 arcsec a year, from 27 detections over 16 years/);
  assert.equal(f[1].text, 'Moves towards the north of the sky.');
  assert.equal(f[2].text, '6 light-years away.');
  assert.match(f[2].how, /^Gaia DR3 parallax/);
  assert.match(f[3].text, /about 90 km\/s, 3 times Earth's speed/);
  assert.match(f[4].text, /^\d+ images over 1[56] years\.$/);
  assert.match(f[5].text, /^SPHEREx last looked on \d+ \w+ 202\d\.$/);
  for (const x of f) assert.doesNotMatch(`${x.text} ${x.how}`, /—|the tool/);
});

test('the parallax card gives its error to two significant figures, as the co-moving sentence does', () => {
  const d = viewFacts(load('cwise-2029-7910')).find((x) => x.title === 'Distance');
  assert.match(d.how, /^Gaia DR3 parallax, 19\.63 ± 0\.66 mas/);
});

test('motion facts need the motion at MIN_MOTION_SIGMA (5) times its error; the How line uses the headline precision', () => {
  assert.equal(MIN_MOTION_SIGMA, 5);
  // RW Aurigae: 33.8 +- 10.3 mas/yr (3.3 sigma): a motion for the headline, too loose for a Moon crossing.
  const rw = titles(viewFacts(load('rw-aurigae')));
  for (const t of ['Against the Moon', 'Heading', 'Sideways speed']) assert.ok(!rw.includes(t), rw);
  assert.ok(!titles(viewFacts(load('r-draconis'))).includes('Against the Moon'));
  const wise = viewFacts(load('wise-0855-0714'));
  assert.match(wise[0].how, /^Our measured motion, 8\.16 ± 0\.01 arcsec a year/);
  const justUnder = sky({ measured_motion: { pmra_masyr: 0, pmdec_masyr: 49, err_masyr: 10, n_detections: 20, baseline_years: 15 } });
  assert.ok(!titles(viewFacts(justUnder)).includes('Against the Moon'));
  const justOver = sky({ measured_motion: { pmra_masyr: 0, pmdec_masyr: 51, err_masyr: 10, n_detections: 20, baseline_years: 15 } });
  assert.ok(titles(viewFacts(justOver)).includes('Against the Moon'));
});

test('Haumea: distance from the Sun from the solar_system block, no motion facts', () => {
  const f = viewFacts(load('haumea'));
  assert.deepEqual(titles(f), ['From the Sun', 'Images', 'Latest look']);
  assert.match(f[0].text, /^49\.8 au from the Sun: sunlight takes 414 minutes to get there \(about 6\.9 hours\)\.$/);
  assert.match(f[0].how, /JPL Horizons/);
  assert.equal(f[1].text, 'SPHEREx looked 3 times, from 2025 to 2026.');
  assert.match(f[2].text, /^SPHEREx last looked on \d+ \w+ 2026\.$/);
});

test('an insignificant or missing motion gives no motion facts', () => {
  const weak = sky({ measured_motion: { pmra_masyr: 150, pmdec_masyr: 0, err_masyr: 560, n_detections: 2, baseline_years: 1 } });
  assert.deepEqual(titles(viewFacts(weak)), ['Images', 'Latest look']);
  assert.deepEqual(titles(viewFacts(sky())), ['Images', 'Latest look']);
});

test('a weak or missing Gaia parallax gives no distance', () => {
  const mm = { pmra_masyr: 0, pmdec_masyr: 1000, err_masyr: 10, n_detections: 20, baseline_years: 15 };
  const gaia = (plx, err) => ({ gaia: [{ id: '1', ra: 10, dec: 10, epoch: 2016, parallax_mas: plx, parallax_error_mas: err }] });
  assert.ok(!titles(viewFacts(sky({ measured_motion: mm, overlays: gaia(2, 1) }))).includes('Distance'));
  assert.ok(!titles(viewFacts(sky({ measured_motion: mm, overlays: gaia(null, null) }))).includes('Distance'));
  const good = viewFacts(sky({ measured_motion: mm, overlays: gaia(100, 0.1) }));
  assert.deepEqual(titles(good).slice(0, 4), ['Against the Moon', 'Heading', 'Distance', 'Sideways speed']);
  assert.equal(good[2].text, '33 light-years away.');
  assert.match(good[3].text, /about 47 km\/s, 1\.6 times/);
});

test('factsBlock builds one card per fact with a How line', async () => {
  const make = (tag) => ({ tag, children: [], attrs: {}, textContent: '', className: '',
    setAttribute(k, v) { this.attrs[k] = v; }, append(...c) { this.children.push(...c); },
    addEventListener() {} });
  globalThis.document = { createElement: make };
  try {
    const { factsBlock } = await import('../js/facts.js');
    const ul = factsBlock(load('barnards-star'));
    assert.equal(ul.tag, 'ul');
    assert.equal(ul.children.length, 6);
    assert.equal(ul.children[0].children[2].textContent.slice(0, 5), 'How: ');
    assert.equal(factsBlock(null), null);
  } finally {
    delete globalThis.document;
  }
});

test('one image set with no SPHEREx frame and a short span', () => {
  const m = validateManifest({ schema: 1, center: { ra: 1, dec: 1 }, size_px: 10, fov_arcsec: 10,
    frames: [{ id: 'a', mission: 'WISE', band: 'W2', image: 'a.png', mjd: 55300 }] }).manifest;
  assert.deepEqual(viewFacts(m), [{ title: 'Images', text: '1 image.', how: 'Counted from this view: WISE images in 2010.' }]);
  assert.deepEqual(viewFacts(null), []);
});
