// Anonymous visit counts from the host's own cookie-free counter (Vercel Web Analytics). The
// script is same-origin, so the Content-Security-Policy is unchanged. It is loaded only on
// *.vercel.app, where the host serves it; on localhost and any other host nothing is loaded.
const COUNTER = '/_vercel/insights/script.js';

/** True on the hosted site only. */
export function countsVisits(hostname) {
  return hostname.endsWith('.vercel.app');
}

/** Load the counter once per page. */
export function countVisit() {
  if (!countsVisits(location.hostname) || document.querySelector(`script[src="${COUNTER}"]`)) return;
  const s = document.createElement('script');
  s.defer = true;
  s.src = COUNTER;
  document.head.append(s);
}
