import { test } from 'node:test';
import assert from 'node:assert/strict';
import { constellationOf, precessToB1875 } from '../js/constellation.js';
import { ROMAN_ROWS, CONSTELLATION_NAMES } from '../js/constellation-data.js';

const KNOWN = [
  ["Barnard's Star", 269.45, 4.74, 'Ophiuchus'],
  ['Epsilon Indi', 331.08, -56.79, 'Indus'],
  ['WISE 0855-0714', 133.78, -7.24, 'Hydra'],
  ['2MASS J0415-0935', 63.84, -9.58, 'Eridanus'],
  ['DENIS 0255-4700', 43.77, -47.01, 'Eridanus'],
  ['UGPS 0722-0540', 110.61, -5.67, 'Monoceros'],
  ['R Draconis', 248.17, 66.76, 'Draco'],
  ['RW Aurigae', 76.96, 30.4, 'Auriga'],
  ['Polaris', 37.95, 89.264, 'Ursa Minor'],
  ['Sirius', 101.287, -16.716, 'Canis Major'],
  ['Galactic Centre', 266.405, -28.936, 'Sagittarius'],
  ['RA 0, Dec 0', 0, 0, 'Pisces'],
  ['just east of RA 0', 0.02, 25, 'Pegasus'],
  ['just west of RA 0', 359.98, 25, 'Pegasus'],
  ['RA 0, far south', 0.02, -40, 'Phoenix'],
  ['RA 360, far south', 359.98, -40, 'Phoenix'],
  ['north celestial pole', 0, 90, 'Ursa Minor'],
  ['near the north pole', 200, 89.95, 'Ursa Minor'],
  ['south celestial pole', 0, -90, 'Octans'],
  ['near the south pole', 120, -89.95, 'Octans'],
  ['deep south', 300, -80, 'Octans'],
];

for (const [label, ra, dec, name] of KNOWN) {
  test(`constellation: ${label} is in ${name}`, () => assert.equal(constellationOf(ra, dec).name, name));
}

// Random positions away from any boundary (0.3 degrees), with the answer from astropy's get_constellation.
const ASTROPY = [[225.034, 39.043, 'Boo'], [322.997, -32.126, 'PsA'], [279.247, 4.6, 'Ser'], [81.075, 9.857, 'Ori'], [108.06, -19.892, 'CMa'],
  [314.479, 59.189, 'Cep'], [1.896, -19.617, 'Cet'], [295.642, -20.342, 'Sgr'], [286.945, 22.657, 'Vul'], [168.457, -1.404, 'Leo'],
  [109.092, 26.718, 'Gem'], [100.233, -43.967, 'Pup'], [160.227, 28.171, 'LMi'], [181.637, -12.88, 'Crv'], [199.259, 45.583, 'CVn'],
  [358.38, -32.209, 'Scl'], [356.026, -16.057, 'Aqr'], [77.511, -51.296, 'Pic'], [12.845, 6.406, 'Psc'], [330.18, 30.357, 'Peg'],
  [226.521, 72.531, 'UMi'], [178.874, 48.801, 'UMa'], [249.132, -20.134, 'Oph'], [298.817, -65.718, 'Pav'], [55.606, 49.165, 'Per'],
  [316.92, -6.561, 'Aqr'], [183.525, -45.9, 'Cen'], [304.974, -3.457, 'Aql']];
test('constellation: agrees with astropy on random positions away from boundaries', () => {
  for (const [ra, dec, abbr] of ASTROPY) assert.equal(constellationOf(ra, dec).abbr, abbr, `${ra}, ${dec}`);
});

test('precession to B1875 matches astropy at the equinox and at the Galactic Centre', () => {
  const p = precessToB1875(0, 0);
  // Reference values from astropy's PrecessedGeocentric(equinox='B1875').
  assert.ok(Math.abs(p.ra - 358.398) < 0.01 && Math.abs(p.dec + 0.696) < 0.01, `${p.ra}, ${p.dec}`);
  const gc = precessToB1875(266.405, -28.936);
  assert.ok(Math.abs(gc.ra - 264.4146) < 0.01 && Math.abs(gc.dec + 28.88) < 0.01, `${gc.ra}, ${gc.dec}`);
});

test('the table has 357 rows, covers every band and names all 88 constellations', () => {
  assert.equal(ROMAN_ROWS.length, 357);
  assert.equal(Object.keys(CONSTELLATION_NAMES).length, 88);
  const used = new Set(ROMAN_ROWS.map((r) => r[3]));
  assert.equal(used.size, 88);
  for (const abbr of used) assert.ok(CONSTELLATION_NAMES[abbr], abbr);
  assert.equal(CONSTELLATION_NAMES.Oph, 'Ophiuchus');
  assert.equal(CONSTELLATION_NAMES.Cha, 'Chamaeleon');
});

test('every position on a coarse grid gets a constellation', () => {
  for (let ra = 0; ra < 360; ra += 3) {
    for (let dec = -90; dec <= 90; dec += 3) assert.ok(constellationOf(ra, dec).name, `${ra}, ${dec}`);
  }
});
