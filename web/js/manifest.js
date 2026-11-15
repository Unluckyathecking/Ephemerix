// Validate a view manifest (docs/api.md) at the boundary. Returns a cleaned
// copy plus a list of non-fatal problems; throws ManifestError when the view
// cannot be shown at all. Never trusts field types.

import { cleanSolarSystem } from './bodytext.js';
import { cleanFieldMovers } from './fieldmovers.js';

export class ManifestError extends Error {}

const fin = (v) => typeof v === 'number' && Number.isFinite(v);
const str = (v) => (typeof v === 'string' && v.trim() ? v : null);
const arr = (v) => (Array.isArray(v) ? v : []);
const strings = (v) => arr(v).filter((s) => typeof s === 'string' && s.trim());
const pair = (v) => (Array.isArray(v) && v.length === 2 && fin(v[0]) && fin(v[1]) ? [v[0], v[1]] : null);
const numOrNull = (v) => (fin(v) ? v : null);

function mjdOf(f) {
  if (fin(f.mjd)) return f.mjd;
  const t = Date.parse(f.date);
  return Number.isFinite(t) ? t / 86400000 + 40587 : null;
}

function cleanFrame(f, problems) {
  if (!f || typeof f !== 'object') return null;
  const id = str(f.id), mission = str(f.mission), band = str(f.band), image = str(f.image);
  const mjd = mjdOf(f);
  if (!id || !band || !image || mjd == null) {
    problems.push(`A frame${id ? ` (${id})` : ''} was skipped: it lacks an id, band, image or date.`);
    return null;
  }
  const centroid = pair(f.centroid_px);
  return {
    id, mission: mission || 'unknown', band, image, mjd,
    date: str(f.date) || new Date((mjd - 40587) * 86400000).toISOString(),
    wavelength_um: pair(f.wavelength_um),
    date_span_days: numOrNull(f.date_span_days),
    n_exposures: numOrNull(f.n_exposures),
    native_pixscale_arcsec: numOrNull(f.native_pixscale_arcsec),
    predicted_px: pair(f.predicted_px),
    centroid_px: centroid,
    centroid_err_arcsec: centroid ? numOrNull(f.centroid_err_arcsec) : null,
    flag_fraction: numOrNull(f.flag_fraction),
    // Share of the frame with no usable data, that share near the object, and the mask image (docs/api.md).
    no_data_fraction: share(f.no_data_fraction),
    no_data_near_target: share(f.no_data_near_target),
    gaps_image: str(f.gaps_image),
    warnings: strings(f.warnings),
  };
}

const share = (v) => (fin(v) && v >= 0 && v <= 1 ? v : null);

/** `field` (docs/api.md): glare over the object, a crowded field; null for an older manifest. */
function cleanField(f) {
  if (!f || typeof f !== 'object') return null;
  return { saturated: f.saturated === true, crowded: typeof f.crowded === 'boolean' ? f.crowded : null,
    saturated_missions: strings(f.saturated_missions) };
}

/** A motion fitted but too thin to publish: {reason, n_detections, baseline_years}, or null. */
function cleanNotMeasured(n) {
  if (!n || typeof n !== 'object' || !str(n.reason)) return null;
  return { reason: n.reason, n_detections: numOrNull(n.n_detections), baseline_years: numOrNull(n.baseline_years) };
}

function cleanSource(s) {
  if (!s || !fin(s.ra) || !fin(s.dec)) return null;
  return { ...s, id: String(s.id ?? ''), epoch: fin(s.epoch) ? s.epoch : 2016.0,
    pmra_masyr: numOrNull(s.pmra_masyr), pmdec_masyr: numOrNull(s.pmdec_masyr) };
}

function cleanSpectrum(s, problems) {
  const id = str(s?.id);
  if (!id) return null;
  const points = arr(s.points)
    .filter((p) => p && fin(p.wl_um) && fin(p.flux))
    .map((p) => ({ wl_um: p.wl_um, bw_um: numOrNull(p.bw_um), flux: p.flux, err: numOrNull(p.err),
      detector: p.detector ?? null, flagged: p.flagged === true }))
    .sort((a, b) => a.wl_um - b.wl_um);
  // Flagged points with no flux cannot be plotted; keep where they fall so the page can say so.
  const missing = arr(s.points)
    .filter((p) => p && fin(p.wl_um) && !fin(p.flux) && p.flagged === true)
    .map((p) => ({ wl_um: p.wl_um, reason: str(p.reason) }))
    .sort((a, b) => a.wl_um - b.wl_um);
  if (!points.length) {
    problems.push(`Spectrum ${id} has no usable points and was skipped.`);
    return null;
  }
  return { id, label: str(s.label) || id, date_start: str(s.date_start), date_end: str(s.date_end),
    unit: str(s.unit) || 'mJy', points, missing };
}

