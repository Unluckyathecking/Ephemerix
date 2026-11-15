// The first screen of the sky map: the whole sky where the rings stay tappable, otherwise the
// region with the most of our views, and words that say how many are off screen.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { openingView, wholeSkyFits, openingWords } from '../js/exploreopen.js';
import { makeView, project, toVec } from '../js/exploreproj.js';

const GALLERY = JSON.parse(readFileSync(new URL('../gallery/index.json', import.meta.url))).targets;
const INSET = { top: 130, bottom: 70, side: 16 };

const visible = (v, pts, inset) => pts.filter((t) => {
  const p = project(v, toVec(t.ra, t.dec));
  return p.x >= inset.side && p.x <= v.width - inset.side && p.y >= inset.top && p.y <= v.height - inset.bottom;
}).length;

test('a laptop opens on the whole sky; a phone does not', () => {
  assert.equal(wholeSkyFits(1440, 700), true);
  assert.equal(wholeSkyFits(768, 600), true);
  assert.equal(wholeSkyFits(390, 574), false);
});

test('on a phone the opening region holds most of our views, all on screen inside the controls', () => {
  const o = openingView(GALLERY, 390, 574, INSET);
  assert.ok(o.fov < 360);
  const v = makeView({ ...o, width: 390, height: 574 });
  const n = visible(v, GALLERY, INSET);
  assert.equal(n, o.shown);
  assert.ok(n >= 10, `${n} shown`);
});

test('on a laptop the opening shows all 19', () => {
  const o = openingView(GALLERY, 1440, 700, { top: 8, bottom: 8, side: 8 });
  assert.equal(o.shown, 19);
  assert.equal(o.whole, true);
});

test('the opening words say how many more there are', () => {
  assert.equal(openingWords(19, 19), 'All 19 of our built views are on the map: tap an orange ring to watch it move.');
  assert.equal(openingWords(12, 19), '12 of our 19 built views are on screen: tap an orange ring to watch it move, or drag (or press Reset view) for the other 7.');
  assert.equal(openingWords(18, 19), '18 of our 19 built views are on screen: tap an orange ring to watch it move, or drag (or press Reset view) for the other one.');
});
