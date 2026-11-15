import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { decodeStars, magLimit, countBrighter, starRadius, hitTest, labelPosition } from '../js/exploredata.js';
import { typeWords, plainRa, plainDec, pinText, buildHref, viewHref, exploreHref, targetLines, parseExploreQuery } from '../js/exploretext.js';
import { normalise, buildIndex, searchSky } from '../js/exploresearch.js';
import { parseState, viewKind } from '../js/urlstate.js';

const STARS = JSON.parse(readFileSync(new URL('../data/stars.json', import.meta.url)));
const LINES = JSON.parse(readFileSync(new URL('../data/constellation-lines.json', import.meta.url)));

test('star data: a few thousand stars, brightest first, credited, compact', () => {
  assert.ok(STARS.count > 8000 && STARS.count < 12000);
  assert.equal(STARS.ra.length, STARS.count);
  for (let i = 1; i < STARS.mag.length; i++) assert.ok(STARS.mag[i] >= STARS.mag[i - 1]);
  assert.match(STARS.source, /Hipparcos/);
  assert.ok(STARS.fetched && STARS.licence);
  const bytes = readFileSync(new URL('../data/stars.json', import.meta.url)).length;
  assert.ok(bytes < 400 * 1024, `${bytes} bytes`);
});

test('decoded stars: Sirius is first and where it should be', () => {
  const s = decodeStars(STARS);
  assert.ok(Math.abs(s.ra[0] - 101.287) < 0.01 && Math.abs(s.dec[0] + 16.716) < 0.01);
  assert.ok(s.mag[0] < -1.3);
  const sirius = LINES.names.find(([i]) => i === 0);
  assert.equal(sirius[1], 'Sirius');
});

test('constellation lines: all 88, indices inside the star table', () => {
  assert.equal(LINES.constellations.length, 88);
  for (const c of LINES.constellations) for (const poly of c.lines) for (const i of poly) assert.ok(i >= 0 && i < STARS.count);
  assert.match(LINES.licence, /CC BY-SA/);
});

test('Orion\'s label sits in Orion', () => {
  const s = decodeStars(STARS);
  const ori = LINES.constellations.find((c) => c.abbr === 'Ori');
  const p = labelPosition(s, ori.lines);
  assert.ok(p.ra > 75 && p.ra < 95 && p.dec > -10 && p.dec < 15, JSON.stringify(p));
});

test('magnitude limit and star counts by zoom', () => {
  assert.equal(magLimit(360), 5);
  assert.equal(magLimit(5), 6.5);
  const mag = Float32Array.from([-1, 0, 1, 2, 2, 3]);
  assert.equal(countBrighter(mag, 2), 5);
  assert.equal(countBrighter(mag, -2), 0);
  assert.ok(starRadius(-1, 100) > starRadius(5, 100));
  assert.ok(starRadius(4, 5) > starRadius(4, 100));
});

test('hit-testing picks the nearest point inside the radius', () => {
  const pts = [{ x: 10, y: 10 }, null, { x: 14, y: 10 }, { x: 100, y: 100 }];
  assert.equal(hitTest(pts, 13, 10, 8), 2);
  assert.equal(hitTest(pts, 50, 50, 8), -1);
  assert.equal(hitTest(pts, 104, 100, 8), 3);
});

test('pin text is plain and names the constellation', () => {
  assert.equal(plainRa(269.4485), '17h 58m');
  assert.equal(plainRa(359.999), '0h 00m');
  assert.equal(plainDec(4.7394), '+4° 44′');
  assert.equal(plainDec(-56.79), '−56° 47′');
  const p = pinText(83.82, -5.39);
  assert.equal(p.title, 'A patch of sky in Orion');
  assert.equal(p.where, 'RA 5h 35m, Dec −5° 23′');
});

test('links: build here, open a view, open this map', () => {
  assert.equal(buildHref(-10, 12.345678), 'index.html?ra=350.0000&dec=12.3457');
  assert.equal(viewHref('barnards-star'), 'index.html?target=barnards-star');
  assert.equal(exploreHref(10, -20, 30), 'explore.html?ra=10.0000&dec=-20.0000&zoom=30');
});

