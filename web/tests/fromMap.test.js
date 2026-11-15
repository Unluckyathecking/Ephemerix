import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { parseState, serializeState, viewKind } from '../js/urlstate.js';
import { nameHref, parseExploreQuery, exploreCardParams } from '../js/exploretext.js';
import { nameToSearch } from '../js/nameopen.js';
import { buildIndex } from '../js/nameindex.js';

test('a named star from the map carries its own position as a fallback, and says it came from the map', () => {
  const href = nameHref('Muliphen', { ra: 105.9396, dec: -15.6333 });
  assert.equal(href, 'index.html?name=Muliphen&at=105.9396,-15.6333&from=map');
  const s = parseState(new URL(href, 'http://x').search);
  assert.equal(viewKind(s), 'name');
  assert.deepEqual(s.at, { ra: 105.9396, dec: -15.6333, pmra: null, pmdec: null, epoch: null });
  assert.equal(s.from, 'map');
  assert.equal(serializeState(s), '?name=Muliphen&at=105.9396,-15.6333&from=map');
  assert.equal(nameHref('Vega'), 'index.html?name=Vega&from=map');
  // Junk positions are dropped; only 'map' is a known origin.
  assert.equal(parseState('?name=X&at=999,1').at, null);
  assert.equal(parseState('?target=x&from=elsewhere').from, null);
  assert.match(serializeState(parseState('?target=x&from=map')), /from=map/);
});

const index = buildIndex(JSON.parse(readFileSync(new URL('../data/names.json', import.meta.url))));
const down = async () => ({ ok: false, status: 503, headers: { get: () => null }, json: async () => ({ error: 'The name service is down.' }) });

test('when the name lookup fails, the map\'s own position opens, labelled with the name', async () => {
  const r = await nameToSearch('Muliphen', { index, slugs: new Set(), apiBase: 'A', fetchImpl: down,
    fallback: { ra: 105.9396, dec: -15.6333, pmra: null, pmdec: null, epoch: null } });
  assert.equal(r.search, '?ra=105.9396&dec=-15.6333&fov=240&label=Muliphen');
  const off = await nameToSearch('Muliphen', { index, slugs: new Set(), apiBase: '', fallback: { ra: 105.9396, dec: -15.6333, pmra: 1, pmdec: 2, epoch: 2000 } });
  assert.equal(off.search, '?ra=105.9396&dec=-15.6333&pmra=1&pmdec=2&epoch=2000&fov=240&label=Muliphen');
  assert.ok((await nameToSearch('Muliphen', { index, slugs: new Set(), apiBase: 'A', fetchImpl: down })).message);
});

test('the map writes its card into its own address, so Back and the way back restore it', () => {
  assert.deepEqual(exploreCardParams({ selected: { slug: 'barnards-star' } }), { target: 'barnards-star' });
  assert.deepEqual(exploreCardParams({ selected: { entry: { label: 'Proxima Centauri' } } }), { known: 'Proxima Centauri' });
  assert.deepEqual(exploreCardParams({ pin: { ra: 105.93961, dec: -15.63331 } }), { pin: '105.9396,-15.6333' });
  assert.deepEqual(exploreCardParams({}), {});
  const q = parseExploreQuery('?ra=100&dec=-10&zoom=4&pin=105.9396,-15.6333');
  assert.deepEqual(q.pin, { ra: 105.9396, dec: -15.6333 });
  assert.equal(parseExploreQuery('?known=Proxima%20Centauri').known, 'Proxima Centauri');
  assert.equal(parseExploreQuery('?pin=junk').pin, null);
});
