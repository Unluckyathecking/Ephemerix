import { test } from 'node:test';
import assert from 'node:assert/strict';
import { makeView, project, unproject, toVec, pan, zoomAt, maxFov, MIN_FOV, crossesSeam, angularSep } from '../js/exploreproj.js';

const near = (a, b, tol, msg) => assert.ok(Math.abs(a - b) <= tol, `${msg ?? ''} ${a} vs ${b}`);
const raDiff = (a, b) => Math.abs(((a - b + 540) % 360) - 180);

test('the view centre lands in the middle of the canvas', () => {
  const v = makeView({ ra: 83.8, dec: -5.4, fov: 30, width: 800, height: 600 });
  const p = project(v, toVec(83.8, -5.4));
  near(p.x, 400, 1e-6); near(p.y, 300, 1e-6);
});

test('north is up and RA increases to the left near the centre', () => {
  const v = makeView({ ra: 100, dec: 20, fov: 20, width: 800, height: 600 });
  const north = project(v, toVec(100, 21));
  const east = project(v, toVec(101, 20));
  assert.ok(north.y < 300, 'north is above the centre');
  near(north.x, 400, 0.5);
  assert.ok(east.x < 400, 'higher RA is to the left');
});

test('scale near the centre is the field width over the canvas width', () => {
  const v = makeView({ ra: 0, dec: 0, fov: 10, width: 1000, height: 600 });
  const p = project(v, toVec(0, 1));
  near(300 - p.y, 100, 0.2, 'one degree is 100 px at 10 degrees across 1000 px');
});

test('project and unproject round-trip anywhere on screen', () => {
  for (const [ra, dec, fov] of [[10, 80, 60], [200, -45, 5], [359, 0, 360], [120, 89.9, 30]]) {
    const v = makeView({ ra, dec, fov, width: 900, height: 500 });
    for (const [x, y] of [[100, 100], [450, 250], [800, 420]]) {
      const s = unproject(v, x, y);
      if (!s) continue;
      const p = project(v, toVec(s.ra, s.dec));
      near(p.x, x, 1e-6); near(p.y, y, 1e-6);
    }
  }
});

test('unproject is null outside the whole-sky ellipse', () => {
  const v = makeView({ ra: 0, dec: 0, fov: 360, width: 800, height: 400 });
  assert.equal(unproject(v, 2, 2), null);
});

test('the whole sky fits the canvas at the widest field', () => {
  for (const [w, h] of [[1440, 800], [390, 640]]) {
    const v = makeView({ ra: 0, dec: 0, fov: maxFov(w, h), width: w, height: h });
    const left = project(v, toVec(179.999, 0)), top = project(v, toVec(0, 90));
    assert.ok(left.x >= 0 && left.x <= w, `edge inside at ${w}x${h}`);
    assert.ok(top.y >= 0, `pole inside at ${w}x${h}`);
  }
});

test('dragging right brings higher RA into the middle and wraps through 0h', () => {
  const v = makeView({ ra: 359, dec: 0, fov: 20, width: 800, height: 600 });
  const moved = pan(v, 80, 0); // 80 px = 2 degrees at this scale
  near(raDiff(moved.ra, 1), 0, 0.01);
  assert.ok(moved.ra >= 0 && moved.ra < 360);
});

test('dragging down shows sky further north, and Dec stops at the pole', () => {
  const v = makeView({ ra: 50, dec: 89, fov: 20, width: 800, height: 600 });
  assert.equal(pan(v, 0, 400).dec, 90);
  near(pan(makeView({ ra: 50, dec: 0, fov: 20, width: 800, height: 600 }), 0, 40).dec, 1, 1e-6);
});

test('zooming at a point keeps that point under the pointer', () => {
  const v = makeView({ ra: 150, dec: 30, fov: 60, width: 800, height: 600 });
  const before = unproject(v, 650, 150);
  const z = zoomAt(v, 2, 650, 150);
  near(z.fov, 30, 1e-9);
  const after = unproject(makeView({ ...z, width: 800, height: 600 }), 650, 150);
  assert.ok(angularSep(before.ra, before.dec, after.ra, after.dec) < 0.05);
});

test('zoom is clamped between a few degrees and the whole sky', () => {
  const v = makeView({ ra: 0, dec: 0, fov: 3, width: 800, height: 600 });
  assert.equal(zoomAt(v, 10, 400, 300).fov, MIN_FOV);
  const w = makeView({ ra: 0, dec: 0, fov: 300, width: 800, height: 600 });
  assert.equal(zoomAt(w, 0.1, 400, 300).fov, maxFov(800, 600));
});

test('a segment crosses the hidden seam only behind the view', () => {
  assert.equal(crossesSeam(170, -175), true);
  assert.equal(crossesSeam(10, -5), false);
  assert.equal(crossesSeam(95, 100), false);
});

test('angular separation', () => {
  near(angularSep(0, 0, 90, 0), 90, 1e-9);
  near(angularSep(10, 89, 190, 89), 2, 1e-9);
});
