// The sky map's second round: the name index markers, live-view links, the motion hint and
// "something that moves".
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { liveHref, knownLines, motionPath, pickMover } from '../js/exploretext.js';
import { nameResults } from '../js/exploresearch.js';
import { buildIndex as buildNameIndex } from '../js/nameindex.js';
import { parseState, viewKind } from '../js/urlstate.js';

const NAMES = JSON.parse(readFileSync(new URL('../data/names.json', import.meta.url)));
const NAME_INDEX = buildNameIndex(NAMES);

test('a live view link carries the position, proper motion and epoch', () => {
  const href = liveHref({ ra: 217.4289422, dec: -62.6794902, pmra: -3781.741, pmdec: 769.465 }, 2000);
  assert.equal(href, 'index.html?ra=217.4289422&dec=-62.6794902&pmra=-3781.741&pmdec=769.465&epoch=2000&fov=240');
  const s = parseState(new URL(href, 'http://x').search);
  assert.equal(viewKind(s), 'position');
  assert.equal(s.pmra, -3781.741);
  assert.equal(liveHref({ ra: 10, dec: 5, label: 'Ross 128' }, 2000), 'index.html?ra=10&dec=5&fov=240&label=Ross+128');
});

test('a named star on the map opens by name, as the search box would', async () => {
  const { nameHref } = await import('../js/exploretext.js');
  assert.equal(nameHref('Betelgeuse'), 'index.html?name=Betelgeuse&from=map');
  assert.equal(parseState(new URL(nameHref('alf Ori'), 'http://x').search).name, 'alf Ori');
});

test('a not-yet-built object says it is built live', () => {
  const lines = knownLines({ kind: 'brown dwarf', sp_type: 'T8' });
  assert.equal(lines[0], 'A brown dwarf (spectral type T8).');
  assert.match(lines.at(-1), /about a minute/);
  assert.equal(knownLines({ kind: 'star', sp_type: null })[0], 'A star.');
});

test('name search reaches the index by any alias, with built views marked', () => {
  const [p] = nameResults(NAME_INDEX, 'gj 551');
  assert.equal(p.label, 'Proxima Centauri');
  assert.equal(p.kind, 'known');
  assert.equal(p.alias, 'GJ 551');
  const [b] = nameResults(NAME_INDEX, 'gliese 699');
  assert.equal(b.kind, 'target');
  assert.equal(b.slug, 'barnards-star');
});

test('the motion hint runs from 2010 to 2026 along the proper motion', () => {
  const [a, b] = motionPath({ ra: 269.452077, dec: 4.693365, pmra: -801.551, pmdec: 10362.394 }, 2000);
  assert.ok(Math.abs((b.dec - a.dec) * 3600 - 10.362394 * 16) < 0.01);
  assert.ok(b.ra < a.ra);
  assert.equal(motionPath({ ra: 1, dec: 1 }, 2000), null);
});

test('"something that moves" picks a built view other than the one open', () => {
  const ts = [{ slug: 'a', pmra: 300, pmdec: 0 }, { slug: 'b', group: 'solar-system' }];
  assert.equal(pickMover(ts, 'a', () => 0).slug, 'b');
  assert.equal(pickMover(ts, null, () => 0.99).slug, 'b');
  assert.equal(pickMover([], null, Math.random), null);
});

test('"something that moves" skips views whose motion is under 0.1 arcsec a year', () => {
  const ts = [{ slug: 'r-draconis', pmra: -20.6, pmdec: 6.1 }, { slug: 'no-pm' }, { slug: 'barnard', pmra: -801.6, pmdec: 10362.4 }];
  assert.equal(pickMover(ts, null, () => 0).slug, 'barnard');
  assert.equal(pickMover(ts, 'barnard', () => 0), null);
});

test('the index has the 34 objects we have not built', () => {
  assert.equal(NAMES.entries.filter((e) => !e.slug).length, 34);
});
