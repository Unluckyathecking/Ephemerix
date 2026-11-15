// ?name=<text>: open a named object exactly as the search box would, so a link from the sky map
// makes the same request to the lookup service (and is served from its cache the second time).
// The offline index first, then the live name lookup, then the Solar System body lookup.

import { searchNames } from './nameindex.js';
import { entryHref } from './suggest.js';
import { resolveName, resolveBody } from './resolve.js';
import { serializeState, emptyState, cleanLabel } from './urlstate.js';

const FOV = 240; // the search box's default field of view

/**
 * Where a name leads: the query string of the view to open, or a message saying why not.
 * @param {string} name
 * @param {{index: object[], slugs: Set<string>, apiBase: string, fetchImpl?: Function, fallback?: object|null}} deps  fallback: the map's position (?at=)
 * @returns {Promise<{search: string}|{message: string}>}
 */
export async function nameToSearch(name, { index, slugs, apiBase, fetchImpl, fallback = null }) {
  const label = cleanLabel(name);
  const top = searchNames(index, name)[0];
  if (top && top.score >= 80) {
    const href = entryHref(top.entry, slugs);
    if (href) return { search: href };
  }
  const opts = fetchImpl ? { apiBase, fetchImpl } : { apiBase };
  const r = await resolveName(name, opts);
  if (r.ok) {
    // The same numbers the search box sends after a name lookup (search.js), plus the name to show.
    return { search: serializeState({ ...emptyState(), ra: +r.ra.toFixed(7), dec: +r.dec.toFixed(7), pmra: r.pmra, pmdec: r.pmdec,
      epoch: r.pmra != null ? r.epoch : null, fov: FOV, label }) };
  }
  // The sky map knows where the object is: when the lookup fails, open there, never a dead end.
  if (fallback) {
    const pm = Number.isFinite(fallback.pmra) && Number.isFinite(fallback.pmdec);
    return { search: serializeState({ ...emptyState(), ra: fallback.ra, dec: fallback.dec, fov: FOV, label,
      pmra: pm ? fallback.pmra : null, pmdec: pm ? fallback.pmdec : null, epoch: pm ? fallback.epoch : null }) };
  }
  const b = apiBase ? await resolveBody(name, opts) : { ok: false };
  if (b.ok) return { search: serializeState({ ...emptyState(), body: b.designation }) };
  return { message: r.message };
}
