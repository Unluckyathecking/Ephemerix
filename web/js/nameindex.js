// The offline name index behind the search suggestions: web/data/names.json, written by
// tools/build_name_index.py from SIMBAD. Pure: normalise names, build keys, rank matches.

const GREEK = {
  alpha: 'alf', beta: 'bet', gamma: 'gam', delta: 'del', epsilon: 'eps', zeta: 'zet', eta: 'eta',
  theta: 'tet', iota: 'iot', kappa: 'kap', lambda: 'lam', mu: 'mu', nu: 'nu', xi: 'ksi', omicron: 'omi',
  pi: 'pi', rho: 'rho', sigma: 'sig', tau: 'tau', upsilon: 'ups', phi: 'phi', chi: 'chi', psi: 'psi', omega: 'ome',
};
// Genitive constellation names people type, for the objects in the index.
const CONSTELLATIONS = {
  indi: 'ind', centauri: 'cen', eridani: 'eri', ceti: 'cet', cygni: 'cyg', draconis: 'dra', aurigae: 'aur',
};
const WORDS = { ...GREEK, ...CONSTELLATIONS, gliese: 'gj', gl: 'gj' };
// Survey designations written with or without the J: "WISE J0855", "WISE 0855".
const SURVEY_J = /\b(2massi?w?|wisea?|wisep[ac]?|cwise|denis|ugps|vhs|scr|sdss)\s*j\s*(?=\d)/g;

/**
 * A name as people type it: lower case, no catalogue prefixes or apostrophes, common words shortened.
 * @param {string} text
 * @returns {string}
 */
export function normaliseName(text) {
  const s = String(text ?? '').normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase()
    .replace(/^\s*(name|v\*|\*\*|\*)\s+/, '')
    .replace(/['’`.](?!\d)/g, '')
    .replace(/[_,;()]/g, ' ')
    .replace(SURVEY_J, '$1 ')
    .replace(/\s+/g, ' ').trim();
  return s.split(' ').map((w) => WORDS[w] || w).join(' ');
}

/**
 * The short form of a survey designation: "WISE J085510.83-071442.5" -> "wise 0855-0714".
 * @param {string} alias
 * @returns {string|null}
 */
export function shortDesignation(alias) {
  const m = normaliseName(alias).match(/^([a-z0-9]+) (\d{4})[\d.]*([+-])(\d{4})/);
  return m ? `${m[1]} ${m[2]}${m[3]}${m[4]}` : null;
}

const compact = (s) => s.replace(/[\s-]/g, '');
const fin = (x) => typeof x === 'number' && Number.isFinite(x);

function validEntry(e) {
  if (!e || typeof e.label !== 'string' || !Array.isArray(e.names)) return false;
  const slug = typeof e.slug === 'string' && /^[a-z0-9][a-z0-9-]{0,80}$/.test(e.slug);
  return slug || (fin(e.ra) && fin(e.dec) && e.ra >= 0 && e.ra < 360 && Math.abs(e.dec) <= 90);
}

/**
 * Searchable keys for every valid entry; bad entries are dropped.
 * @param {{entries?: object[]}|null} data the parsed names.json
 * @returns {{entry: object, keys: {name: string, key: string, flat: string}[]}[]}
 */
export function buildIndex(data) {
  const entries = Array.isArray(data?.entries) ? data.entries.filter(validEntry) : [];
  return entries.map((entry) => {
    const names = [entry.label, ...entry.names.filter((n) => typeof n === 'string')];
    const keys = [];
    for (const name of names) {
      for (const key of [normaliseName(name), shortDesignation(name)]) {
        if (key && !keys.some((k) => k.key === key)) keys.push({ name, key, flat: compact(key) });
      }
    }
    return { entry, keys };
  });
}

/** How well one key matches the query; 0 for no match. */
function score(k, q, qFlat, qWords) {
  if (k.key === q) return 100;
  if (k.key.startsWith(q)) return 80;
  if (qFlat.length >= 3 && k.flat.startsWith(qFlat)) return 70;
  if (new RegExp(`(^|\\s)${q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}`).test(k.key)) return 50;
  const words = k.key.split(' ');
  return qWords.every((w) => words.some((x) => x.startsWith(w))) ? 30 : 0;
}

// A typed position matches a gallery target within this many arcseconds of its path. The challenge
// brief's WISE-era position of WISE 0855-0714 lies 0.5 arcsec from that path but 40 arcsec from our
// 2015 manifest position, so the path, not one epoch, is what is matched.
const NEAR_ARCSEC = 10;
const PATH_YEARS = [2010, 2027];

/** Closest distance (arcsec) from a point to an entry's straight path between two years. */
function pathDistance(e, ra, dec, epoch) {
  const cosd = Math.cos((dec * Math.PI) / 180);
  let dra = e.ra - ra;
  if (dra > 180) dra -= 360; else if (dra < -180) dra += 360;
  const x0 = dra * cosd * 3600, y0 = (e.dec - dec) * 3600;
  const vx = (Number.isFinite(e.pmra) ? e.pmra : 0) / 1000, vy = (Number.isFinite(e.pmdec) ? e.pmdec : 0) / 1000;
  const at = (t) => Math.hypot(x0 + vx * (t - epoch), y0 + vy * (t - epoch));
  const v2 = vx * vx + vy * vy;
  const [t0, t1] = PATH_YEARS;
  const tMin = v2 > 0 ? epoch - (x0 * vx + y0 * vy) / v2 : t0;
  return at(Math.max(t0, Math.min(t1, tMin)));
}

/**
 * The gallery target whose 2010-2027 path passes within NEAR_ARCSEC of a typed position, or null.
 * @param {ReturnType<typeof buildIndex>} index
 * @param {number} ra degrees
 * @param {number} dec degrees
 * @param {Set<string>} slugs gallery views built on this site
 * @param {number} [epoch] the year the index positions refer to (names.json: 2000)
 * @returns {{entry: object, arcsec: number}|null}
 */
export function nearGallery(index, ra, dec, slugs, epoch = 2000) {
  let best = null;
  for (const { entry } of index) {
    if (!entry.slug || !slugs.has(entry.slug) || !fin(entry.ra) || !fin(entry.dec)) continue;
    const d = pathDistance(entry, ra, dec, epoch);
    if (d <= NEAR_ARCSEC && (!best || d < best.arcsec)) best = { entry, arcsec: d };
  }
  return best;
}

/**
 * The best matches for what was typed, gallery views first on a tie.
 * `alias` is the name that matched when it differs from the label, else null.
 * @param {ReturnType<typeof buildIndex>} index
 * @param {string} query
 * @param {number} [limit]
 * @returns {{entry: object, alias: string|null, score: number}[]}
 */
export function searchNames(index, query, limit = 6) {
  const q = normaliseName(query);
  if (q.length < 2) return [];
  const qFlat = compact(q), qWords = q.split(' ');
  const hits = [];
  for (const { entry, keys } of index) {
    let best = null;
    for (const k of keys) {
      const s = score(k, q, qFlat, qWords);
      if (s && (!best || s > best.s)) best = { s, name: k.name };
    }
    if (best) hits.push({ entry, alias: best.name === entry.label ? null : best.name, score: best.s + (entry.slug ? 25 : 0) });
  }
  return hits.sort((a, b) => b.score - a.score || a.entry.label.localeCompare(b.entry.label)).slice(0, limit);
}