function cleanMatch(m, problems) {
  if (m == null) return null;
  if (typeof m !== 'object' || !str(m.best?.type)) {
    problems.push('The template match was unreadable and is not shown.');
    return null;
  }
  const fit = (x) => (x && str(x.type) ? { type: x.type, chi2: numOrNull(x.chi2), dof: numOrNull(x.dof) } : null);
  const models = {};
  for (const [k, v] of Object.entries(m.models && typeof m.models === 'object' ? m.models : {})) {
    const pts = arr(v).map(pair).filter(Boolean);
    if (pts.length) models[k] = pts;
  }
  return {
    spectrum_id: str(m.spectrum_id), best: fit(m.best), runner_up: fit(m.runner_up),
    delta_chi2: numOrNull(m.delta_chi2), verdict: str(m.verdict) || `Best match: ${m.best.type}.`,
    confidence: ['high', 'medium', 'low'].includes(m.confidence) ? m.confidence : 'low',
    candidates: arr(m.candidates).filter((c) => str(c?.type)).map((c) => ({ type: c.type, chi2: numOrNull(c.chi2) })),
    models, method: str(m.method),
    class: CLASSES.includes(m.class) ? m.class : null,
    type_range: Array.isArray(m.type_range) && m.type_range.length === 2 && m.type_range.every(str) ? [m.type_range[0], m.type_range[1]] : null,
    range_open_cold: m.range_open_cold === true,
    range_open_warm: m.range_open_warm === true,
    pair: cleanPair(m.pair),
    delta_class: numOrNull(m.delta_class),
    bands_detected: strings(m.bands_detected),
    per_pass: cleanPasses(m.per_pass),
    pass_agreement: cleanAgreement(m.pass_agreement),
    // A caution sentence when the type stands but should be read as provisional.
    provisional: str(m.provisional) || null,
  };
}

/** Optional per-pass calls; [] when absent or unusable. */
function cleanPasses(v) {
  return arr(v).filter((p) => p && typeof p === 'object' && (str(p.type) || CLASSES.includes(p.class)))
    .map((p) => ({ id: str(p.id), label: str(p.label) || str(p.id),
      class: CLASSES.includes(p.class) ? p.class : null, type: str(p.type) }));
}

/** Optional pipeline verdict on whether the passes agree; null without a readable sentence. */
function cleanAgreement(a) {
  if (!a || typeof a !== 'object' || !str(a.sentence)) return null;
  return { status: ['agree', 'disagree', 'too few'].includes(a.status) ? a.status : null, sentence: a.sentence };
}

const CLASSES = ['brown dwarf', 'star', 'not a brown dwarf', 'uncertain'];

function cleanPair(p) {
  if (!p || typeof p !== 'object' || !Array.isArray(p.types) || p.types.length !== 2 || !p.types.every(str)) return null;
  return { types: [p.types[0], p.types[1]], chi2: numOrNull(p.chi2), delta_vs_single: numOrNull(p.delta_vs_single), model: str(p.model) };
}

/** Optional vetting numbers; null when absent or empty. */
function cleanVetting(v) {
  if (!v || typeof v !== 'object') return null;
  const out = { w1_mag: numOrNull(v.w1_mag), w2_mag: numOrNull(v.w2_mag), w1_w2: numOrNull(v.w1_w2),
    reduced_pm_w2: numOrNull(v.reduced_pm_w2), catalogue: str(v.catalogue) };
  return Object.values(out).some((x) => x != null) ? out : null;
}

function cleanTarget(t, center) {
  const o = t && typeof t === 'object' ? t : {};
  const hasPos = fin(o.ra) && fin(o.dec);
  return {
    name: str(o.name), slug: str(o.slug), blurb: str(o.blurb),
    ra: hasPos ? o.ra : center.ra, dec: hasPos ? o.dec : center.dec,
    epoch: numOrNull(o.epoch),
    pmra_masyr: numOrNull(o.pmra_masyr), pmdec_masyr: numOrNull(o.pmdec_masyr),
  };
}

