import { test } from 'node:test';
import assert from 'node:assert/strict';
import { resolveName, resolveBody, looksLikeName } from '../js/resolve.js';

const reply = (status, body, headers = {}) => async () => ({
  ok: status >= 200 && status < 300, status,
  headers: { get: (k) => headers[k] ?? null },
  json: async () => { if (body === undefined) throw new SyntaxError('bad'); return body; },
});

test('names and coordinates are told apart', () => {
  assert.equal(looksLikeName('WISE 0855-0714'), true);
  assert.equal(looksLikeName("Barnard's Star"), true);
  assert.equal(looksLikeName('M31'), true);
  assert.equal(looksLikeName('08h55m10.83s -07d14m42.5s'), false);
  assert.equal(looksLikeName('08 55 10.83 -07 14 42.5'), false);
  assert.equal(looksLikeName('133.78 -7.24'), false);
});

test('a found name returns position, motion and the service', async () => {
  let asked = '';
  const fetchImpl = async (url) => { asked = url; return reply(200, { resolved: true, name: 'WISE J085510.83-071442.5', ra: 133.78, dec: -7.24, epoch: 2000.0, pmra: -8123.7, pmdec: 673.2, source: 'CDS Sesame' })(); };
  const r = await resolveName(' WISE 0855 ', { apiBase: 'https://api.example.org/', fetchImpl });
  assert.equal(asked, 'https://api.example.org/api/resolve?name=WISE%200855');
  assert.deepEqual(r, { ok: true, name: 'WISE J085510.83-071442.5', ra: 133.78, dec: -7.24, pmra: -8123.7, pmdec: 673.2, epoch: 2000, source: 'CDS Sesame' });
});

test('no proper motion means no epoch either', async () => {
  const r = await resolveName('x', { apiBase: 'A', fetchImpl: reply(200, { resolved: true, ra: 1, dec: 2, pmra: null, pmdec: 3, epoch: null }) });
  assert.equal(r.pmra, null);
  assert.equal(r.pmdec, null);
  assert.equal(r.epoch, null);
  assert.equal(r.source, 'the name service');
});

test('every failure is soft and readable', async () => {
  assert.match((await resolveName('x', { apiBase: '' })).message, /needs the live server/);
  assert.match((await resolveName('x', { apiBase: 'A', fetchImpl: reply(200, { resolved: false, message: 'Could not resolve that name. Enter the coordinates instead.' }) })).message, /^Could not resolve/);
  assert.match((await resolveName('x', { apiBase: 'A', fetchImpl: reply(422, { error: "'name' may contain only letters" }) })).message, /may contain only/);
  assert.match((await resolveName('x', { apiBase: 'A', fetchImpl: reply(429, { error: 'Busy.' }, { 'Retry-After': '30' }) })).message, /^Busy\. Try again in about 30 s\.$/);
  // A visitor never sees an HTTP code: no live server (404) and a failing one (500) are said in words.
  const none = (await resolveName('x', { apiBase: 'A', fetchImpl: reply(404, undefined) })).message;
  assert.match(none, /^This copy of the site shows the built views only/);
  const down = (await resolveName('x', { apiBase: 'A', fetchImpl: reply(500, undefined) })).message;
  assert.match(down, /^The name service is not answering right now/);
  const notFound = (await resolveName('Barnrd', { apiBase: 'A', fetchImpl: reply(200, { resolved: false }) })).message;
  assert.equal(notFound, 'We could not find an object called “Barnrd”. Check the spelling, or enter its coordinates.');
  for (const s of [none, down, notFound]) assert.doesNotMatch(s, /HTTP|\d{3}\)/);
  const body404 = (await resolveBody('x', { apiBase: 'A', fetchImpl: reply(404, undefined) })).message;
  assert.match(body404, /^This copy of the site shows the built views only/);
  assert.match((await resolveName('x', { apiBase: 'A', fetchImpl: reply(200, undefined) })).message, /could not find an object/);
  assert.match((await resolveName('x', { apiBase: 'A', fetchImpl: async () => { throw new TypeError('net'); } })).message, /could not be reached/);
  assert.match((await resolveName('x', { apiBase: 'A', fetchImpl: reply(200, { resolved: true, ra: 400, dec: 0 }) })).message, /could not be read/);
});

test('abort is passed through', async () => {
  const fetchImpl = async () => { throw new DOMException('Aborted', 'AbortError'); };
  await assert.rejects(resolveName('x', { apiBase: 'A', fetchImpl }), { name: 'AbortError' });
});

test('a body name resolves through /api/body/resolve', async () => {
  let asked = '';
  const fetchImpl = async (url) => { asked = url; return reply(200, { resolved: true, designation: '136199', name: 'Eris', kind: 'TNO' })(); };
  const r = await resolveBody(' Eris ', { apiBase: 'https://api.example.org/', fetchImpl });
  assert.equal(asked, 'https://api.example.org/api/body/resolve?name=Eris');
  assert.deepEqual(r, { ok: true, designation: '136199', name: 'Eris', kind: 'TNO' });
});

test('an unknown body comes back with suggestions; failures are soft', async () => {
  const list = [{ designation: '1P', name: '1P/Halley' }, { designation: '2688', name: '<b>' }, 7, { designation: 'x;y', name: 'z' }];
  const r = await resolveBody('Halley', { apiBase: 'A', fetchImpl: reply(200, { resolved: false, message: 'Several bodies match.', did_you_mean: list }) });
  assert.deepEqual(r, { ok: false, message: 'Several bodies match.', suggestions: [{ designation: '1P', name: '1P/Halley' }, { designation: '2688', name: '2688' }] });
  const down = await resolveBody('Eris', { apiBase: 'A', fetchImpl: async () => { throw new TypeError('net'); } });
  assert.equal(down.ok, false);
  assert.deepEqual(down.suggestions, []);
  assert.equal((await resolveBody('Eris', { apiBase: '' })).ok, false);
  const busy = await resolveBody('Eris', { apiBase: 'A', fetchImpl: reply(429, { error: 'Busy.' }, { 'Retry-After': '9' }) });
  assert.equal(busy.message, 'Busy. Try again in about 9 s.');
  const bad = await resolveBody('Eris', { apiBase: 'A', fetchImpl: reply(200, { resolved: true, designation: 'x;rm<', name: 'E' }) });
  assert.equal(bad.ok, false);
});
