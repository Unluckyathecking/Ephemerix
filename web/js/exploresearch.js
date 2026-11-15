// Search on the sky map: a name (prebuilt view, bright star, constellation) or a position.
// Pure functions.

import { parsePosition, CoordError } from './coords.js';
import { searchNames } from './nameindex.js';

/** Lower case, accents and punctuation stripped, single spaces. */
export function normalise(text) {
  return String(text).normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase()
    .replace(/[’'`]/g, '').replace(/[^a-z0-9+.-]+/g, ' ').trim();
}

/**
 * Build the search list.
 * @param {{targets?: Array<{slug: string, name: string, ra: number, dec: number}>,
 *   stars?: Array<{name: string, ra: number, dec: number}>,
 *   constellations?: Array<{name: string, ra: number, dec: number}>}} parts
 * @returns {Array<{label: string, kind: 'target'|'star'|'constellation', ra: number, dec: number, slug?: string, key: string, fov: number}>}
 */
export function buildIndex({ targets = [], stars = [], constellations = [] }) {
  const out = [];
  for (const t of targets) out.push({ label: t.name, kind: 'target', ra: t.ra, dec: t.dec, slug: t.slug, key: normalise(`${t.name} ${t.slug.replace(/-/g, ' ')}`), fov: 8 });
  for (const s of stars) out.push({ label: s.name, kind: 'star', ra: s.ra, dec: s.dec, key: normalise(s.name), fov: 12 });
  for (const c of constellations) out.push({ label: c.name, kind: 'constellation', ra: c.ra, dec: c.dec, key: normalise(c.name), fov: 45 });
  return out;
}

const KIND_RANK = { target: 0, star: 1, constellation: 2 };

function score(key, q) {
  if (key === q) return 0;
  if (key.startsWith(q)) return 1;
  if (key.split(' ').some((w) => w.startsWith(q))) return 2;
  if (key.replace(/ /g, '').includes(q.replace(/ /g, ''))) return 3;
  return -1;
}

/**
 * Matches for a query, best first. A position ("83.8 -5.4", "05 35 17 -05 23 28") comes back as
 * one result of kind 'position'; text that is neither a name nor a valid position returns [].
 * @returns {Array<{label: string, kind: string, ra: number, dec: number, slug?: string, fov: number}>}
 */
export function searchSky(query, index, limit = 6) {
  query = String(query).replace(/[\u2212\u2013\u2012]/g, '-'); // typed or pasted minus signs and dashes
  const q = normalise(query);
  if (!q) return [];
  if (/^[\d+\-.\s:hdms°'"′″,]+$/i.test(String(query).trim())) {
    try {
      const p = parsePosition(String(query));
      return [{ label: `RA ${p.ra.toFixed(4)}°, Dec ${p.dec.toFixed(4)}°`, kind: 'position', ra: p.ra, dec: p.dec, fov: 8 }];
    } catch (e) {
      if (!(e instanceof CoordError)) throw e;
    }
  }
  return index
    .map((e) => ({ e, s: score(e.key, q) }))
    .filter((r) => r.s >= 0)
    .sort((a, b) => a.s - b.s || KIND_RANK[a.e.kind] - KIND_RANK[b.e.kind] || a.e.label.length - b.e.label.length)
    .slice(0, limit)
    .map((r) => r.e);
}

/**
 * Matches from the site's name index (web/data/names.json), by any alias. Built views come back as
 * kind 'target', the rest as 'known'.
 */
export function nameResults(nameIndex, query, limit = 6) {
  return searchNames(nameIndex, query, limit).map(({ entry, alias }) => ({
    label: entry.label, kind: entry.slug ? 'target' : 'known', ra: entry.ra, dec: entry.dec,
    slug: entry.slug || undefined, alias, entry, fov: 8,
  }));
}
