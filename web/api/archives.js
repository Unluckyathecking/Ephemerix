// Vercel Function for GET /api/archives: the saved archive checks, from the tiny read-only
// Modal function (`archive_status` in deploy/modal_app.py), never from the lookup service.
//
// Its host is read from PXS_STATUS_ORIGIN and named in no file; the request carries the same
// shared secret as the proxy (PXS_PROXY_SECRET). The answer is the same for every visitor and
// keeps the upstream Cache-Control (public, s-maxage=300, stale-while-revalidate=900), so
// Vercel's CDN serves almost every request without calling this function or Modal. No visitor
// header, cookie or address is forwarded. web/middleware.js leaves this one path alone.

import { upstreamOrigin } from '../middleware.js';

const TIMEOUT_MS = 20000; // a cold start of the small function is a few seconds
const FALLBACK_CACHE = 'public, s-maxage=300, stale-while-revalidate=900';

function failure(status) { // never cached
  return new Response(JSON.stringify({ error: 'The archive checks are not available.' }), {
    status, headers: { 'content-type': 'application/json', 'cache-control': 'no-store' },
  });
}

const DAY_MS = 86400000;
const KEEP_DAYS = 31; // the saved checks span 30 days; older days cannot exist

/** True for a real date from 31 days before `now` to tomorrow (UTC). `now` is a Date or ms. */
function dayInRange(day, now) {
  const t = Date.parse(`${day}T00:00:00Z`);
  if (!Number.isFinite(t) || new Date(t).toISOString().slice(0, 10) !== day) return false;
  const today = Math.floor(new Date(now).getTime() / DAY_MS) * DAY_MS;
  return t >= today - KEEP_DAYS * DAY_MS && t <= today + DAY_MS;
}

/** '' or '?day=YYYY-MM-DD' for a request's query string; null for anything else, including a
 *  day older than 31 days or later than tomorrow (UTC), so each distinct value is a real day. */
export function dayQuery(search, now = Date.now()) {
  const q = new URLSearchParams(search || '');
  const keys = [...q.keys()];
  if (!keys.length) return '';
  const day = q.get('day');
  return keys.length === 1 && keys[0] === 'day' && /^\d{4}-\d{2}-\d{2}$/.test(day) && dayInRange(day, now) ? `?day=${day}` : null;
}

/** The answer for this path, given the env, a fetch, the query string and "now". Exported for web/tests/archivesfn.test.js. */
export async function archives(env, fetchImpl = fetch, search = '', now = Date.now()) {
  const origin = upstreamOrigin(env.PXS_STATUS_ORIGIN);
  const secret = env.PXS_PROXY_SECRET || '';
  if (!origin || !secret) return failure(503);
  const day = dayQuery(search, now);
  if (day === null) return failure(400);
  let res;
  try {
    res = await fetchImpl(new URL(`/api/archives${day}`, origin), {
      headers: { accept: 'application/json', 'x-pxs-proxy-secret': secret },
      redirect: 'manual',
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
  } catch {
    console.error('pxs archives: upstream unreachable'); // no URL, no headers
    return failure(502);
  }
  if (res.status === 400 || res.status === 404) return failure(res.status);
  if (res.status !== 200) return failure(502);
  return new Response(await res.text(), {
    status: 200,
    headers: { 'content-type': 'application/json', 'cache-control': res.headers.get('cache-control') || FALLBACK_CACHE },
  });
}

// The CDN keys its cache on the full URL, query string included, so each ?day= is its own entry.
export function GET(request) {
  return archives(process.env, fetch, new URL(request.url).search);
}
