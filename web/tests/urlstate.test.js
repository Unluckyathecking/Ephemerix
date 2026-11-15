import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseState, serializeState, viewKind, emptyState, apiQuery, bodyQuery } from '../js/urlstate.js';

test('gallery state round-trips', () => {
  const s = { ...emptyState(), target: 'wise-0855', frame: 'wise-w2-2010a', bands: ['W2', 'spx-4.6'], spec: 'spx-all', embed: true };
  const q = serializeState(s);
  assert.equal(q, '?target=wise-0855&frame=wise-w2-2010a&bands=W2,spx-4.6&spec=spx-all&embed=1');
  assert.deepEqual(parseState(q), s);
});

test('position state round-trips', () => {
  const s = { ...emptyState(), ra: 133.7835555, dec: -7.244052, pmra: -8123.7, pmdec: 673.2, epoch: 2015.405, fov: 240 };
  const back = parseState(serializeState(s));
  assert.deepEqual(back, s);
  assert.equal(viewKind(back), 'position');
  assert.equal(apiQuery(back), 'ra=133.7835555&dec=-7.244052&pmra=-8123.7&pmdec=673.2&epoch=2015.405&fov=240');
});

test('landing has an empty query', () => {
  assert.equal(serializeState(emptyState()), '');
  assert.equal(viewKind(parseState('')), 'landing');
});

test('malformed values are dropped, not thrown', () => {
  const s = parseState('?ra=abc&dec=95&target=../../etc&frame=<x>&bands=W2,<b>,&embed=yes');
  assert.equal(s.ra, null);
  assert.equal(s.dec, null);
  assert.equal(s.target, null);
  assert.equal(s.frame, null);
  assert.deepEqual(s.bands, ['W2']);
  assert.equal(s.embed, false);
});

test('empty bands list is kept distinct from no bands param', () => {
  assert.deepEqual(parseState('?target=a&bands=').bands, []);
  assert.equal(parseState('?target=a').bands, null);
});

test('preset and compare state round-trip', () => {
  const s = { ...emptyState(), target: 'wise-0855', preset: 'spherex', cmp: 'diff', a: 'spherex-spx-b6-2025p36', b: 'spherex-spx-b6-2026p36' };
  const q = serializeState(s);
  assert.equal(q, '?target=wise-0855&preset=spherex&cmp=diff&a=spherex-spx-b6-2025p36&b=spherex-spx-b6-2026p36');
  assert.deepEqual(parseState(q), s);
});

test('compare mode needs a valid mode; a and b ride only with it', () => {
  assert.equal(parseState('?target=x&cmp=multiply').cmp, null);
  assert.equal(serializeState({ ...emptyState(), target: 'x', a: 'f1', b: 'f2' }), '?target=x');
  assert.equal(parseState('?target=x&preset=../x').preset, null);
  assert.equal(parseState('?target=x&cmp=sum&a=<b>').a, null);
});

test('zoom and follow round-trip; fractional and old integer zooms are accepted, bad ones dropped', () => {
  const s = parseState('?target=x&zoom=2.4&follow=1');
  assert.equal(s.zoom, 2.4);
  assert.equal(s.follow, true);
  assert.equal(serializeState(s), '?target=x&zoom=2.4&follow=1');
  assert.equal(parseState('?target=x&zoom=2').zoom, 2);
  assert.equal(parseState('?target=x&zoom=0.5').zoom, null);
  assert.equal(parseState('?target=x&zoom=99').zoom, null);
  assert.equal(parseState('?target=x&follow=0').follow, false);
  assert.equal(parseState('?target=x&follow=yes').follow, null);
  assert.equal(serializeState(parseState('?target=x')), '?target=x');
});

test('body state round-trips and keeps view keys', () => {
  const s = { ...emptyState(), body: '3I/ATLAS', frame: 'spx-b2-01', zoom: 2, embed: true };
  const q = serializeState(s);
  assert.equal(q, '?body=3I%2FATLAS&frame=spx-b2-01&zoom=2&embed=1');
  const back = parseState(q);
  assert.deepEqual(back, s);
  assert.equal(viewKind(back), 'body');
  assert.equal(bodyQuery(back), 'name=3I%2FATLAS');
});

test('a body name with unsafe characters or too long is dropped', () => {
  assert.equal(parseState('?body=<script>').body, null);
  assert.equal(parseState(`?body=${'a'.repeat(41)}`).body, null);
  assert.equal(parseState('?body=%20%20').body, null);
  assert.equal(parseState('?body=433%20Eros').body, '433 Eros');
  assert.equal(viewKind(parseState('?body=x&ra=1&dec=2')), 'body');
  assert.equal(viewKind(parseState('?target=haumea&body=Eris')), 'gallery');
});
