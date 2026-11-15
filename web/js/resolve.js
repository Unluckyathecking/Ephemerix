// Object-name lookup through the live server's GET /api/resolve?name= (src/pxs/api/resolve.py).
// Fails soft: every problem comes back as {ok: false, message}. Pure apart from the injected fetch.

const NO_SERVER = 'Name lookup needs the live server, which this copy of the site does not have. Enter the coordinates instead.';
const UNREACHABLE = 'The name service could not be reached. Try again, or enter the coordinates instead.';

/**
 * True when the text should be looked up as a name rather than parsed as coordinates.
 * Unit letters straight after a number ("08h55m10s", "-07d14m") do not count.
 * @param {string} text
 */
export function looksLikeName(text) {
  const stripped = String(text).replace(/(\d)\s*[hdms]/gi, '$1');
  return /[a-z]/i.test(stripped);
}

const fin = Number.isFinite;

const BODY_NOT_FOUND = 'That Solar System body was not found.';
const BODY_TEXT = /^[A-Za-z0-9][A-Za-z0-9 /'()._-]{0,79}$/;

async function getJson(url, fetchImpl, signal) {
  const res = await fetchImpl(url, { signal, headers: { Accept: 'application/json' } });
  let body = null;
  try { body = await res.json(); } catch { body = null; }
  return { res, body };
}

// A visitor never sees an HTTP code. No /api here (404, 405, 501) means a copy without the live
// server; anything else means the service is having trouble.
export const STATIC_COPY = 'This copy of the site shows the built views only, so it cannot look up new names. Try one of the gallery objects, or the example names under the box.';
const NO_API = new Set([404, 405, 501]);

function httpMessage(res, body, what) {
  const wait = Number(res.headers?.get?.('Retry-After'));
  const base = typeof body?.error === 'string' ? body.error
    : NO_API.has(res.status) ? STATIC_COPY : `The ${what} is not answering right now. Try again in a minute, or enter the coordinates instead.`;
  return Number.isFinite(wait) && wait > 0 ? `${base} Try again in about ${Math.ceil(wait)} s.` : base;
}

const notFound = (name) => `We could not find an object called “${String(name).trim().slice(0, 60)}”. Check the spelling, or enter its coordinates.`;

/**
 * Is this name a Solar System body? Asks GET /api/body/resolve?name= (never starts a build).
 * @param {string} name
 * @param {{apiBase: string, fetchImpl?: Function, signal?: AbortSignal}} opts
 * @returns {Promise<{ok: true, designation: string, name: string, kind: string}
 *   | {ok: false, message: string, suggestions: {designation: string, name: string}[]}>}
 */
export async function resolveBody(name, { apiBase, fetchImpl = fetch, signal } = {}) {
  const fail = (message, suggestions = []) => ({ ok: false, message, suggestions });
  if (!apiBase) return fail(NO_SERVER);
  const url = `${apiBase.replace(/\/+$/, '')}/api/body/resolve?name=${encodeURIComponent(name.trim())}`;
  let res, body;
  try {
    ({ res, body } = await getJson(url, fetchImpl, signal));
  } catch (err) {
    if (err?.name === 'AbortError') throw err;
    return fail(UNREACHABLE);
  }
  if (!res.ok) return fail(httpMessage(res, body, 'body lookup'));
  if (body?.resolved !== true) {
    const list = Array.isArray(body?.did_you_mean) ? body.did_you_mean : [];
    const ok = (s) => typeof s?.designation === 'string' && BODY_TEXT.test(s.designation);
    return fail(typeof body?.message === 'string' ? body.message : BODY_NOT_FOUND,
      list.filter(ok).slice(0, 5).map((s) => ({ designation: s.designation,
        name: typeof s.name === 'string' && BODY_TEXT.test(s.name) ? s.name : s.designation })));
  }
  if (typeof body.designation !== 'string' || !BODY_TEXT.test(body.designation)) return fail(BODY_NOT_FOUND);
  const label = typeof body.name === 'string' && body.name.trim() ? body.name.trim() : body.designation;
  return { ok: true, designation: body.designation, name: label, kind: typeof body.kind === 'string' ? body.kind : '' };
}

/**
 * @param {string} name
 * @param {{apiBase: string, fetchImpl?: Function, signal?: AbortSignal}} opts
 * @returns {Promise<{ok: true, name: string, ra: number, dec: number, pmra: number|null,
 *   pmdec: number|null, epoch: number|null, source: string} | {ok: false, message: string}>}
 */
export async function resolveName(name, { apiBase, fetchImpl = fetch, signal } = {}) {
  if (!apiBase) return { ok: false, message: NO_SERVER };
  const url = `${apiBase.replace(/\/+$/, '')}/api/resolve?name=${encodeURIComponent(name.trim())}`;
  let res;
  try {
    res = await fetchImpl(url, { signal, headers: { Accept: 'application/json' } });
  } catch (err) {
    if (err?.name === 'AbortError') throw err;
    return { ok: false, message: UNREACHABLE };
  }
  let body = null;
  try { body = await res.json(); } catch { body = null; }
  if (!res.ok) return { ok: false, message: httpMessage(res, body, 'name service') };
  if (!body || body.resolved !== true) {
    return { ok: false, message: typeof body?.message === 'string' ? body.message : notFound(name) };
  }
  if (!fin(body.ra) || !fin(body.dec) || body.ra < 0 || body.ra >= 360 || Math.abs(body.dec) > 90) {
    return { ok: false, message: 'The name service sent a position that could not be read. Enter the coordinates instead.' };
  }
  const hasPm = fin(body.pmra) && fin(body.pmdec);
  return {
    ok: true, name: typeof body.name === 'string' && body.name.trim() ? body.name.trim() : name.trim(),
    ra: body.ra, dec: body.dec,
    pmra: hasPm ? body.pmra : null, pmdec: hasPm ? body.pmdec : null,
    epoch: hasPm && fin(body.epoch) ? body.epoch : null,
    source: typeof body.source === 'string' ? body.source : 'the name service',
  };
}
