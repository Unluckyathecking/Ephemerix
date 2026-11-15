import { test } from 'node:test';
import assert from 'node:assert/strict';
import { eqToGal, galToEq, eqToEcl, eclToEq, hammer, hammerInverse, skyToChart, chartToSky,
  HAMMER_HALF_WIDTH, HAMMER_HALF_HEIGHT, OBLIQUITY } from '../js/skymath.js';
import { toSvg, runs, curveD, galacticBandD, eclipticD, graticuleD, CENTER, HALF_W, HALF_H } from '../js/allskypaths.js';

const near = (a, b, tol, msg) => assert.ok(Math.abs(a - b) <= tol, `${msg || ''} ${a} vs ${b}`);
const angDiff = (a, b) => { const d = Math.abs(a - b) % 360; return Math.min(d, 360 - d); };

test('the Galactic Centre is at l = 0, b = 0', () => {
  const g = eqToGal(266.405, -28.936);
  near(angDiff(g.l, 0), 0, 0.01, 'l');
  near(g.b, 0, 0.01, 'b');
});

test('the north galactic pole is at b = +90', () => {
  near(eqToGal(192.859, 27.128).b, 90, 0.01);
});

test('Sirius and Polaris galactic coordinates (values from astropy)', () => {
  const s = eqToGal(101.287155, -16.716116);
  near(s.l, 227.23, 0.01); near(s.b, -8.89, 0.01);
  const p = eqToGal(37.954, 89.264);
  near(p.l, 123.28, 0.05); near(p.b, 26.46, 0.05);
});

test('galactic to equatorial inverts equatorial to galactic everywhere', () => {
  for (let ra = 0; ra < 360; ra += 17) {
    for (let dec = -85; dec <= 85; dec += 11) {
      const g = eqToGal(ra, dec);
      const e = galToEq(g.l, g.b);
      near(angDiff(e.ra, ra), 0, 1e-9, `ra ${ra},${dec}`);
      near(e.dec, dec, 1e-9);
    }
  }
});

test('the Galactic Centre in equatorial coordinates', () => {
  const e = galToEq(0, 0);
  near(e.ra, 266.405, 0.01); near(e.dec, -28.936, 0.01);
});

test('ecliptic latitude: the ecliptic pole, the equinox and the solstice', () => {
  near(eqToEcl(270, 90 - OBLIQUITY).lat, 90, 1e-9);
  const equinox = eqToEcl(0, 0);
  near(equinox.lat, 0, 1e-9); near(equinox.lon, 0, 1e-9);
  const solstice = eqToEcl(90, OBLIQUITY);
  near(solstice.lat, 0, 1e-9); near(solstice.lon, 90, 1e-9);
});

test('ecliptic latitude agrees with astropy for Barnard\'s Star and Sirius', () => {
  near(eqToEcl(269.4485, 4.7394).lat, 28.1775, 0.01);
  near(eqToEcl(101.287155, -16.716116).lat, -39.605, 0.01);
});

test('ecliptic to equatorial inverts equatorial to ecliptic', () => {
  for (let lon = 0; lon < 360; lon += 23) {
    for (let lat = -80; lat <= 80; lat += 20) {
      const e = eclToEq(lon, lat);
      const back = eqToEcl(e.ra, e.dec);
      near(angDiff(back.lon, lon), 0, 1e-9); near(back.lat, lat, 1e-9);
    }
  }
});

test('Hammer-Aitoff: centre, poles and the edge of the map', () => {
  near(hammer(0, 0).x, 0, 1e-12); near(hammer(0, 0).y, 0, 1e-12);
  near(hammer(0, 90).y, HAMMER_HALF_HEIGHT, 1e-12);
  near(hammer(0, 90).x, 0, 1e-12);
  near(hammer(180, 0).x, HAMMER_HALF_WIDTH, 1e-12);
  near(hammer(-180, 0).x, -HAMMER_HALF_WIDTH, 1e-12);
  const e = hammer(90, 30);
  near(e.x, 1.3640, 1e-3); near(e.y, 0.5569, 1e-3);
});

