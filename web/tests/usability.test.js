import { test } from 'node:test';
import assert from 'node:assert/strict';
import { playingPair, pairCaption } from '../js/compare.js';
import { needsScroll } from '../js/keepinview.js';
import { isBrownDwarf, stripNote, STRIP_LEAD } from '../js/striptext.js';

const f = (id, band, mjd, found = true) => ({ id, band, mjd, date: `d${id}`, centroid_px: found ? [1, 1] : null });

test('compare opens on the earliest and latest frame of the playing set with the longest span', () => {
  // The default blink: WISE W2 2010-2024 and one SPHEREx band 2025-2026.
  const playing = [f('w0', 'W2', 55320), f('w1', 'W2', 58000), f('w2', 'W2', 60416), f('s0', 'spx-b6', 60800), f('s1', 'spx-b6', 61157)];
  assert.deepEqual(playingPair(playing).map((x) => x.id), ['w0', 'w2']);
});

test('among sets a year long, compare prefers the one whose ends show the object', () => {
  const playing = [f('a0', 'spx-b2', 60800, false), f('a1', 'spx-b2', 61165, false), f('b0', 'spx-b5', 60801), f('b1', 'spx-b5', 61160)];
  assert.deepEqual(playingPair(playing).map((x) => x.id), ['b0', 'b1']);
});

test('compare has no opening pair when no playing set has two frames', () => {
  assert.equal(playingPair([f('a', 'W2', 1), f('b', 'spx-b6', 2)]), null);
  assert.equal(playingPair([]), null);
});

test('the caption names both dates and how far apart they are', () => {
  const fmt = (d) => d.toUpperCase();
  assert.equal(pairCaption(f('a', 'W2', 55320), f('b', 'W2', 60416), 'diff', 'WISE W2 (4.6 µm)', fmt),
    'B − A: A is DA, B is DB, 14 years apart, WISE W2 (4.6 µm).');
  assert.match(pairCaption(f('a', 'x', 60800), f('b', 'x', 61157), 'sum', 'L', fmt), /^A \+ B \(mean\): .*12 months apart, L\.$/);
});

test('the image is brought back only when most of it is off screen', () => {
  assert.equal(needsScroll(-288, 205, 900), true);   // laptop, after a click under the image
  assert.equal(needsScroll(-183, 141, 844), true);   // phone
  assert.equal(needsScroll(20, 500, 900), false);    // in view
  assert.equal(needsScroll(-100, 400, 900), true);   // top edge (date, set name) cut off
  assert.equal(needsScroll(300, 800, 900), false);   // below the fold a little: leave the page alone
  assert.equal(needsScroll(700, 1200, 900), true);   // mostly below the fold
  assert.equal(needsScroll(0, 0, 900), false);       // not laid out
});

test('the methane line shows for brown dwarfs only', () => {
  assert.equal(isBrownDwarf('Y4 (adopted estimate)', null), true);
  assert.equal(isBrownDwarf('sdT3', null), true);
  assert.equal(isBrownDwarf('d/sdL9', null), true);
  assert.equal(isBrownDwarf('M4 star', 'brown dwarf'), false);
  assert.equal(isBrownDwarf('Dwarf planet, methane ice', null), false);
  assert.equal(isBrownDwarf('K1-K5 young star (T Tauri)', null), false);
  assert.equal(isBrownDwarf(null, 'brown dwarf'), true);
  assert.equal(isBrownDwarf(null, null), false);
  assert.match(stripNote(true), /methane absorbs.*Click a band to blink it over time\.$/);
  assert.equal(stripNote(false), 'Click a band to blink it over time.');
  assert.match(STRIP_LEAD, /six detector arrays/);
});

test('a mode in the URL is a choice to remember; Simple never shows the hint', async () => {
  const { urlChoice, shouldHint } = await import('../js/mode.js');
  assert.equal(urlChoice('?target=x&mode=simple'), 'simple');
  assert.equal(urlChoice('?mode=advanced'), 'advanced');
  assert.equal(urlChoice('?mode=full'), 'advanced');
  assert.equal(urlChoice('?target=x'), null);
  assert.equal(urlChoice('?mode=bogus'), null);
  assert.equal(shouldHint({ stored: null, hinted: false, mode: 'simple' }), false);
  assert.equal(shouldHint({ stored: null, hinted: false, mode: 'advanced' }), true);
});
