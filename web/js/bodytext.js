// Solar System body mode, pure parts: clean the manifest's `solar_system` block (docs/api.md),
// band-depth wording that can never print an impossible depth, the reflectance spectra for the
// plot, the plain sentence on what SPHEREx sees and the Planet X note. No DOM here.

const fin = (v) => typeof v === 'number' && Number.isFinite(v);
const str = (v) => (typeof v === 'string' && v.trim() ? v : null);
const arr = (v) => (Array.isArray(v) ? v : []);
const obj = (v) => v && typeof v === 'object' && !Array.isArray(v);
const num = (v) => (fin(v) ? v : null);
const median = (xs) => {
  const v = xs.filter(fin).sort((a, b) => a - b);
  return v.length ? v[Math.floor(v.length / 2)] : null;
};

const Z95 = 1.645; // one-sided 95%, as src/pxs/solarsystem/bands.py
const SAT_SIGMA = 2.0;
export const ALL = 'all-detected';
const OUTCOMES = ['detected', 'marginal', 'not detected'];

function cleanDepth(d) {
  if (!obj(d) || !str(d.label)) return null;
  return { label: d.label, wl_um: arr(d.wl_um).filter(fin).slice(0, 2), ratio: num(d.ratio), err: num(d.err), depth: num(d.depth),
    depth_min: num(d.depth_min), saturated: d.saturated === true, sigma: num(d.sigma), detected: d.detected === true };
}

function cleanRefl(r) {
  if (!obj(r) || !str(r.spectrum_id)) return null;
  const points = arr(r.points).filter((p) => obj(p) && fin(p.wl_um) && fin(p.refl))
    .map((p) => ({ wl_um: p.wl_um, bw_um: num(p.bw_um), refl: p.refl, err: num(p.err) }));
  return { spectrum_id: r.spectrum_id, r_au: num(r.r_au), points, band_depths: arr(r.band_depths).map(cleanDepth).filter(Boolean), reading: str(r.reading) };
}

function cleanPass(p) {
  if (!obj(p) || !str(p.id)) return null;
  return { id: p.id, date_start: str(p.date_start), date_end: str(p.date_end), n_measured: num(p.n_measured), n_frames: num(p.n_frames),
    best_band: str(p.best_band), best_snr: num(p.best_snr), detected: p.detected === true,
    outcome: OUTCOMES.includes(p.outcome) ? p.outcome : (p.detected === true ? 'detected' : 'not detected'),
    bands: arr(p.bands).filter((b) => obj(b) && str(b.band)),
    ephemeris: arr(p.ephemeris).filter(obj) };
}

/** The validated `solar_system` block, or null when the manifest is an ordinary sky view. */
export function cleanSolarSystem(raw) {
  if (!obj(raw) || !Array.isArray(raw.passes)) return null;
  const bf = obj(raw.body_frames) ? raw.body_frames : {};
  return {
    designation: str(raw.designation), type: str(raw.type), composition: str(raw.composition), composition_ref: str(raw.composition_ref),
    shown_pass: str(raw.shown_pass),
    passes: raw.passes.map(cleanPass).filter(Boolean),
    reflectance: arr(raw.reflectance).map(cleanRefl).filter(Boolean),
    body_frames: { note: str(bf.note), size_px: num(bf.size_px),
      frames: arr(bf.frames).filter((f) => obj(f) && str(f.id) && str(f.band) && str(f.image))
        .map((f) => ({ id: f.id, band: f.band, wavelength_um: arr(f.wavelength_um).filter(fin).slice(0, 2), image: f.image,
          date: str(f.date), n_exposures: num(f.n_exposures) })) },
    sky_track_arcsec: num(raw.sky_track_arcsec),
    method: str(raw.method),
  };
}

/** Pipeline text uses ASCII "um" and "+-"; show µm and ±. */
export const pretty = (s) => (s || '').replace(/ \+- /g, ' ± ').replace(/(\d) ?um\b/g, '$1 µm');

/** 95% lower limit on a saturated band's depth (also for older manifests without the field), else null. */
function lowerLimit(d) {
  if (d.saturated && fin(d.depth_min)) return d.depth_min;
  if (fin(d.ratio) && fin(d.err) && (d.ratio < SAT_SIGMA * d.err || (fin(d.depth) && d.depth > 1))) {
    return Math.max(0, 1 - (Math.max(d.ratio, 0) + Z95 * d.err));
  }
  return null;
}

const pct = (x) => `${Math.round(x * 100)}%`;

/**
 * A band depth in words. Saturated bands (and older manifests whose depth exceeds 100%) read as a
 * 95% lower limit, never as the impossible number.
 */