function cleanMotion(m) {
  if (!m || !fin(m.pmra_masyr) || !fin(m.pmdec_masyr)) return null;
  return { pmra_masyr: m.pmra_masyr, pmdec_masyr: m.pmdec_masyr, err_masyr: numOrNull(m.err_masyr),
    err_pmra_masyr: numOrNull(m.err_pmra_masyr), err_pmdec_masyr: numOrNull(m.err_pmdec_masyr),
    baseline_years: numOrNull(m.baseline_years), n_detections: numOrNull(m.n_detections),
    // "all_frames": no single image shows the object and all images were fitted at once.
    // Older manifests have no method: null, a motion fitted to single detections.
    method: m.method === 'all_frames' ? 'all_frames' : null, n_frames: numOrNull(m.n_frames) };
}

/**
 * @param {unknown} raw parsed JSON
 * @returns {{manifest: object, problems: string[]}}
 */
export function validateManifest(raw) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) throw new ManifestError('The view data is not a JSON object.');
  const problems = [];
  if (raw.schema !== 1) problems.push(`Unexpected schema version ${JSON.stringify(raw.schema)}; showing what can be read.`);
  const center = raw.center;
  if (!center || !fin(center.ra) || !fin(center.dec)) throw new ManifestError('The view data has no valid centre position.');
  if (!fin(raw.size_px) || raw.size_px <= 0 || !fin(raw.fov_arcsec) || raw.fov_arcsec <= 0) {
    throw new ManifestError('The view data has no valid image size or field of view.');
  }
  const seen = new Set();
  const frames = arr(raw.frames)
    .map((f) => cleanFrame(f, problems))
    .filter((f) => f && !seen.has(f.id) && seen.add(f.id))
    .sort((a, b) => a.mjd - b.mjd);
  if (!frames.length) throw new ManifestError('The view data has no usable image frames.');
  const overlays = raw.overlays && typeof raw.overlays === 'object' ? raw.overlays : {};
  const manifest = {
    schema: raw.schema,
    generated: str(raw.generated),
    target: cleanTarget(raw.target, center),
    center: { ra: center.ra, dec: center.dec },
    fov_arcsec: raw.fov_arcsec,
    size_px: raw.size_px,
    frames,
    track: arr(raw.track).filter((p) => p && fin(p.year) && pair(p.px)).map((p) => ({ year: p.year, px: pair(p.px) })),
    spectra: arr(raw.spectra).map((s) => cleanSpectrum(s, problems)).filter(Boolean),
    match: cleanMatch(raw.match, problems),
    features: arr(raw.features).filter((f) => str(f?.label) && pair(f.wl_um)).map((f) => ({ label: f.label, wl_um: pair(f.wl_um) })),
    overlays: {
      gaia: arr(overlays.gaia).map(cleanSource).filter(Boolean),
      catwise: arr(overlays.catwise).map(cleanSource).filter(Boolean),
    },
    measured_motion: cleanMotion(raw.measured_motion),
    motion_not_measured: cleanNotMeasured(raw.motion_not_measured),
    field: cleanField(raw.field),
    field_movers: cleanFieldMovers(raw.field_movers), // optional; null for older views and bodies
    vetting: cleanVetting(raw.vetting),
    warnings: strings(raw.warnings),
    degraded: raw.degraded === true,
    credits: strings(raw.credits),
    solar_system: cleanSolarSystem(raw.solar_system), // optional; null for a sky-position view
  };
  return { manifest, problems };
}

/** Validate gallery/index.json. Returns the usable targets (may be empty). */
export function validateIndex(raw) {
  if (!raw || typeof raw !== 'object') throw new ManifestError('The gallery index is not a JSON object.');
  return arr(raw.targets)
    .filter((t) => t && str(t.slug) && /^[a-z0-9][a-z0-9-]*$/i.test(t.slug))
    .map((t) => ({
      slug: t.slug, name: str(t.name) || t.slug, blurb: str(t.blurb),
      manifest: str(t.manifest) || `${t.slug}/manifest.json`, thumb: str(t.thumb),
      known_type: str(t.known_type), tool_type: str(t.tool_type),
      group: str(t.group),
      ra: fin(t.ra) && t.ra >= 0 && t.ra < 360 ? t.ra : null,
      dec: fin(t.dec) && t.dec >= -90 && t.dec <= 90 ? t.dec : null,
    }));
}

/** A type label from the matcher that means "not a brown dwarf" (e.g. "star (4500 K)"). */
export const isStarType = (type) => typeof type === 'string' && /^star\b/i.test(type.trim());
