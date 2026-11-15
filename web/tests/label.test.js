import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { parseState, serializeState, viewKind, emptyState, cleanLabel } from '../js/urlstate.js';
import { validateManifest } from '../js/manifest.js';
import { verdictTiles } from '../js/verdict.js';
import { motionSentence } from '../js/simpletext.js';

test('a display label rides with a position view, cleaned and capped, never more than text', () => {
  const s = parseState('?ra=88.79&dec=7.407&label=Betelgeuse');
  assert.equal(s.label, 'Betelgeuse');
  assert.equal(viewKind(s), 'position');
  assert.match(serializeState(s), /&label=Betelgeuse$/);
  assert.equal(cleanLabel('<b>x</b>\u0000\n  y'), '<b>x</b> y');
  assert.equal(cleanLabel('a'.repeat(200)).length, 80);
  assert.equal(cleanLabel('   '), null);
  assert.equal(parseState('?target=barnards-star&label=Foo').label, null); // a gallery view has its own name
});

test('name= asks the page to look a name up, then becomes the resulting view', () => {
  const s = parseState('?name=Betelgeuse');
  assert.equal(viewKind(s), 'name');
  assert.equal(s.name, 'Betelgeuse');
  assert.equal(serializeState({ ...emptyState(), name: 'Betelgeuse' }), '?name=Betelgeuse');
  assert.equal(viewKind(parseState('?name=%20%20')), 'landing');
});

test('a name opens as the search box would: index first, then the live lookup with the same numbers, then a body', async () => {
  const { nameToSearch } = await import('../js/nameopen.js');
  const { buildIndex } = await import('../js/nameindex.js');
  const index = buildIndex(JSON.parse(readFileSync(new URL('../data/names.json', import.meta.url))));
  const reply = (body) => async () => ({ ok: true, status: 200, headers: { get: () => null }, json: async () => body });
  assert.deepEqual(await nameToSearch('Barnard', { index, slugs: new Set(['barnards-star']), apiBase: 'A' }), { search: '?target=barnards-star' });
  const bet = await nameToSearch('betelgeuse', { index, slugs: new Set(), apiBase: 'A',
    fetchImpl: reply({ resolved: true, name: '* alf Ori', ra: 88.79293899, dec: 7.407064, pmra: 27.54, pmdec: 11.3, epoch: 2000, source: 'CDS Sesame' }) });
  assert.equal(bet.search, '?ra=88.792939&dec=7.407064&pmra=27.54&pmdec=11.3&epoch=2000&fov=240&label=betelgeuse');
  const eris = await nameToSearch('Eris', { index, slugs: new Set(), apiBase: 'A', fetchImpl: async (url) => (/body/.test(url)
    ? { ok: true, status: 200, headers: { get: () => null }, json: async () => ({ resolved: true, designation: '136199', name: 'Eris' }) }
    : { ok: true, status: 200, headers: { get: () => null }, json: async () => ({ resolved: false }) }) });
  assert.equal(eris.search, '?body=136199');
  assert.match((await nameToSearch('Nothing 9', { index, slugs: new Set(), apiBase: '' })).message, /live server/);
});

const fast = validateManifest(JSON.parse(readFileSync(new URL('./fixtures/gallery/synthetic-fast-mover/manifest.json', import.meta.url)))).manifest;
const nothing = { ...fast, measured_motion: null, warnings: ['The target was not detected in any frame.'], frames: fast.frames.map((f) => ({ ...f, centroid_px: null })) };

test('nothing visible at a position is said plainly, not as our failure', () => {
  const tile = verdictTiles(nothing).find((t) => t.key === 'motion');
  assert.equal(tile.value, 'Nothing visible here');
  assert.match(tile.sub, /too faint or too blue for WISE and SPHEREx/);
  assert.equal(motionSentence(nothing), 'Nothing is visible at this position in these infrared images. An object can be too faint, or too blue, for WISE and SPHEREx to see.');
  // Found in some frames but too few to fit: unchanged.
  const few = { ...nothing, frames: fast.frames.map((f, i) => ({ ...f, centroid_px: i < 2 ? f.centroid_px : null })) };
  assert.notEqual(verdictTiles(few).find((t) => t.key === 'motion').value, 'Nothing visible here');
});
