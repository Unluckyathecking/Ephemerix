// Is there a Gaia DR3 source where the target was at the Gaia epoch? Pure. Everything comes
// from the manifest: the target's position and motion, and `overlays.gaia`.

import { propagate } from './sky.js';

// Gaia positions are good to a milliarcsecond and a catalogue position moved a year or two
// is good to a fraction of an arcsecond, so 2″ catches the target and little else
// (unrelated stars in the gallery fields sit 11″ or more away).
export const GAIA_RADIUS_ARCSEC = 2;
// The pipeline's own sentence when the Gaia query failed (src/pxs/catalogs.py, gaia_failed).
const GAIA_FAILED = /^Gaia DR3 sources could not be fetched/;
// The pipeline asks Gaia for at most this many sources (catalogs.MAX_SOURCES).
const GAIA_CAP = 200;
// W1−W2 redder than this is a T or Y dwarf colour (methane removes W1 light).
const COLD_W1_W2 = 1.5;
// A match whose motion differs from the target's by more than this is probably unrelated.
const PM_AGREE_MASYR = 50, PM_AGREE_FRAC = 0.2;

const fin = Number.isFinite;

/** Separation in arcsec between two positions (small-angle, fine at these scales). */
function sepArcsec(a, b) {
  const dra = (((a.ra - b.ra + 540) % 360) - 180) * Math.cos(((a.dec + b.dec) / 2) * Math.PI / 180);
  return Math.hypot(dra, a.dec - b.dec) * 3600;
}

/** The motion to move the target with: the catalogue's, else the one measured here, else null. */
function targetMotion(m) {
  const t = m.target;
  if (fin(t.pmra_masyr) && fin(t.pmdec_masyr)) return { pmra: t.pmra_masyr, pmdec: t.pmdec_masyr, from: 'catalogue' };
  const mm = m.measured_motion;
  if (mm && fin(mm.pmra_masyr) && fin(mm.pmdec_masyr)) return { pmra: mm.pmra_masyr, pmdec: mm.pmdec_masyr, from: 'measured' };
  return null;
}

function looksCold(m) {
  return m.match?.class === 'brown dwarf' || (fin(m.vetting?.w1_w2) && m.vetting.w1_w2 >= COLD_W1_W2);
}

const gText = (g) => (fin(g) ? `G = ${g.toFixed(1)}` : 'no G magnitude');
const arcsec = (x) => `${x < 0.05 ? '0.0' : x.toFixed(1)}″`;

/**
 * @param {object} m validated manifest
 * @returns {null | {status: 'match'|'unrelated'|'none'|'limited'|'unchecked', text: string, source?: object, sep?: number}}
 *   'limited': no source, but the list may lack the faintest stars, so absence holds only to its faintest G
 *   null for a Solar System body (no catalogue overlays apply)
 */
export function gaiaCounterpart(m, radius = GAIA_RADIUS_ARCSEC) {
  if (m.solar_system) return null;
  const gaia = m.overlays?.gaia || [];
  if ((m.warnings || []).some((w) => GAIA_FAILED.test(w))) {
    return { status: 'unchecked', text: 'Gaia DR3 could not be checked: the Gaia query failed when this view was built.' };
  }
  const t = m.target;
  const epoch = gaia[0]?.epoch ?? 2016;
  const pm = targetMotion(m);
  let at = { ra: t.ra, dec: t.dec };
  // A position with no stated epoch (a typed-in search) is compared as given.
  const caveat = fin(t.epoch) ? '' : ` (it has no stated epoch, so it was not moved to Gaia's ${epoch})`;
  if (fin(t.epoch) && t.epoch !== epoch) {
    if (!pm) return { status: 'unchecked', text: `Gaia DR3 could not be checked: the target's motion is unknown, so its position at the Gaia epoch (${epoch}) is too.` };
    at = propagate(t.ra, t.dec, t.epoch, pm.pmra, pm.pmdec, epoch);
  }
  const ranked = gaia.map((g) => ({ g, d: sepArcsec(at, g) })).sort((a, b) => a.d - b.d);
  const near = ranked[0];
  const where = caveat ? `of the position as given${caveat}` : `of where the target was at the Gaia epoch (${epoch})`;
  if (!near || near.d > radius) {
    // The pipeline keeps the brightest GAIA_CAP stars of a circle around the field, about 64% of
    // which falls inside it: a list this long may have lost its faintest stars.
    const mags = gaia.map((g) => g.g_mag).filter(fin);
    if (gaia.length >= GAIA_CAP / 2 && mags.length) {
      const faintest = Math.max(...mags);
      return { status: 'limited', text: `No Gaia DR3 source brighter than G = ${faintest.toFixed(1)} within ${radius}″ ${where}. This field is crowded and we keep only the ${GAIA_CAP} brightest Gaia stars around it, so a fainter one cannot be ruled out.` };
    }
    const why = looksCold(m)
      ? 'too faint or too red for Gaia, as expected for a cold brown dwarf.'
      : 'fainter than Gaia reaches (about G = 21) or too red for it.';
    return { status: 'none', text: `No Gaia DR3 source within ${radius}″ ${where}: ${why}` };
  }
  const g = near.g;
  const head = `Gaia DR3 ${g.id} sits ${arcsec(near.d)} ${where.replace(/^of/, 'from')}, ${gText(g.g_mag)}`;
  const gpm = fin(g.pmra_masyr) && fin(g.pmdec_masyr) ? Math.hypot(g.pmra_masyr, g.pmdec_masyr) : null;
  if (pm && gpm != null) {
    const diff = Math.hypot(g.pmra_masyr - pm.pmra, g.pmdec_masyr - pm.pmdec);
    if (diff > Math.max(PM_AGREE_MASYR, PM_AGREE_FRAC * Math.hypot(pm.pmra, pm.pmdec))) {
      return { status: 'unrelated', text: `${head}, but its motion differs from the target's by ${(diff / 1000).toFixed(2)} arcsec/yr, so it is probably an unrelated star.`, source: g, sep: near.d };
    }
    return { status: 'match', text: `${head}, with the same motion: Gaia sees the target.`, source: g, sep: near.d };
  }
  return { status: 'match', text: `${head}.`, source: g, sep: near.d };
}
