// The API is served from the site's own origin: the host rewrites /api/* to the lookup
// service (web/middleware.js), so API_BASE is '/' and 'self' in the Content-Security-Policy
// covers it. Any non-empty value enables live searches; '' gives a gallery-only site.
//
// Local development against another API: open the page on localhost with ?api=ORIGIN
// (an http(s) origin, for example http://localhost:8000), and add that origin to connect-src and
// img-src in the page's Content-Security-Policy meta tag. The override is ignored on any other host.
const SAME_ORIGIN = '/';
const LOCAL_HOSTS = new Set(['localhost', '127.0.0.1', '[::1]']);

/** The API base for a page at `hostname` with query string `search`. */
export function apiBaseFor(hostname, search = '') {
  if (!LOCAL_HOSTS.has(hostname)) return SAME_ORIGIN;
  const raw = new URLSearchParams(search).get('api');
  if (!raw) return SAME_ORIGIN;
  try {
    const u = new URL(raw);
    return u.protocol === 'http:' || u.protocol === 'https:' ? u.origin : SAME_ORIGIN;
  } catch {
    return SAME_ORIGIN;
  }
}

export const API_BASE = typeof location === 'undefined' ? SAME_ORIGIN : apiBaseFor(location.hostname, location.search);

// How long the page waits for a live view before giving up (ms). The server stops a
// build after 480 s, plus any time spent queued behind other builds.
export const LIVE_TIMEOUT_MS = 600000;