export function depthText(d) {
  if (!fin(d.ratio) && !fin(d.depth) && !fin(d.depth_min)) return 'no data in this window';
  const min = lowerLimit(d);
  if (min != null) return `saturated: deeper than ${pct(min)} (95% confidence)`;
  const depth = fin(d.depth) ? d.depth : 1 - d.ratio;
  const text = `${pct(depth)} ± ${pct(d.err ?? 0)}`;
  return d.detected ? text : `${text}, not significant`;
}

/**
 * The pass's reading with its band list rebuilt from the band depths (depthText), so the sentence
 * rounds every depth and error as the table does; the rest is kept as the manifest writes it.
 */
export function readingText(refl) {
  const s = refl?.reading || '';
  const seen = (refl?.band_depths || []).filter((d) => d.detected);
  const head = /^SPHEREx sees absorption at .*? \(depth against/.exec(s);
  if (!head || !seen.length) return pretty(s);
  const parts = seen.map((d) => `${d.label} ${depthText(d)}`).join('; ');
  return pretty(`SPHEREx sees absorption at ${parts} (depth against${s.slice(head[0].length)}`);
}

const isoDay = (s) => (s || '').slice(0, 10);
const choiceLabel = (ss, id) => (id === ALL ? 'All detected passes'
  : `Pass of ${isoDay(ss.passes.find((p) => p.id === id)?.date_start) || id}`);

/** The reflectance blocks as spectrum objects for spectrum.js: all passes first, then by date. */
export function reflSpectra(ss) {
  const order = (r) => (r.spectrum_id === ALL ? 0 : 1);
  return [...ss.reflectance].sort((a, b) => order(a) - order(b)).map((r) => ({
    id: r.spectrum_id, label: choiceLabel(ss, r.spectrum_id), unit: 'relative',
    date_start: null, date_end: null, missing: [],
    points: r.points.map((p) => ({ wl_um: p.wl_um, bw_um: p.bw_um, flux: p.refl, err: p.err, flagged: false, detector: null })),
  }));
}

/**
 * A y range for a reflectance plot set by the points short of 3.8 µm, where the ice bands are;
 * the faint long-wavelength points may fall outside it (double-click the plot shows them all).
 */
export function reflYRange(spec) {
  const v = spec.points.filter((p) => p.wl_um < 3.8 && fin(p.flux)).map((p) => p.flux).sort((a, b) => a - b);
  if (!v.length) return null;
  const lo = Math.min(-0.2, v[Math.floor(v.length * 0.01)] * 1.1), hi = Math.max(1.2, v[Math.floor(v.length * 0.99)] * 1.15);
  return [lo, hi];
}

/** The pass selector's choices, {id, label}, in the same order as reflSpectra. */
export const passChoices = (ss) => reflSpectra(ss).map((s) => ({ id: s.id, label: s.label }));

/** Body-centred images of one pass, in band order; "all passes" shows the pass in the blink. */
export function bodyFrames(ss, id) {
  const pass = id === ALL ? ss.shown_pass : id;
  return ss.body_frames.frames.filter((f) => f.id.startsWith(`${pass}-`)).sort((a, b) => a.band.localeCompare(b.band));
}

const byPrefix = (depths, p) => depths.find((d) => d.label.startsWith(p) && (fin(d.ratio) || fin(d.depth)));
const umOf = (d) => d.label.split(' ')[0];
const isSat = (d) => lowerLimit(d) != null;
// A saturated band counts at its lower limit: conservative when it is the deeper one.
const depthOf = (d) => lowerLimit(d) ?? d.depth;

function icePattern(depths) {
  const a = byPrefix(depths, '2.0'), b = byPrefix(depths, '2.3');
  if (!a || !b || !fin(depthOf(a)) || !fin(depthOf(b)) || !fin(a.err) || !fin(b.err)) return '';
  const diff = depthOf(a) - depthOf(b), err = Math.hypot(a.err, b.err);
  if (a.detected && diff > 2 * err) return 'water ice';
  if (b.detected && -diff > 2 * err) return 'methane ice';
  return '';
}

const listUm = (xs) => (xs.length > 1 ? `${xs.slice(0, -1).join(', ')} and ${xs.at(-1)} µm` : `${xs[0]} µm`);

/** One plain sentence on what the reflectance shows, e.g. "SPHEREx sees Haumea's water ice: ...". */
export function iceSentence(name, refl) {
  const depths = refl?.band_depths || [];
  const seen = depths.filter((d) => d.detected);
  if (!seen.length) return `In this pass SPHEREx does not see a clear ice band on ${name}; the light is reflected sunlight with no dip measured at 3 sigma.`;
  const dips = seen.filter((d) => !isSat(d)).map(umOf);
  const black = seen.filter(isSat).map(umOf);
  const parts = [];
  if (dips.length) parts.push(`its reflected sunlight dips at ${listUm(dips)}`);
  if (black.length) parts.push(`almost no light comes back at ${listUm(black)}`);
  const pat = icePattern(depths);
  // The pattern rests on the 2.0 and 2.3 µm depths only, not on every dip listed.
  const what = pat === 'water ice' ? 'with the 2.0 and 2.3 µm depths giving the fingerprint of frozen water'
    : pat === 'methane ice' ? 'with the 2.0 and 2.3 µm depths giving the fingerprint of frozen methane' :'absorption by ice, though these bands alone do not say which';
  const lead = pat ? `SPHEREx sees ${name}’s ${pat}` : `SPHEREx sees ice absorption on ${name}`;
  return `${lead}: ${parts.join(', and ')}, ${what}.`;
}

const shown = (ss) => ss.passes.find((p) => p.id === ss.shown_pass) || ss.passes.find((p) => p.detected) || null;

/** Distances and rate from the shown pass's ephemeris (medians), and how far it moved in the blink. */
export function bodyFacts(ss) {
  const eph = shown(ss)?.ephemeris || [];
  const med = (k) => median(eph.map((e) => e[k]));
  return { rate: med('rate_arcsec_h'), r_au: med('r_au'), delta_au: med('delta_au'), vmag: med('vmag'), track: ss.sky_track_arcsec };
}

const sig2 = (x) => Number(x.toPrecision(2)).toLocaleString('en-US');
// One significant figure in plain decimals ("0.0003"), never exponent form; below 1e-6 "under 0.000001".
const snr1 = (x) => (x < 1e-6 ? 'under 0.000001' : Number(x.toPrecision(1)).toLocaleString('en-US', { maximumSignificantDigits: 1 }));

/**
 * Which ice the body's published composition names, in one line under the band-depth table, whose
 * column lists every ice with a band near each window in general. Read from `ss.composition` only.
 */
export function compositionIceNote(name, ss) {
  const c = ss?.composition || '';
  const water = /water/i.test(c), methane = /methane|CH4/i.test(c);
  if (!water && !methane) return '';
  const lead = `The column lists every ice with a band near each window, not what ${name} has.`;
  if (water && methane) return `${lead} Its published composition names both water and methane ice.`;
  const [ice, other, tag] = water ? ['water ice', 'methane ice', 'H2O'] : ['methane ice', 'water ice', 'CH4'];
  // Windows (from the table's own rows) where only the other ice has a band: a dip there is not read as this ice.
  const rows = ss.reflectance?.[0]?.band_depths || [];
  const others = rows.filter((d) => !d.label.includes(tag)).map(umOf);
  const read = `Its published composition names ${ice} and not ${water ? 'methane' : 'water ice'}, so we read the dips in windows where ${ice} has a band as ${ice}`;
  if (!others.length) return `${lead} ${read}.`;
  const one = others.length === 1;
  return `${lead} ${read}; ${one ? 'a dip' : 'dips'} at ${listUm(others)}, where only ${other} has a band, ${one ? 'is' : 'are'} left unassigned.`;
}

/**
 * What this means for Planet X, from the measured numbers: reflected light falls as distance^-4
 * (sunlight in, and back out), so the shown pass's S/N scales by (r / 300 au)^4.
 */
export function planetXNote(name, ss) {
  const p = shown(ss);
  const r = bodyFacts(ss).r_au;
  const tail = 'This page shows the tracking method on known bodies; it is not a search and not a detection.';
  if (!p || !fin(r) || !fin(p.best_snr)) return `A body at 300 to 1000 au would be far fainter than ${name}. ${tail}`;
  const k300 = (300 / r) ** 4, k1000 = (1000 / r) ** 4;
  return `${name} is about ${Math.round(r)} au from the Sun. Reflected sunlight fades as the fourth power of distance, so a body of the same size and reflectivity would be about ${sig2(k300)} times fainter at 300 au and ${sig2(k1000)} times at 1,000 au: SPHEREx measured ${name} at S/N ${Math.round(p.best_snr)} in one pass, which at the same noise would become S/N ${snr1(p.best_snr / k300)} at 300 au and ${snr1(p.best_snr / k1000)} at 1,000 au. A larger planet would be brighter in proportion to its area, and it would move far more slowly. ${tail}`;
}

/**
 * The detection rule in words with this body's counts. "marginal" (one band only) is what empty sky
 * beside known bodies gives in about 6% of passes.
 */
export function detectionNote(ss) {
  const n = ss.passes.length;
  const count = (o) => ss.passes.filter((p) => p.outcome === o).length;
  const m = count('marginal');
  const det = `${count('detected')} of ${n} pass${n === 1 ? ' is' : 'es are'} detected`;
  const marg = m ? `; ${m} ${m === 1 ? 'is' : 'are'} marginal (S/N 5 in one band only, which empty sky next to known bodies also gives in about 6% of passes, so it is not counted)` : '';
  return `A pass counts as detected when the body is at S/N 5 or more in at least two detector bands (or 50 when saturation leaves only one band) after the background control is subtracted. ${det}${marg}.`;
}
