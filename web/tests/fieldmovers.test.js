import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { cleanFieldMovers, moverName, moverMotion, moverPx, checkLine, withheldLine, comovingLine, comoving } from '../js/fieldmovers.js';
import { validateManifest } from '../js/manifest.js';

// The field_movers blocks of three real builds (scratch rebuilds of gallery targets with the search).
const fix = (slug) => JSON.parse(readFileSync(new URL(`./fixtures/fieldmovers/${slug}.json`, import.meta.url)));
const gallery = (slug) => validateManifest(JSON.parse(readFileSync(new URL(`../gallery/${slug}/manifest.json`, import.meta.url)))).manifest;
const decYear = (mjd) => 2000 + (mjd - 51544.5) / 365.25;

/** A field with a Gaia mover, made from WISE 0855's block (no real gallery field has one yet). */
function withGaia() {
  const fm = structuredClone(fix('wise-0855-0714').field_movers);
  fm.movers.push({ ...fm.movers[0], label: 'gaia', gaia_id: '5765384736386410240', catwise_id: null, px: [40, 60],
    pmra_masyr: 150.2, pmdec_masyr: -310.4, err_masyr: 12.5, motion_arcsec_yr: 0.345, significance: 27.6 });
  fm.n_known = 1;
  fm.sentence = 'We searched this patch for anything else that moved between 2010 and 2024. We found 1 star already known to move and nothing unexplained. The search also picked up the target itself without being told where it is.';
  return fm;
}

test('the real blocks validate; WISE 0855 lists only the target, in plain words', () => {
  const fm = cleanFieldMovers(fix('wise-0855-0714').field_movers);
  assert.equal(fm.status, 'searched');
  assert.equal(fm.movers.length, 1);
  assert.equal(moverName(fm.movers[0]), 'The target itself, found without being told where it is');
  assert.equal(moverMotion(fm.movers[0]), '8.16 ± 0.03 arcsec a year towards the west (the search\'s own fit)');
  assert.equal(checkLine(fm), 'As a check, we shuffled the visit dates 10 times so that nothing real could line up, and the same search then found 0 movers on average and 0 at most.');
  assert.equal(withheldLine(fm), null);
  for (const s of ['barnards-star', 'denis-0255-4700']) assert.equal(cleanFieldMovers(fix(s).field_movers).movers[0].label, 'target');
});

test("the fitted track lands on our measured positions of WISE 0855 (image axes: east left, north up)", () => {
  const fm = cleanFieldMovers(fix('wise-0855-0714').field_movers);
  const m = gallery('wise-0855-0714');
  const scale = m.fov_arcsec / m.size_px;
  const det = m.frames.filter((f) => f.mission === 'WISE' && f.centroid_px);
  assert.ok(det.length > 10);
  for (const f of det) {
    const p = moverPx(fm.movers[0], decYear(f.mjd), scale);
    assert.ok(Math.hypot(p[0] - f.centroid_px[0], p[1] - f.centroid_px[1]) < 3, `${f.id}: ${p} vs ${f.centroid_px}`);
  }
});

test('a known Gaia mover is named with its id and motion', () => {
  const fm = cleanFieldMovers(withGaia());
  assert.equal(moverName(fm.movers[1]), 'Gaia DR3 5765384736386410240, already known to move');
  assert.equal(moverMotion(fm.movers[1]), '0.345 ± 0.01 arcsec a year towards the south-east');
  assert.match(fm.sentence, /1 star already known to move/);
});

test('withheld candidates are counted in words, never listed', () => {
  const raw = { ...withGaia(), n_candidates: 2, candidates_withheld: true };
  raw.movers = [...raw.movers, { ...raw.movers[1], label: 'candidate' }];
  const fm = cleanFieldMovers(raw);
  assert.ok(fm.movers.every((mv) => mv.label !== 'candidate'));
  assert.equal(withheldLine(fm), '2 tracks do not match any catalogue and are not shown, because we cannot yet tell them from noise.');
  assert.equal(withheldLine({ ...fm, n_candidates: 1 }), '1 track does not match any catalogue and is not shown, because we cannot yet tell it from noise.');
});

