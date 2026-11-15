// The tiles under a view's title: motion, spectrum, data, and a fourth when there is one
// (the blind search of the patch, or a variable star's brightness). Each says the answer in a few
// words and links to the section that backs it. Pure: everything comes from the manifest.

import { describeMotion, motionHeadline, noMotionReason, motionSignificant, insignificantText, nothingVisible, neighboursUnchecked } from './summary.js';
import { typeRangeText, notBrownDwarf, hasPair, showsType } from './matchtext.js';
import { noTypeWhy, missingParts } from './notes.js';
import { bodyFacts } from './bodytext.js';
import { comoving } from './fieldmovers.js';

/**
 * `calm` is for an answer that stands but is not to be leaned on: a provisional type, a marginal
 * detection. It is drawn quietly (dashed), never as a warning.
 * @typedef {{key: 'motion'|'spectrum'|'data'|'search'|'brightness', href: string, label: string, value: string, sub: string, tone: 'good'|'warn'|'bad'|'quiet'|'calm'}} Tile
 */

const joinWords = (xs) => (xs.length < 2 ? xs.join('') : `${xs.slice(0, -1).join(', ')} and ${xs.at(-1)}`);
const lower = (s) => (/^[A-Z][a-z]/.test(s) ? s.charAt(0).toLowerCase() + s.slice(1) : s).replace(/\.$/, '');

/** True when the tool measured a spectrum and declined to classify it (rather than having none to judge). */
export function isRefusal(m) {
  if (m.match || m.solar_system || !m.spectra.length) return false;
  return !m.warnings.some((w) => /spectrum point is unusable|no spectrum to judge/i.test(w));
}

const WHY = {
  saturated: 'the star saturates SPHEREx',
  'no usable spectrum': 'SPHEREx gave no usable spectrum here',
};

/**
 * The outcome of the pass a body view shows (bodytext.js cleans `outcome` on every pass):
 * 'detected' | 'marginal' | 'not detected'. A manifest without passes counts as detected.
 */
export function bodyOutcome(ss) {
  const passes = ss?.passes || [];
  const shown = passes.find((p) => p.id === ss.shown_pass) || passes.find((p) => p.outcome === 'detected') || passes[0];
  return shown?.outcome || 'detected';
}

function motionTile(m) {
  const base = { key: 'motion', href: '#motion', label: 'Motion' };
  if (m.solar_system) {
    const f = bodyFacts(m.solar_system);
    return Number.isFinite(f.rate)
      ? { ...base, value: `${f.rate.toFixed(1)}″ an hour`, sub: 'followed along its JPL Horizons orbit', tone: 'good' }
      : { ...base, value: 'Followed', sub: 'along its JPL Horizons orbit', tone: 'good' };
  }
  const mm = m.measured_motion;
  const meas = mm && describeMotion(mm.pmra_masyr, mm.pmdec_masyr);
  // The tile carries the first clause of the reason; the motion panel below gives the whole sentence.
  // Nothing found in any image: say what is (not) there, and why that can happen, not a failure.
  // Fitted but too thin to mean anything: the first clause of the pipeline's reason.
  if (!meas && m.motion_not_measured) return { ...base, value: 'Not measured', sub: lower(noMotionReason(m)).split('; ')[0], tone: 'quiet' };
  if (!meas && nothingVisible(m)) return { ...base, value: 'Nothing visible here', sub: 'an object can be too faint or too blue for WISE and SPHEREx', tone: 'quiet' };
  if (!meas) return { ...base, value: 'Not measured', sub: lower(noMotionReason(m) || 'too few detections').split(/ because |, so /)[0], tone: 'quiet' };
  // Within three times its error the figure is not a motion: say so, and keep the figure below.
  if (!motionSignificant(mm)) return { ...base, value: 'No motion we can measure', sub: insignificantText(mm), tone: 'quiet' };
  const value = `${meas.arcsecPerYear.toFixed(2)}″ a year`;
  const head = motionHeadline(mm, m.target);
  if (!head) return { ...base, value, sub: 'no catalogue motion to compare with', tone: 'quiet' };
  const cat = describeMotion(m.target.pmra_masyr, m.target.pmdec_masyr).arcsecPerYear.toFixed(2);
  return head.agree
    ? { ...base, value, sub: `agrees with the catalogue (${cat})`, tone: 'good' }
    : { ...base, value, sub: `differs from the catalogue (${cat})`, tone: 'bad' };
}

