// Words and links for the sky map: pin text, the card sentence for a prebuilt view, and the page's
// own query string. Pure functions.

import { constellationOf } from './constellation.js';
import { describeMotion } from './summary.js';
import { MIN_FOV } from './exploreproj.js';
import { serializeState, emptyState } from './urlstate.js';
import { propagate } from './sky.js';

const pad2 = (n) => String(n).padStart(2, '0');

/** "18h 57m" style RA, rounded to the minute. */
export function plainRa(ra) {
  const total = Math.round((((ra % 360) + 360) % 360) / 15 * 60) % (24 * 60);
  return `${Math.floor(total / 60)}h ${pad2(total % 60)}m`;
}

/** "+4° 44′" style Dec, rounded to the arcminute, with a real minus sign. */
export function plainDec(dec) {
  const total = Math.round(Math.abs(dec) * 60);
  const sign = dec < 0 && total > 0 ? '−' : '+';
  return `${sign}${Math.floor(total / 60)}° ${pad2(total % 60)}′`;
}

/**
 * What a dropped pin says.
 * @returns {{title: string, where: string, degrees: string}}
 */
export function pinText(ra, dec) {
  const c = constellationOf(ra, dec);
  return {
    title: c.name ? `A patch of sky in ${c.name}` : 'A patch of sky',
    where: `RA ${plainRa(ra)}, Dec ${plainDec(dec)}`,
    degrees: `${ra.toFixed(4)}°, ${dec >= 0 ? '+' : '−'}${Math.abs(dec).toFixed(4)}°`,
  };
}

/** Link that builds a live view at a position (the main view's ?ra=&dec= form). */
export function buildHref(ra, dec) {
  const r = Number((((ra % 360) + 360) % 360).toFixed(4));
  return `index.html?ra=${(r >= 360 ? 0 : r).toFixed(4)}&dec=${dec.toFixed(4)}`;
}

/**
 * Link that opens a named object as the search box would (the main view looks the name up). The
 * map's own position rides along (at=) so a failed lookup still opens the view, never a dead end.
 * @param {string} name
 * @param {{ra: number, dec: number}|null} [at]
 */
export function nameHref(name, at = null) {
  const pos = at ? `&at=${(((at.ra % 360) + 360) % 360).toFixed(4)},${at.dec.toFixed(4)}` : '';
  return `index.html?name=${encodeURIComponent(name)}${pos}&from=map`;
}

/**
 * The open card, as parameters of the map's own address, so Back and "Back to the sky map"
 * reopen it: a gallery target by slug, an indexed object by label, a pin by position.
 * @param {{selected?: object|null, pin?: {ra: number, dec: number}|null}} scene
 */
export function exploreCardParams(scene) {
  if (scene?.selected?.slug) return { target: scene.selected.slug };
  if (scene?.selected?.entry?.label) return { known: scene.selected.entry.label };
  if (scene?.pin) return { pin: `${scene.pin.ra.toFixed(4)},${scene.pin.dec.toFixed(4)}` };
  return {};
}

/** Link to a prebuilt view. */
export const viewHref = (slug) => `index.html?target=${encodeURIComponent(slug)}`;

/** This page centred on a position: zoom is magnification, 1 = the whole sky. */
export function exploreHref(ra, dec, zoom = 18) {
  return `explore.html?ra=${ra.toFixed(4)}&dec=${dec.toFixed(4)}&zoom=${zoom}`;
}

/**
 * The plain sentences on a marker's card: the gallery blurb, then what we measured when the
 * manifest has it.
 * @param {{blurb?: string, known_type?: string|null, group?: string}} target
 * @param {object|null} manifest
 * @returns {string[]}
 */
export function targetLines(target, manifest = null) {
  const lines = [];
  if (target.blurb) lines.push(target.blurb);
  const mm = manifest?.measured_motion;
  const motion = mm && describeMotion(mm.pmra_masyr, mm.pmdec_masyr);
  if (motion && motion.arcsecPerYear >= 0.01) lines.push(`We measured it moving ${motion.words.replace(/ toward /, ' towards ')}.`);
  else if (target.group === 'solar-system') lines.push('It drifts against the stars, so the marker shows where it was when we imaged it.');
  const type = typeWords(target.known_type, target.group);
  if (type) lines.push(type);
  return lines;
}

