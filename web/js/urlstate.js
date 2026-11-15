// Page state <-> query string, as specified in docs/api.md ("Page URL").

const NUM_KEYS = ['ra', 'dec', 'pmra', 'pmdec', 'epoch', 'fov'];
const SLUG = /^[a-z0-9][a-z0-9-]{0,80}$/i;
const ID = /^[\w.:-]{1,120}$/;
// A Solar System body name or designation, as the server's /api/body accepts it.
export const BODY = /^[A-Za-z0-9][A-Za-z0-9 /'()._-]{0,39}$/;

/** Empty state: the gallery landing. */
export function emptyState() {
  return { target: null, body: null, ra: null, dec: null, pmra: null, pmdec: null, epoch: null, fov: null,
    frame: null, bands: null, preset: null, spec: null, cmp: null, a: null, b: null, zoom: null, follow: null, fc: false, embed: false, mode: null, label: null, name: null, at: null, from: null };
}

// Parameters only the full view writes; a link carrying one came from an expert.
const EXPERT = ['frame', 'bands', 'preset', 'spec', 'cmp', 'zoom', 'follow'];
const hasExpert = (s) => EXPERT.some((k) => s[k] != null) || s.fc || s.embed;

/**
 * Simple or full (Advanced) view. An explicit mode wins; a link carrying full-view parameters (an
 * older expert link or an embed) opens the full view; otherwise the visitor's stored choice, and
 * Advanced when there is none.
 * @param {object} s page state
 * @param {string|null} [stored] the stored site-wide mode (js/mode.js): 'simple' | 'advanced' | null
 * @returns {'simple'|'full'}
 */
export function viewMode(s, stored = null) {
  if (s.mode === 'simple' || s.mode === 'full') return s.mode;
  if (hasExpert(s)) return 'full';
  return stored === 'simple' ? 'simple' : 'full';
}

function num(v) {
  if (v == null || v.trim() === '') return null;
  const x = Number(v);
  return Number.isFinite(x) ? x : null;
}

/**
 * Parse a query string. Unknown or malformed values are dropped, never thrown.
 * @param {string} search  e.g. location.search
 */
export function parseState(search) {
  const q = new URLSearchParams(search);
  const s = emptyState();
  const target = q.get('target');
  if (target && SLUG.test(target)) s.target = target;
  const body = (q.get('body') || '').trim();
  if (BODY.test(body)) s.body = body;
  for (const k of NUM_KEYS) s[k] = num(q.get(k));
  if (s.ra != null && !(s.ra >= 0 && s.ra < 360)) s.ra = null;
  if (s.dec != null && !(s.dec >= -90 && s.dec <= 90)) s.dec = null;
  if (s.fov != null && !(s.fov > 0)) s.fov = null;
  const frame = q.get('frame');
  if (frame && ID.test(frame)) s.frame = frame;
  for (const k of ['spec', 'a', 'b']) {
    const v = q.get(k);
    if (v && ID.test(v)) s[k] = v;
  }
  const preset = q.get('preset');
  if (preset && SLUG.test(preset)) s.preset = preset;
  const cmp = q.get('cmp');
  if (cmp === 'diff' || cmp === 'sum') s.cmp = cmp;
  const bands = q.get('bands');
  if (bands != null) s.bands = bands.split(',').map((b) => b.trim()).filter((b) => ID.test(b));
  const zoom = num(q.get('zoom'));
  if (zoom != null && zoom >= 1 && zoom <= 8) s.zoom = zoom;
  const follow = q.get('follow');
  if (follow === '1' || follow === '0') s.follow = follow === '1';
  s.fc = q.get('fc') === '1';
  s.embed = q.get('embed') === '1';
  const mode = q.get('mode');
  if (mode === 'simple' || mode === 'full' || mode === 'advanced') s.mode = mode === 'simple' ? 'simple' : 'full';
  if (s.ra != null && s.dec != null && !s.target && !s.body) s.label = cleanLabel(q.get('label'));
  s.name = cleanLabel(q.get('name'));
  s.at = parseAt(q.get('at'));
  s.from = q.get('from') === 'map' ? 'map' : null;
  return s;
}

const LABEL_MAX = 80;

/** ?at=ra,dec: where the sky map put a named object, the fallback when a name lookup fails. */
function parseAt(v) {
  const m = String(v ?? '').match(/^(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)$/);
  if (!m) return null;
  const ra = Number(m[1]), dec = Number(m[2]);
  return ra >= 0 && ra < 360 && Math.abs(dec) <= 90 ? { ra, dec, pmra: null, pmdec: null, epoch: null } : null;
}

/**
 * A name typed or chosen by a visitor, for display only: control characters and runs of space
 * collapsed, capped at 80 characters, null when empty. It is only ever set as text, never as HTML.
 * @param {string|null} v
 */
export function cleanLabel(v) {
  const s = String(v ?? '').replace(/[\u0000-\u001f\u007f]/g, ' ').replace(/\s+/g, ' ').trim().slice(0, LABEL_MAX).trim();
  return s || null;
}

/** Which kind of view the state asks for; 'name' is a name still to be looked up (?name=). */
export function viewKind(s) {
  if (s.target) return 'gallery';
  if (s.body) return 'body';
  if (s.ra != null && s.dec != null) return 'position';
  if (s.name) return 'name';
  return 'landing';
}

/** Serialize state to a query string ("" or "?..."), in a stable key order. */
export function serializeState(s) {
  const q = new URLSearchParams();
  if (s.target) q.set('target', s.target);
  else if (s.body) q.set('body', s.body);
  else if (s.ra != null && s.dec != null) {
    for (const k of NUM_KEYS) if (s[k] != null) q.set(k, String(s[k]));
  }
  if (!['landing', 'name'].includes(viewKind(s))) {
    if (s.frame) q.set('frame', s.frame);
    if (s.bands && s.bands.length) q.set('bands', s.bands.join(','));
    if (s.preset) q.set('preset', s.preset);
    if (s.spec) q.set('spec', s.spec);
    if (s.cmp) {
      q.set('cmp', s.cmp);
      if (s.a) q.set('a', s.a);
      if (s.b) q.set('b', s.b);
    }
    if (s.zoom != null) q.set('zoom', String(Math.round(s.zoom * 100) / 100));
    if (s.follow != null) q.set('follow', s.follow ? '1' : '0');
    if (s.fc) q.set('fc', '1');
    if (s.embed) q.set('embed', '1');
    // Written only when the other parameters would say otherwise, so older links keep their exact form.
    if (s.mode === 'simple') q.set('mode', 'simple');
    // A position view reached from a name keeps the name, for display only.
    if (s.label && viewKind(s) === 'position') q.set('label', s.label);
    if (s.from) q.set('from', s.from);
  } else if (s.name) {
    q.set('name', s.name);
    if (s.at) q.set('at', `${s.at.ra},${s.at.dec}`);
    if (s.from) q.set('from', s.from);
  }
  const out = q.toString().replace(/%2C/g, ',');
  return out ? `?${out}` : '';
}

/** Query string for the live API from a position state. */
export function apiQuery(s) {
  const q = new URLSearchParams();
  for (const k of NUM_KEYS) if (s[k] != null) q.set(k, String(s[k]));
  return q.toString();
}

/** Query string for the live API's /api/body from a body state. */
export function bodyQuery(s) {
  return new URLSearchParams({ name: s.body }).toString().replace(/\+/g, '%20');
}
