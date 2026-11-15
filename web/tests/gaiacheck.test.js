import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { gaiaCounterpart } from '../js/gaiacheck.js';
import { validateManifest } from '../js/manifest.js';

const real = (slug) => validateManifest(JSON.parse(readFileSync(new URL(`../gallery/${slug}/manifest.json`, import.meta.url)))).manifest;

const base = (patch = {}) => ({
  target: { ra: 10, dec: 0, epoch: 2016, pmra_masyr: 1000, pmdec_masyr: 0 },
  overlays: { gaia: [], catwise: [] }, warnings: [], measured_motion: null, match: null, vetting: null, ...patch,
});
const src = (dra, pm = [1000, 0], g = 18.04) => ({ id: '42', ra: 10 + dra / 3600, dec: 0, epoch: 2016, pmra_masyr: pm[0], pmdec_masyr: pm[1], g_mag: g });

test('real gallery: Gaia sees the targets it should, and not the cold ones', () => {
  assert.equal(gaiaCounterpart(real('epsilon-indi-b')).status, 'match');
  assert.match(gaiaCounterpart(real('epsilon-indi-b')).text, /G = 18\.0, with the same motion/);
  assert.equal(gaiaCounterpart(real('barnards-star')).status, 'match');
  assert.equal(gaiaCounterpart(real('denis-0255-4700')).status, 'match');
  // UGPS 0722 lies in a crowded field whose Gaia list stops at G 19.3: absence holds only that far.
  const u = gaiaCounterpart(real('ugps-0722-0540'));
  assert.equal(u.status, 'limited');
  assert.match(u.text, /^No Gaia DR3 source brighter than G = 19\.3 within 2″/);
  for (const slug of ['2mass-0415-0935', 'wise-0855-0714']) {
    const r = gaiaCounterpart(real(slug));
    assert.equal(r.status, 'none', slug);
    assert.match(r.text, /^No Gaia DR3 source within 2″ of where the target was at the Gaia epoch \(2016\)/);
  }
  // WISE 0855 is refused a type, but its W1−W2 is a cold brown dwarf's.
  assert.match(gaiaCounterpart(real('wise-0855-0714')).text, /as expected for a cold brown dwarf/);
  assert.equal(gaiaCounterpart(real('haumea')), null);
});

test('target moved to the Gaia epoch before matching', () => {
  // 2 arcsec/yr east from 2015: at 2016 it is 2" east of its catalogue position.
  const m = base({ target: { ra: 10, dec: 0, epoch: 2015, pmra_masyr: 2000, pmdec_masyr: 0 }, overlays: { gaia: [src(2, [2000, 0])], catwise: [] } });
  assert.equal(gaiaCounterpart(m).status, 'match');
  assert.match(gaiaCounterpart(m).text, /sits 0\.0″/);
});

test('falls back to the measured motion, else says it cannot check', () => {
  const t = { ra: 10, dec: 0, epoch: 2015, pmra_masyr: null, pmdec_masyr: null };
  const m = base({ target: t, overlays: { gaia: [src(2, [2000, 0])], catwise: [] }, measured_motion: { pmra_masyr: 2000, pmdec_masyr: 0 } });
  assert.equal(gaiaCounterpart(m).status, 'match');
  assert.equal(gaiaCounterpart({ ...m, measured_motion: null }).status, 'unchecked');
});

test('a coincident star with different motion is called unrelated', () => {
  const r = gaiaCounterpart(base({ overlays: { gaia: [src(0.5, [3, -2])], catwise: [] } }));
  assert.equal(r.status, 'unrelated');
  assert.match(r.text, /probably an unrelated star/);
});

test('Gaia query failure or a capped list is never read as absence', () => {
  const failed = base({ warnings: ['Gaia DR3 sources could not be fetched, so none are marked.'] });
  assert.equal(gaiaCounterpart(failed).status, 'unchecked');
  // A degraded view for other reasons (CatWISE) is still checked.
  const cat = base({ degraded: true, warnings: ['CatWISE2020 sources could not be fetched, so none are marked.'] });
  assert.equal(gaiaCounterpart(cat).status, 'none');
  const capped = base({ overlays: { gaia: Array.from({ length: 120 }, (_, i) => src(30, [0, 0], 15 + i / 40)), catwise: [] } });
  assert.equal(gaiaCounterpart(capped).status, 'limited');
  assert.match(gaiaCounterpart(capped).text, /brighter than G = 18\.0/);
});

test('a position with no epoch is compared as given, and says so', () => {
  const m = base({ target: { ra: 10, dec: 0, epoch: null, pmra_masyr: null, pmdec_masyr: null } });
  assert.match(gaiaCounterpart(m).text, /no stated epoch/);
  const hit = { ...m, overlays: { gaia: [src(0.3)], catwise: [] } };
  assert.equal(gaiaCounterpart(hit).status, 'match');
  assert.match(gaiaCounterpart(hit).text, /sits 0\.3″ from the position as given \(it has no stated epoch, so it was not moved to Gaia's 2016\), G = 18\.0/);
});

test('the cold-brown-dwarf reason only when the manifest supports it', () => {
  assert.doesNotMatch(gaiaCounterpart(base()).text, /brown dwarf/);
  assert.match(gaiaCounterpart(base({ match: { class: 'brown dwarf' } })).text, /cold brown dwarf/);
  assert.match(gaiaCounterpart(base({ vetting: { w1_w2: 0.2 } })).text, /about G = 21/);
});