/** The catalogue type in plain words, with the spectral type kept in brackets. */
export function typeWords(knownType, group = null) {
  if (!knownType) return null;
  if (group === 'solar-system') return `${knownType}.`;
  const code = knownType.replace(/^(d\/)?(sd)?/, '');
  const head = code[0];
  let words = 'A star';
  if ('LTY'.includes(head)) words = /^(d\/)?sd/.test(knownType) ? 'An old brown dwarf' : 'A brown dwarf';
  else if (head === 'M') words = /giant/i.test(knownType) ? 'A red giant star' : 'A small, cool red star';
  else if (/young/i.test(knownType)) words = 'A young star';
  return `${words} (spectral type ${knownType.replace(/ star$/, '')}).`;
}

const num = (v) => (v == null || v === '' || !Number.isFinite(Number(v)) ? null : Number(v));

/**
 * The page's query string: ?ra=&dec=&zoom= (zoom 1 = the whole sky, larger is closer) or ?target=<slug>.
 * @returns {{ra: number|null, dec: number|null, fov: number|null, target: string|null}}
 */
export function parseExploreQuery(search) {
  const q = new URLSearchParams(search);
  const ra = num(q.get('ra')), dec = num(q.get('dec')), zoom = num(q.get('zoom'));
  const okPos = ra != null && dec != null && dec >= -90 && dec <= 90;
  const target = /^[a-z0-9-]{1,64}$/.test(q.get('target') || '') ? q.get('target') : null;
  const pm = (q.get('pin') || '').match(/^(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)$/);
  const pin = pm && Number(pm[1]) >= 0 && Number(pm[1]) < 360 && Math.abs(Number(pm[2])) <= 90 ? { ra: Number(pm[1]), dec: Number(pm[2]) } : null;
  const known = (q.get('known') || '').trim().slice(0, 80) || null;
  return {
    ra: okPos ? ((ra % 360) + 360) % 360 : null,
    dec: okPos ? dec : null,
    fov: zoom != null && zoom > 0 ? Math.max(MIN_FOV, 360 / zoom) : null,
    target, pin, known,
  };
}

const fin = (x) => typeof x === 'number' && Number.isFinite(x);

/**
 * Link that builds a live view of a name-index object: position, and proper motion with its epoch
 * when the index has them (the same query the main page's search writes).
 * @param {{ra: number, dec: number, pmra?: number|null, pmdec?: number|null}} entry
 * @param {number} epoch the year the index positions refer to
 */
export function liveHref(entry, epoch) {
  const pm = fin(entry.pmra) && fin(entry.pmdec);
  // The same request as the search box's suggestion for this entry (suggest.js entryHref), so it shares the service's cache.
  return `index.html${serializeState({ ...emptyState(), ra: entry.ra, dec: entry.dec, fov: 240, label: entry.label || null,
    pmra: pm ? entry.pmra : null, pmdec: pm ? entry.pmdec : null, epoch: pm ? epoch : null })}`;
}

/** The card lines for an object in the name index that we have not built yet. */
export function knownLines(entry) {
  const what = entry.kind === 'brown dwarf' ? 'A brown dwarf' : entry.kind === 'star' ? 'A star' : 'An object';
  return [
    entry.sp_type ? `${what} (spectral type ${entry.sp_type}).` : `${what}.`,
    'We have not built this view yet: we build it live from SPHEREx and WISE images in about a minute.',
  ];
}

/** Start and end of an object's path across the sky from 2010 to 2026, or null without a proper motion. */
export function motionPath(entry, epoch, from = 2010, to = 2026) {
  if (!fin(entry.pmra) || !fin(entry.pmdec)) return null;
  return [from, to].map((y) => propagate(entry.ra, entry.dec, epoch, entry.pmra, entry.pmdec, y));
}

/** Moves visibly: a Solar System body, or a catalogue motion of at least 0.1 arcsec a year. */
export const MIN_MOVER_MASYR = 100;
export function isMover(t) {
  return t.group === 'solar-system' || (fin(t.pmra) && fin(t.pmdec) && Math.hypot(t.pmra, t.pmdec) >= MIN_MOVER_MASYR);
}

/** A built view that visibly moves to fly to, never the one already open. `rand` returns [0, 1). */
export function pickMover(targets, excludeSlug, rand) {
  const pool = targets.filter((t) => t.slug !== excludeSlug && isMover(t));
  return pool.length ? pool[Math.min(pool.length - 1, Math.floor(rand() * pool.length))] : null;
}