test('the page query: position, zoom and target, with junk ignored', () => {
  assert.deepEqual(parseExploreQuery('?ra=370&dec=-5&zoom=36'), { ra: 10, dec: -5, fov: 10, target: null, pin: null, known: null });
  assert.deepEqual(parseExploreQuery('?ra=10&dec=95'), { ra: null, dec: null, fov: null, target: null, pin: null, known: null });
  assert.equal(parseExploreQuery('?target=barnards-star').target, 'barnards-star');
  assert.equal(parseExploreQuery('?target=<script>').target, null);
  assert.equal(parseExploreQuery('?zoom=1000').fov, 2);
});

test('card lines use the blurb, our measured motion and the type', () => {
  const t = { blurb: 'Fast.', known_type: 'M4 star', group: 'brief' };
  const lines = targetLines(t, { measured_motion: { pmra_masyr: -799.7, pmdec_masyr: 10379.1 } });
  assert.deepEqual(lines, ['Fast.', 'We measured it moving 10.41 arcsec per year towards the north.', 'A small, cool red star (spectral type M4).']);
  assert.deepEqual(targetLines({ blurb: 'Ice.', group: 'solar-system' }), ['Ice.', 'It drifts against the stars, so the marker shows where it was when we imaged it.']);
});

const INDEX = buildIndex({
  targets: [{ slug: 'barnards-star', name: "Barnard's Star", ra: 269.45, dec: 4.74 }, { slug: 'wise-0855-0714', name: 'WISE 0855-0714', ra: 133.78, dec: -7.24 }],
  stars: [{ name: 'Vega', ra: 279.23, dec: 38.78 }, { name: 'Betelgeuse', ra: 88.79, dec: 7.41 }],
  constellations: [{ name: 'Orion', ra: 83, dec: 3 }, { name: 'Vela', ra: 140, dec: -47 }],
});

test('search finds targets, stars and constellations by name', () => {
  assert.equal(normalise("Barnard’s  Star"), 'barnards star');
  assert.equal(searchSky('barnard', INDEX)[0].slug, 'barnards-star');
  assert.equal(searchSky('wise 0855', INDEX)[0].slug, 'wise-0855-0714');
  assert.equal(searchSky('VEGA', INDEX)[0].label, 'Vega');
  assert.deepEqual(searchSky('ve', INDEX).map((r) => r.label), ['Vega', 'Vela']);
  assert.equal(searchSky('orion', INDEX)[0].kind, 'constellation');
  assert.deepEqual(searchSky('zzz', INDEX), []);
  assert.deepEqual(searchSky('  ', INDEX), []);
});

test('search reads positions in degrees or h m s', () => {
  const [d] = searchSky('83.82 -5.39', INDEX);
  assert.equal(d.kind, 'position');
  assert.ok(Math.abs(d.ra - 83.82) < 1e-9);
  const [h] = searchSky('05 35 17 -05 23 28', INDEX);
  assert.ok(Math.abs(h.ra - 83.8208) < 0.001);
  assert.deepEqual(searchSky('400 0', INDEX), []);
});

test('types in plain words', () => {
  assert.equal(typeWords('T5.5'), 'A brown dwarf (spectral type T5.5).');
  assert.equal(typeWords('d/sdT7.5'), 'An old brown dwarf (spectral type d/sdT7.5).');
  assert.equal(typeWords('Y0 (peculiar)'), 'A brown dwarf (spectral type Y0 (peculiar)).');
  assert.equal(typeWords('M4.5-M6 giant (Mira variable)'), 'A red giant star (spectral type M4.5-M6 giant (Mira variable)).');
  assert.equal(typeWords('K1-K5 young star (T Tauri)'), 'A young star (spectral type K1-K5 young star (T Tauri)).');
  assert.equal(typeWords('Dwarf planet, water ice', 'solar-system'), 'Dwarf planet, water ice.');
  assert.equal(typeWords(null), null);
});

test('a typed minus sign still reads as a position', () => {
  const [r] = searchSky('83.8 \u22125.4', INDEX);
  assert.equal(r.kind, 'position');
  assert.ok(Math.abs(r.dec + 5.4) < 1e-9);
});

test('our links land on a view in the main page, not on the gallery', () => {
  const build = parseState(new URL(buildHref(350, 12.3457), 'http://x').search);
  assert.equal(viewKind(build), 'position');
  assert.equal(build.ra, 350);
  assert.equal(viewKind(parseState(new URL(viewHref('haumea'), 'http://x').search)), 'gallery');
  assert.equal(buildHref(359.99999, 0), 'index.html?ra=0.0000&dec=0.0000');
});