test('not searched: the reason survives; absent or broken blocks give null', () => {
  const fm = cleanFieldMovers({ status: 'not_searched', reason: 'fewer than 6 WISE visits', movers: [], sentence: 'We could not search this patch for other movers.' });
  assert.equal(fm.status, 'not_searched');
  assert.equal(fm.reason, 'fewer than 6 WISE visits');
  assert.equal(cleanFieldMovers(undefined), null);
  assert.equal(cleanFieldMovers({ movers: 'x' }), null);
  assert.equal(gallery('haumea').field_movers, null);
  const m = validateManifest({ schema: 1, center: { ra: 1, dec: 1 }, size_px: 10, fov_arcsec: 10,
    frames: [{ id: 'a', mission: 'WISE', band: 'W2', image: 'a.png', mjd: 55300 }], field_movers: withGaia() }).manifest;
  assert.equal(m.field_movers.movers.length, 2);
});

test('a catalogued star that shares the target\'s motion is called out, and an unrelated one is not', () => {
  const pair = gallery('cwise-2029-7910');
  const star = pair.field_movers.movers.find((mv) => mv.label === 'gaia');
  const scale = pair.fov_arcsec / pair.size_px;
  const base = 'It moves the same way as the target at the same speed, 34 arcsec away on the sky';
  // Without the Gaia parallaxes, hedged.
  assert.equal(comovingLine(star, pair.field_movers.movers, scale), `${base}, so the two are probably travelling together.`);
  // With them, as in this view (the host star and the target's own Gaia counterpart): one distance.
  assert.deepEqual(comoving(star, pair.field_movers.movers, scale, pair), { distance: 'same',
    line: `${base}, and Gaia puts both at the same distance (parallax 20.12 ± 0.04 mas for this star and 19.63 ± 0.66 mas for the target), so the two travel together.` });
  // A star at another distance shares only the motion.
  const far = { ...pair, overlays: { ...pair.overlays, gaia: pair.overlays.gaia.map((g) => (g.id === star.gaia_id ? { ...g, parallax_mas: 5 } : g)) } };
  assert.deepEqual(comoving(star, pair.field_movers.movers, scale, far), { distance: 'different',
    line: `${base}, but Gaia puts them at different distances (parallax 5.00 ± 0.04 mas for this star and 19.63 ± 0.66 mas for the target), so they share only a motion on the sky.` });
  // A parallax missing on either side: hedged again.
  const none = { ...pair, overlays: { ...pair.overlays, gaia: pair.overlays.gaia.map((g) => (g.id === star.gaia_id ? { ...g, parallax_mas: null } : g)) } };
  assert.equal(comoving(star, pair.field_movers.movers, scale, none).distance, null);
  // A parallax under 5 times its error, or negative, gives no distance: hedged, with no parallaxes printed.
  const withStar = (over) => ({ ...pair, overlays: { ...pair.overlays, gaia: pair.overlays.gaia.map((g) => (g.id === star.gaia_id ? { ...g, ...over } : g)) } });
  for (const over of [{ parallax_mas: 0.1, parallax_error_mas: 0.5 }, { parallax_mas: -0.3, parallax_error_mas: 0.4 }]) {
    assert.deepEqual(comoving(star, pair.field_movers.movers, scale, withStar(over)), { distance: null, line: `${base}, so the two are probably travelling together.` });
  }
  const lone = gallery('2mass-0559-1404');
  const other = lone.field_movers.movers.find((mv) => mv.label === 'gaia');
  assert.equal(comovingLine(other, lone.field_movers.movers, lone.fov_arcsec / lone.size_px), null);
  const target = pair.field_movers.movers.find((mv) => mv.label === 'target');
  assert.equal(comovingLine(target, pair.field_movers.movers, 1), null);
});
