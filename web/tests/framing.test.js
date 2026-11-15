import { test } from 'node:test';
import assert from 'node:assert/strict';
import { zoomAnchored, clampZoom, viewRect, imageToCanvas, canvasToImage, clampCentre, objectPx, canFollow, offscreenDirection, defaultFraming, shouldAutoFollow } from '../js/framing.js';

const mk = (pts, size = 240) => ({ size_px: size, frames: pts.map((p) => ({ predicted_px: p, centroid_px: null })) });

test('the transform round-trips and puts the view centre mid-canvas', () => {
  const v = viewRect(240, 2, 90, 150, 600);
  assert.deepEqual([v.x0, v.y0, v.w, v.k], [30, 90, 120, 5]);
  assert.deepEqual(imageToCanvas(v, 90, 150), [300, 300]);
  const [x, y] = imageToCanvas(v, 41.3, 120.7);
  const [ix, iy] = canvasToImage(v, x, y);
  assert.ok(Math.abs(ix - 41.3) < 1e-9 && Math.abs(iy - 120.7) < 1e-9);
});

test('the centre is clamped half a view from the edges', () => {
  assert.deepEqual(clampCentre(240, 2, 10, 235), [60, 180]);
  assert.deepEqual(clampCentre(240, 1, 10, 235), [120, 120]);
});

test('the object is the measured spot, else the prediction', () => {
  assert.deepEqual(objectPx({ centroid_px: [1, 2], predicted_px: [3, 4] }), [1, 2]);
  assert.deepEqual(objectPx({ centroid_px: null, predicted_px: [3, 4] }), [3, 4]);
  assert.equal(objectPx({ centroid_px: null, predicted_px: null }), null);
  assert.equal(canFollow([{ centroid_px: null, predicted_px: null }]), false);
  assert.equal(canFollow([{ centroid_px: null, predicted_px: [3, 4] }]), true);
});

test('offscreen direction points from the view centre to the object', () => {
  const v = viewRect(240, 2, 120, 120, 600);
  assert.equal(offscreenDirection(v, 100, 130), null);
  const d = offscreenDirection(v, 200, 120);
  assert.ok(d.dx > 0.99 && Math.abs(d.dy) < 1e-9);
});

test('a path as long as Barnard Star (170 of 240 px) frames at about 1x', () => {
  const f = defaultFraming(mk([[110, 220], [118, 50]]));
  assert.ok(f.zoom >= 1 && f.zoom < 1.5, `zoom ${f.zoom}`);
  assert.equal(f.zoom, f.fitZoom);
  const v = viewRect(240, f.zoom, f.cx, f.cy, 100);
  for (const y of [220, 50]) assert.ok(y > v.y0 && y < v.y0 + v.w);
});

test('a short central path frames at 2x, a very short one allows 3x or 4x to follow', () => {
  const a = defaultFraming(mk([[100, 110], [130, 130]]));
  assert.equal(a.zoom, 2);
  assert.ok(a.fitZoom >= 2);
  const b = defaultFraming(mk([[118, 118], [122, 121]]));
  assert.equal(b.zoom, 2);
  assert.equal(b.fitZoom, 8);
});

test('a path near the image edge never gets a zoom that clips it', () => {
  const f = defaultFraming(mk([[10, 10], [60, 40]]));
  const v = viewRect(240, f.zoom, f.cx, f.cy, 100);
  for (const [x, y] of [[10, 10], [60, 40]]) {
    assert.ok(x > v.x0 && x < v.x0 + v.w && y > v.y0 && y < v.y0 + v.w, `${x},${y} in view at ${f.zoom}x`);
  }
});

test('measured positions count as well as predicted ones', () => {
  const m = { size_px: 240, frames: [{ predicted_px: [120, 120], centroid_px: [120, 120] }, { predicted_px: [120, 121], centroid_px: [30, 200] }, { predicted_px: [150, 60], centroid_px: null }] };
  assert.ok(defaultFraming(m).zoom < 1.7);
});

test('without any position the view is the whole image', () => {
  assert.deepEqual(defaultFraming({ size_px: 240, frames: [{ predicted_px: null, centroid_px: null }] }), { zoom: 1, fitZoom: 1, cx: 120, cy: 120 });
});

test('zooming in past the fitting zoom turns Follow on, only when there is something to follow', () => {
  assert.equal(shouldAutoFollow(1.5, 1, true), true);
  assert.equal(shouldAutoFollow(1, 1, true), false);
  assert.equal(shouldAutoFollow(3, 4, true), false);
  assert.equal(shouldAutoFollow(3, 1, false), false);
});

test('zoom is clamped to 1x-8x and bad numbers fall back to 1x', () => {
  assert.equal(clampZoom(0.2), 1);
  assert.equal(clampZoom(20), 8);
  assert.equal(clampZoom(2.4), 2.4);
  assert.equal(clampZoom(NaN), 1);
});

test('zooming keeps the point under the anchor still, at fractional zoom', () => {
  const [cx, cy] = zoomAnchored(240, 2, 100, 80, 3.3, 0.25, 0.75);
  const v0 = viewRect(240, 2, 100, 80, 100), v1 = viewRect(240, 3.3, cx, cy, 100);
  const at = (v, fx, fy) => [v.x0 + fx * v.w, v.y0 + fy * v.w];
  const [a, b] = [at(v0, 0.25, 0.75), at(v1, 0.25, 0.75)];
  assert.ok(Math.abs(a[0] - b[0]) < 1e-9 && Math.abs(a[1] - b[1]) < 1e-9);
  assert.deepEqual(zoomAnchored(240, 2, 100, 80, 4), [100, 80]); // centre anchor: centre stays
});

test('panning is clamped so the view never leaves the image at fractional zoom', () => {
  const [cx, cy] = clampCentre(240, 2.4, -50, 999);
  assert.ok(Math.abs(cx - 50) < 1e-9 && Math.abs(cy - 190) < 1e-9);
});