function spectrumTile(m, published) {
  const base = { key: 'spectrum', href: '#spectrum', label: 'Spectrum' };
  const pub = published ? `published: ${published}` : null;
  if (m.solar_system) {
    // The pass on screen decides: detected, marginal (one band only, not counted) or not detected.
    const outcome = bodyOutcome(m.solar_system);
    if (outcome === 'marginal') return { ...base, value: 'Marginal detection', sub: 'S/N 5 in one band only, so it is not counted', tone: 'calm' };
    if (outcome === 'not detected') return { ...base, value: 'Not detected', sub: 'in the pass shown', tone: 'quiet' };
    const seen = m.solar_system.reflectance.some((r) => r.band_depths.some((d) => d.detected));
    return { ...base, value: seen ? 'Ice bands seen' : 'No ice band seen', sub: pub || 'in reflected sunlight', tone: seen ? 'good' : 'quiet' };
  }
  const match = m.match;
  if (!match) {
    const why = noTypeWhy(m.warnings, m.spectra.length > 0);
    return isRefusal(m)
      ? { ...base, value: 'Unclassified', sub: WHY[why] || why, tone: 'warn' }
      : { ...base, value: 'No spectrum', sub: WHY[why] || why, tone: 'quiet' };
  }
  // Partial view: the neighbour checks did not run, so the match below is not yet an answer.
  if (neighboursUnchecked(m)) return { ...base, value: 'Not confirmed', sub: 'the catalogues of neighbouring stars did not load, so the match is unchecked', tone: 'quiet' };
  const conf = `${match.confidence} confidence`;
  if (hasPair(match)) return { ...base, value: `${match.pair.types.join(' + ')} blend`, sub: pub || conf, tone: 'quiet' };
  if (notBrownDwarf(match)) return { ...base, value: 'Not a brown dwarf', sub: pub || conf, tone: 'quiet' };
  if (!showsType(match) || !typeRangeText(match)) return { ...base, value: 'Uncertain', sub: pub || conf, tone: 'quiet' };
  const range = typeRangeText(match);
  const value = range.charAt(0).toUpperCase() + range.slice(1);
  // The pipeline's caution (a neighbour may add light): the type stands, calmly marked.
  if (match.provisional) return { ...base, value, sub: ['provisional', pub].filter(Boolean).join('; '), tone: 'calm' };
  return { ...base, value, sub: pub || conf, tone: match.confidence === 'high' ? 'good' : 'quiet' };
}

function dataTile(m) {
  const base = { key: 'data', href: '#data', label: 'Data' };
  const fs = m.frames;
  const n = `${fs.length} ${fs.length === 1 ? 'image' : 'images'}`;
  const missions = [...new Set(fs.map((f) => f.mission))].filter(Boolean);
  const y0 = fs[0]?.date.slice(0, 4), y1 = fs.at(-1)?.date.slice(0, 4);
  const span = !y0 ? '' : y0 === y1 ? `${y0}` : `${y0} to ${y1}`;
  const from = [span, joinWords(missions)].filter(Boolean).join(', ');
  if (m.degraded) {
    const gone = missingParts(m.warnings);
    return { ...base, value: `${n}, partial`, sub: gone.length ? `${joinWords(gone)} are missing` : 'built while an archive was unavailable', tone: 'warn' };
  }
  return { ...base, value: n, sub: from, tone: 'good' };
}

const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

/** The blind search of the patch (fieldmovers.js) in a few words, or null when it did not run. */
export function searchTile(m) {
  const fm = m.field_movers;
  if (!fm || fm.status !== 'searched') return null;
  const base = { key: 'search', href: '#movers', label: 'Search', sub: 'blind search of this patch' };
  const scale = m.fov_arcsec / m.size_px;
  const shared = fm.movers.map((mv) => comoving(mv, fm.movers, scale, m)).filter(Boolean);
  if (shared.some((c) => c.distance === 'same')) return { ...base, value: 'Its companion star, found blind', tone: 'good' };
  if (shared.length) return { ...base, value: 'A star moves with it', tone: 'good' };
  const known = fm.movers.filter((mv) => mv.label === 'gaia' || mv.label === 'catwise').length;
  if (known) return { ...base, value: plural(known, 'known mover', 'known movers'), tone: 'quiet' };
  const tracks = fm.movers.filter((mv) => mv.label === 'candidate').length || fm.n_candidates;
  if (tracks) return { ...base, value: plural(tracks, 'unexplained track', 'unexplained tracks'), tone: 'quiet' };
  return { ...base, value: 'Nothing else moved', tone: 'quiet' };
}

/**
 * A variable star's finding (variabilitytext.js shortFinding) as a tile: the name dropped and
 * its first clause split into a short value and a sub-line; the whole finding is in the block
 * the tile links to.
 */
export function brightnessTile(finding) {
  const clause = finding.replace(/^(R Draconis|RW Aurigae) /, '').split(/; | between |\./)[0];
  // "brightens and fades | every 246 days", "dimmed to about 60% | of its earlier infrared brightness"
  const [, value = clause, sub = 'measured in SPHEREx images'] = clause.match(/^(.*?) ((?:every|of) .*)$/) || [];
  return { key: 'brightness', href: '#variability', label: 'Brightness', value: value.charAt(0).toUpperCase() + value.slice(1), sub, tone: 'good' };
}

/**
 * @param {object} m validated manifest
 * @param {{published?: string|null, variable?: boolean, finding?: string|null}} [opts] the published
 *   type, for a gallery target; for a variable star, its brightness finding once it has arrived
 * @returns {Tile[]} motion, spectrum, data, then search or brightness when there is one (four at most)
 */
export function verdictTiles(m, { published = null, variable = false, finding = null } = {}) {
  const fourth = variable ? (finding ? brightnessTile(finding) : null) : searchTile(m);
  return [motionTile(m), spectrumTile(m, published), dataTile(m), fourth].filter(Boolean);
}