test('Hammer-Aitoff round trip, and null outside the ellipse', () => {
  for (let lon = -175; lon <= 175; lon += 25) {
    for (let lat = -85; lat <= 85; lat += 17) {
      const h = hammer(lon, lat);
      const back = hammerInverse(h.x, h.y);
      near(back.lon, lon, 1e-9, 'lon'); near(back.lat, lat, 1e-9, 'lat');
    }
  }
  assert.equal(hammerInverse(2.9, 0), null);
  assert.equal(hammerInverse(0, 1.5), null);
  assert.equal(hammerInverse(2.4, 1.0), null);
});

test('Hammer-Aitoff keeps areas: equal-area cells project to equal areas', () => {
  // The map covers 4*pi*(1/2) of area in these units: an ellipse of area pi * 2*sqrt(2) * sqrt(2) = 4 pi.
  // Check the Jacobian numerically at several points: the area of a small lon/lat cell scales as cos(lat).
  const cell = (lon, lat) => {
    const d = 0.01;
    const a = hammer(lon, lat), b = hammer(lon + d, lat), c = hammer(lon, lat + d);
    return Math.abs((b.x - a.x) * (c.y - a.y) - (c.x - a.x) * (b.y - a.y)) / (d * d * Math.cos(lat * Math.PI / 180));
  };
  const ref = cell(0, 0);
  for (const [lon, lat] of [[40, 20], [-120, -50], [100, 70], [-30, 5]]) near(cell(lon, lat) / ref, 1, 0.01, `${lon},${lat}`);
});

test('sky chart: RA 12h in the middle, RA increasing to the left, north up', () => {
  near(skyToChart(180, 0).x, 0, 1e-12); near(skyToChart(180, 0).y, 0, 1e-12);
  assert.ok(skyToChart(270, 0).x < 0, '18h is left of the centre');
  assert.ok(skyToChart(90, 0).x > 0, '6h is right of the centre');
  assert.ok(skyToChart(180, 40).y > 0, 'north is up');
  near(skyToChart(0.0001, 0).x, HAMMER_HALF_WIDTH, 1e-3);
  near(skyToChart(359.9999, 0).x, -HAMMER_HALF_WIDTH, 1e-3);
});

test('sky chart round trip', () => {
  for (const [ra, dec] of [[269.45, 4.74], [63.84, -9.58], [0.5, 80], [359.5, -60], [180, 0]]) {
    const c = skyToChart(ra, dec);
    const back = chartToSky(c.x, c.y);
    near(angDiff(back.ra, ra), 0, 1e-9); near(back.dec, dec, 1e-9);
  }
});

test('svg position stays inside the map ellipse and matches the layout', () => {
  const p = toSvg(180, 0);
  near(p.x, CENTER.x, 1e-9); near(p.y, CENTER.y, 1e-9);
  for (const [ra, dec] of [[0.001, 0], [359.999, 0], [10, 89], [10, -89], [269.45, 4.74]]) {
    const q = toSvg(ra, dec);
    const r = ((q.x - CENTER.x) / HALF_W) ** 2 + ((q.y - CENTER.y) / HALF_H) ** 2;
    assert.ok(r <= 1.0001, `${ra},${dec} outside the map`);
  }
  assert.ok(toSvg(270, 0).x < CENTER.x);
  assert.ok(toSvg(0, 60).y < CENTER.y);
});

test('curves are broken at the map edge, not drawn across it', () => {
  const across = [{ ra: 10, dec: 20 }, { ra: 5, dec: 20 }, { ra: 355, dec: 20 }, { ra: 350, dec: 20 }];
  assert.equal(runs(across).length, 2);
  assert.equal(curveD(across).split('M').length - 1, 2);
});

test('path data: the band, ecliptic and graticule are drawn and stay finite', () => {
  for (const d of [galacticBandD(10), galacticBandD(20), eclipticD(), graticuleD()]) {
    assert.ok(d.startsWith('M') && d.length > 200);
    assert.ok(!/NaN|undefined|Infinity/.test(d));
  }
  // The plane crosses the RA 0h edge, so the band is more than one polygon.
  assert.ok(galacticBandD(10).split('Z').length - 1 >= 2);
});
