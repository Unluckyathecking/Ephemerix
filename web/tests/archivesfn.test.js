import { test } from 'node:test';
import assert from 'node:assert/strict';
import { archives, dayQuery } from '../api/archives.js';

const ENV = { PXS_STATUS_ORIGIN: 'https://status.example.org', PXS_PROXY_SECRET: 'x'.repeat(64) };
const NOW = Date.parse('2026-11-15T12:00:00Z');
const CACHE = 'public, s-maxage=300, stale-while-revalidate=900';

test('unset configuration answers 503, uncached, and never fetches', async () => {
  for (const env of [{}, { PXS_STATUS_ORIGIN: ENV.PXS_STATUS_ORIGIN }, { PXS_PROXY_SECRET: 'x', PXS_STATUS_ORIGIN: 'http://plain.example.org' }]) {
    const res = await archives(env, () => { throw new Error('fetched'); });
    assert.equal(res.status, 503);
    assert.equal(res.headers.get('cache-control'), 'no-store');
  }
});

test('asks the status origin with the secret only, and keeps its cache header', async () => {
  let seen;
  const res = await archives(ENV, async (url, init) => {
    seen = { url: String(url), headers: init.headers };
    return new Response('{"archives":[]}', { status: 200, headers: { 'cache-control': CACHE, 'set-cookie': 'a=b' } });
  });
  assert.equal(seen.url, 'https://status.example.org/api/archives');
  assert.deepEqual(Object.keys(seen.headers).sort(), ['accept', 'x-pxs-proxy-secret']);
  assert.equal(res.status, 200);
  assert.equal(res.headers.get('cache-control'), CACHE);
  assert.equal(res.headers.get('set-cookie'), null);
  assert.equal(await res.text(), '{"archives":[]}');
});

test('only ?day=YYYY-MM-DD is passed on; anything else is a 400 that never reaches the origin', async () => {
  assert.equal(dayQuery(''), '');
  assert.equal(dayQuery('?day=2026-11-14', NOW), '?day=2026-11-14');
  for (const bad of ['?day=x', '?day=2026-11-14&day=2026-11-13', '?other=1', '?day=2026-11-14&x=1']) assert.equal(dayQuery(bad, NOW), null, bad);
  let seen;
  await archives(ENV, async (url) => { seen = String(url); return new Response('{}', { status: 200 }); }, '?day=2026-11-14', NOW);
  assert.equal(seen, 'https://status.example.org/api/archives?day=2026-11-14');
  const res = await archives(ENV, () => { throw new Error('fetched'); }, '?day=../x', NOW);
  assert.equal(res.status, 400);
  const missing = await archives(ENV, async () => new Response('{}', { status: 404 }), '?day=2026-11-01', NOW);
  assert.equal(missing.status, 404);
  assert.equal(missing.headers.get('cache-control'), 'no-store');
});

test('an upstream failure is a 502 that is not cached', async () => {
  for (const f of [async () => new Response('no', { status: 403 }), async () => { throw new TypeError('down'); }]) {
    const res = await archives(ENV, f);
    assert.equal(res.status, 502);
    assert.equal(res.headers.get('cache-control'), 'no-store');
  }
});

test('days outside 31 days back to tomorrow (UTC) are a 400 that never reaches the origin', async () => {
  const ok = ['2026-10-15', '2026-11-15', '2026-11-16'];
  const bad = ['2026-10-14', '2020-01-01', '2026-11-17', '2099-01-01', '2026-02-30'];
  for (const d of ok) assert.equal(dayQuery(`?day=${d}`, NOW), `?day=${d}`, d);
  for (const d of bad) {
    assert.equal(dayQuery(`?day=${d}`, NOW), null, d);
    const res = await archives(ENV, () => { throw new Error('fetched'); }, `?day=${d}`, NOW);
    assert.equal(res.status, 400);
    assert.equal(res.headers.get('cache-control'), 'no-store');
  }
  // the window moves with "now", read at the UTC day boundary
  assert.equal(dayQuery('?day=2026-11-16', Date.parse('2026-11-14T23:59:59Z')), null);
  assert.equal(dayQuery('?day=2026-11-16', Date.parse('2026-11-15T00:00:00Z')), '?day=2026-11-16');
});
