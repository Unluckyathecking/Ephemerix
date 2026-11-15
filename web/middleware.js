// Vercel Routing Middleware: the same-origin proxy for /api/* to the lookup service.
//
// The service's host is read from the PXS_API_ORIGIN environment variable and named in no
// file, so it is never served to browsers. Each forwarded request carries the shared secret
// (PXS_PROXY_SECRET), which tells the service the request came through here, and the
// visitor's address as Vercel's edge recorded it (x-real-ip: Vercel overwrites the
// forwarded-for headers, so a visitor cannot set it). The service trusts x-pxs-client-ip
// only next to the right secret. See deploy/README.md ("Same-origin proxy").
//
// No dependencies, so the static deploy needs no install or build step: the proxy is a
// plain fetch(), and the pure parts below are exported for web/tests/middleware.test.js.

import { isIP } from 'node:net';

// Node.js runtime (the documented default, stated because the CLI otherwise builds an edge
// function): node:net below, and no 25 s first-byte limit while Modal starts cold.
// /api/archives is not proxied: web/api/archives.js serves it from the saved checks, cached.
export const config = { matcher: ['/api', '/api/((?!archives$).*)'], runtime: 'nodejs' };

const UPSTREAM_TIMEOUT_MS = 60000; // a Modal cold start can take tens of seconds
// Request headers worth passing on. Everything else (cookies, auth, host, forwarded-for,
// accept-encoding, any inbound x-pxs-*) is dropped.
const REQUEST_ALLOW = ['accept', 'accept-language', 'user-agent', 'if-none-match', 'if-modified-since'];
// Response headers passed back. Not content-encoding/length (fetch has already decoded the
// body), not location (it would name the service's host), not set-cookie.
const RESPONSE_ALLOW = ['content-type', 'cache-control', 'retry-after', 'etag', 'last-modified',
  'vary', 'x-content-type-options'];

function jsonError(message, status) {
  return new Response(JSON.stringify({ error: message }), {
    status,
    headers: { 'content-type': 'application/json', 'cache-control': 'no-store' },
  });
}

/** The service origin from env, or null when it is unset or not an https origin. */
export function upstreamOrigin(raw) {
  if (!raw) return null;
  try {
    const u = new URL(raw);
    return u.protocol === 'https:' ? u.origin : null;
  } catch {
    return null;
  }
}

/** The service URL for a request URL, or null if it would leave `origin` or /api/. */
export function upstreamUrl(requestUrl, origin) {
  const { pathname, search } = new URL(requestUrl);
  if (pathname !== '/api' && !pathname.startsWith('/api/')) return null;
  const target = new URL(pathname + search, origin);
  return target.origin === origin ? target : null;
}

/** The headers sent to the service: allow-listed ones, the secret and the client address. */
export function upstreamHeaders(incoming, secret) {
  const out = new Headers();
  for (const name of REQUEST_ALLOW) {
    const v = incoming.get(name);
    if (v !== null) out.set(name, v);
  }
  out.set('x-pxs-proxy-secret', secret);
  const ip = (incoming.get('x-real-ip') || '').trim();
  if (isIP(ip)) out.set('x-pxs-client-ip', ip);
  return out;
}

/** The headers returned to the browser from the service's response. */
export function downstreamHeaders(upstream) {
  const out = new Headers();
  for (const name of RESPONSE_ALLOW) {
    const v = upstream.get(name);
    if (v !== null) out.set(name, v);
  }
  return out;
}

export default async function middleware(request) {
  const origin = upstreamOrigin(process.env.PXS_API_ORIGIN);
  const secret = process.env.PXS_PROXY_SECRET || '';
  if (!origin || !secret) return jsonError('The live service is not configured.', 503);
  if (request.method !== 'GET' && request.method !== 'HEAD') {
    return jsonError('Only GET is supported.', 405);
  }
  const target = upstreamUrl(request.url, origin);
  if (!target) return jsonError('Not found.', 404);
  let res;
  try {
    res = await fetch(target, {
      method: request.method,
      headers: upstreamHeaders(request.headers, secret),
      redirect: 'manual',
      signal: AbortSignal.timeout(UPSTREAM_TIMEOUT_MS),
    });
  } catch (err) {
    const timedOut = err && err.name === 'TimeoutError';
    console.error('pxs proxy: upstream', timedOut ? 'timeout' : 'error'); // no URL, no headers
    return timedOut
      ? jsonError('The live service took too long to answer. Please try again.', 504)
      : jsonError('The live service could not be reached. Please try again.', 502);
  }
  return new Response(request.method === 'HEAD' ? null : res.body, {
    status: res.status,
    headers: downstreamHeaders(res.headers),
  });
}
