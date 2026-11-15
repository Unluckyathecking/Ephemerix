import { test } from 'node:test';
import assert from 'node:assert/strict';
import middleware, {
  config, downstreamHeaders, upstreamHeaders, upstreamOrigin, upstreamUrl,
} from '../middleware.js';

const ORIGIN = 'https://api.example.org';
const SECRET = 'x'.repeat(64);

test('runs only on /api/*', () => {
  assert.deepEqual(config, { matcher: ['/api', '/api/((?!archives$).*)'], runtime: 'nodejs' });
});

test('the service origin must be an https origin', () => {
  assert.equal(upstreamOrigin('https://api.example.org/some/path'), ORIGIN);
  assert.equal(upstreamOrigin(undefined), null);
  assert.equal(upstreamOrigin(''), null);
  assert.equal(upstreamOrigin('http://api.example.org'), null);
  assert.equal(upstreamOrigin('api.example.org'), null);
});

test('the upstream URL keeps path and query and never leaves the origin', () => {
  assert.equal(upstreamUrl('https://site.example/api/view?ra=1&dec=2', ORIGIN).href,
    `${ORIGIN}/api/view?ra=1&dec=2`);
  assert.equal(upstreamUrl('https://site.example/api//evil.com/x', ORIGIN).origin, ORIGIN);
  assert.equal(upstreamUrl('https://site.example/index.html', ORIGIN), null);
  assert.equal(upstreamUrl('https://site.example/apix', ORIGIN), null);
});

test('request headers: allow-list only, inbound private headers replaced', () => {
  const h = upstreamHeaders(new Headers({
    accept: 'application/json',
    cookie: 'a=b',
    authorization: 'Bearer t',
    'accept-encoding': 'gzip',
    'x-forwarded-for': '9.9.9.9',
    'x-pxs-proxy-secret': 'spoofed',
    'x-pxs-client-ip': '9.9.9.9',
    'x-real-ip': '203.0.113.7',
  }), SECRET);
  assert.deepEqual([...h.keys()].sort(), ['accept', 'x-pxs-client-ip', 'x-pxs-proxy-secret']);
  assert.equal(h.get('x-pxs-proxy-secret'), SECRET);
  assert.equal(h.get('x-pxs-client-ip'), '203.0.113.7');
});

test('the client address comes from x-real-ip and only when it is an address', () => {
  assert.equal(upstreamHeaders(new Headers({ 'x-real-ip': '2001:db8::1' }), SECRET)
    .get('x-pxs-client-ip'), '2001:db8::1');
  for (const bad of ['', 'nonsense', '1.2.3.4, 5.6.7.8']) {
    const h = upstreamHeaders(new Headers(bad ? { 'x-real-ip': bad } : {}), SECRET);
    assert.equal(h.get('x-pxs-client-ip'), null, bad);
  }
  const spoof = upstreamHeaders(new Headers({ 'x-pxs-client-ip': '9.9.9.9' }), SECRET);
  assert.equal(spoof.get('x-pxs-client-ip'), null);
});

test('response headers: no encoding, length, location or cookies pass back', () => {
  const h = downstreamHeaders(new Headers({
    'content-type': 'application/json',
    'cache-control': 'no-store',
    'retry-after': '30',
    'content-encoding': 'gzip',
    'content-length': '10',
    location: 'https://secret-host.example/api/x',
    'set-cookie': 'a=b',
    server: 'secret-host',
  }));
  assert.deepEqual([...h.keys()].sort(), ['cache-control', 'content-type', 'retry-after']);
});

async function withEnv(env, fetchImpl, fn) {
  const saved = { ...process.env };
  const savedFetch = globalThis.fetch;
  delete process.env.PXS_API_ORIGIN;
  delete process.env.PXS_PROXY_SECRET;
  Object.assign(process.env, env);
  globalThis.fetch = fetchImpl;
  try {
    return await fn();
  } finally {
    process.env = saved;
    globalThis.fetch = savedFetch;
  }
}

test('unset or bad configuration answers 503 and never fetches', async () => {
  let called = false;
  const fetchSpy = async () => { called = true; return new Response('x'); };
  for (const env of [{}, { PXS_API_ORIGIN: ORIGIN }, { PXS_PROXY_SECRET: SECRET },
    { PXS_API_ORIGIN: 'http://api.example.org', PXS_PROXY_SECRET: SECRET }]) {
    const res = await withEnv(env, fetchSpy, () => middleware(new Request('https://s.example/api/health')));
    assert.equal(res.status, 503);
    assert.equal(res.headers.get('cache-control'), 'no-store');
    assert.deepEqual(await res.json(), { error: 'The live service is not configured.' });
  }
  assert.equal(called, false);
});

test('forwards GET to the service with the secret and passes the answer back', async () => {
  let seen;
  const fake = async (url, init) => {
    seen = { url: String(url), init };
    return new Response('{"state":"running"}', {
      status: 202,
      headers: { 'content-type': 'application/json', 'cache-control': 'no-store', server: 'x' },
    });
  };
  const env = { PXS_API_ORIGIN: ORIGIN, PXS_PROXY_SECRET: SECRET };
  const res = await withEnv(env, fake, () => middleware(new Request(
    'https://s.example/api/jobs/abc?name=x', { headers: { 'x-real-ip': '203.0.113.7' } })));
  assert.equal(seen.url, `${ORIGIN}/api/jobs/abc?name=x`);
  assert.equal(seen.init.redirect, 'manual');
  assert.equal(seen.init.headers.get('x-pxs-proxy-secret'), SECRET);
  assert.equal(seen.init.headers.get('x-pxs-client-ip'), '203.0.113.7');
  assert.equal(res.status, 202);
  assert.equal(res.headers.get('cache-control'), 'no-store');
  assert.equal(res.headers.get('server'), null);
  assert.equal(await res.text(), '{"state":"running"}');
});

test('other methods get 405; an unreachable service gets 502 without detail', async () => {
  const env = { PXS_API_ORIGIN: ORIGIN, PXS_PROXY_SECRET: SECRET };
  const post = await withEnv(env, async () => new Response('x'),
    () => middleware(new Request('https://s.example/api/view', { method: 'POST' })));
  assert.equal(post.status, 405);
  const down = await withEnv(env, async () => { throw new TypeError(`fetch failed ${ORIGIN}`); },
    () => middleware(new Request('https://s.example/api/health')));
  assert.equal(down.status, 502);
  const body = await down.text();
  assert.doesNotMatch(body, /api\.example\.org/);
  assert.ok(!body.includes(SECRET));
});
