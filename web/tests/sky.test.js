import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { gridOf, skyToPx, pxToSky, propagate, sourcePxAt, decimalYear, motionVector } from '../js/sky.js';
import { validateManifest } from '../js/manifest.js';

const load = (slug) => validateManifest(JSON.parse(readFileSync(new URL(`./fixtures/gallery/${slug}/manifest.json`, import.meta.url)))).manifest;

test('grid centre maps to the middle of the image (edge convention)', () => {
  const g = { ra0: 10, dec0: 20, size: 100, scale: 2 };
  assert.deepEqual(skyToPx(g, 10, 20).map((v) => +v.toFixed(9)), [50, 50]);
});

test('north is up and east is left', () => {
  const g = { ra0: 10, dec0: 20, size: 100, scale: 1 };
  const [, yN] = skyToPx(g, 10, 20 + 10 / 3600);
  assert.ok(Math.abs(yN - 40) < 1e-6);
  const [xE] = skyToPx(g, 10 + 10 / 3600 / Math.cos((20 * Math.PI) / 180), 20);
  assert.ok(Math.abs(xE - 40) < 1e-3);
});

test('pxToSky inverts skyToPx', () => {
  const g = { ra0: 359.99, dec0: -63, size: 240, scale: 1.5 };
  for (const [x, y] of [[0, 0], [12.3, 200.1], [240, 240], [120, 120]]) {
    const s = pxToSky(g, x, y);
    const [x2, y2] = skyToPx(g, s.ra, s.dec);
    assert.ok(Math.abs(x2 - x) < 1e-6 && Math.abs(y2 - y) < 1e-6, `${x},${y} -> ${x2},${y2}`);
  }
});

test('propagation uses cos(dec) at the start declination', () => {
  const p = propagate(100, 60, 2016, 1000, 0, 2017); // 1 arcsec/yr east at dec 60
  assert.ok(Math.abs((p.ra - 100) * 3600 - 2) < 1e-9);
  assert.equal(p.dec, 60);
});

test('decimal year of J2000 MJD', () => {
  assert.equal(decimalYear(51544.5), 2000);
});

test('position angle: east is 90, north is 0', () => {
  assert.equal(Math.round(motionVector(1000, 0).pa), 90);
  assert.equal(Math.round(motionVector(0, 1000).pa), 0);
  assert.equal(Math.round(motionVector(-1000, 0).pa), 270);
});

test('fixture predicted_px matches the pm propagation to within 0.05 px', () => {
  const m = load('synthetic-fast-mover');
  const g = gridOf(m);
  const t = m.target;
  for (const f of m.frames) {
    const p = propagate(t.ra, t.dec, t.epoch, t.pmra_masyr, t.pmdec_masyr, decimalYear(f.mjd));
    const [x, y] = skyToPx(g, p.ra, p.dec);
    assert.ok(Math.abs(x - f.predicted_px[0]) < 0.05 && Math.abs(y - f.predicted_px[1]) < 0.05, f.id);
  }
  for (const pt of m.track) {
    const p = propagate(t.ra, t.dec, t.epoch, t.pmra_masyr, t.pmdec_masyr, pt.year);
    const [x, y] = skyToPx(g, p.ra, p.dec);
    assert.ok(Math.abs(x - pt.px[0]) < 0.05 && Math.abs(y - pt.px[1]) < 0.05, `track ${pt.year}`);
  }
});

test('a high-pm Gaia source moves the expected number of pixels between frames', () => {
  const m = load('synthetic-fast-mover');
  const g = gridOf(m);
  const src = m.overlays.gaia.find((s) => Math.hypot(s.pmra_masyr, s.pmdec_masyr) > 300);
  assert.ok(src);
  const a = sourcePxAt(g, src, 2010), b = sourcePxAt(g, src, 2020);
  const expectedPx = (Math.hypot(src.pmra_masyr, src.pmdec_masyr) * 10) / 1000 / g.scale;
  assert.ok(Math.abs(Math.hypot(b[0] - a[0], b[1] - a[1]) - expectedPx) < 0.05);
  assert.ok(b[0] < a[0], 'positive pmra moves east, i.e. left');
});
