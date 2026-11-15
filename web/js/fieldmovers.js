// "What else moved in this patch?" (docs/api.md `field_movers`): the pipeline's search of every
// WISE visit for anything else that moved. `cleanFieldMovers` validates the block; the words and
// positions are pure; `fieldMoversSection` (Advanced) and `fieldMoversLine` (Simple) build the DOM.

import { el } from './dom.js';
import { direction, roundSig } from './facts.js';
import { gaiaCounterpart } from './gaiacheck.js';

const fin = (v) => typeof v === 'number' && Number.isFinite(v);
const str = (v) => (typeof v === 'string' && v.trim() ? v : null);
const num = (v) => (fin(v) ? v : null);
const pair = (v) => (Array.isArray(v) && v.length === 2 && fin(v[0]) && fin(v[1]) ? [v[0], v[1]] : null);
const LABELS = ['target', 'gaia', 'catwise', 'candidate'];

function cleanMover(mv) {
  if (!mv || typeof mv !== 'object' || !pair(mv.px) || !fin(mv.epoch) || !fin(mv.pmra_masyr) || !fin(mv.pmdec_masyr)) return null;
  return { label: LABELS.includes(mv.label) ? mv.label : 'candidate', gaia_id: str(mv.gaia_id), catwise_id: str(mv.catwise_id),
    px: pair(mv.px), epoch: mv.epoch, pmra_masyr: mv.pmra_masyr, pmdec_masyr: mv.pmdec_masyr, err_masyr: num(mv.err_masyr),
    motion_arcsec_yr: num(mv.motion_arcsec_yr), n_epochs: num(mv.n_epochs) };
}

/** The validated block, or null when the manifest has none (older views, Solar System bodies). */
export function cleanFieldMovers(raw) {
  if (!raw || typeof raw !== 'object' || !str(raw.sentence)) return null;
  const movers = (Array.isArray(raw.movers) ? raw.movers : []).map(cleanMover).filter(Boolean);
  return { status: raw.status === 'searched' ? 'searched' : 'not_searched', reason: str(raw.reason), sentence: raw.sentence,
    first_year: num(raw.first_year), last_year: num(raw.last_year), baseline_years: num(raw.baseline_years),
    // Unexplained candidates are only ever shown when the pipeline says they are not withheld.
    movers: movers.filter((mv) => mv.label !== 'candidate' || raw.candidates_withheld === false),
    n_known: num(raw.n_known) ?? 0, n_candidates: num(raw.n_candidates) ?? 0, candidates_withheld: raw.candidates_withheld !== false,
    null_count: num(raw.null_count), null_max: num(raw.null_max), null_trials: num(raw.null_trials) };
}

/** Who the mover is, in a few words. */
export function moverName(mv) {
  if (mv.label === 'target') return 'The target itself, found without being told where it is';
  if (mv.label === 'gaia') return `Gaia DR3 ${mv.gaia_id || 'star'}, already known to move`;
  if (mv.label === 'catwise') return `CatWISE2020 ${mv.catwise_id || 'source'}, already catalogued as moving`;
  return 'Unexplained track';
}

/** "8.16 ± 0.03 arcsec a year towards the west". */
export function moverMotion(mv) {
  const total = fin(mv.motion_arcsec_yr) ? mv.motion_arcsec_yr : Math.hypot(mv.pmra_masyr, mv.pmdec_masyr) / 1000;
  const err = fin(mv.err_masyr) ? ` ± ${roundSig(mv.err_masyr / 1000, 1)}` : '';
  // The target's row is the search's own fit, not the headline's: say so, so the two can differ.
  const own = mv.label === 'target' ? ' (the search\'s own fit)' : '';
  return `${roundSig(total, 3)}${err} arcsec a year towards the ${direction(mv.pmra_masyr, mv.pmdec_masyr).word}${own}`;
}

const COMOVING_MIN_MASYR = 100; // slower than this and a shared motion is not telling
const COMOVING_MAX_FRACTION = 0.05; // the two motions agree to within this share of the target's speed
const PARALLAX_SIGMA = 3; // parallaxes within this many combined errors put the two at one distance

const PARALLAX_MIN_SIGMA = 5; // each parallax must be this significant before it gives a distance
const plx = (g) => (g && fin(g.parallax_mas) && fin(g.parallax_error_mas) && g.parallax_error_mas > 0
  && g.parallax_mas >= PARALLAX_MIN_SIGMA * g.parallax_error_mas ? g : null);
const plxText = (g) => `${g.parallax_mas.toFixed(2)} ± ${g.parallax_error_mas.toFixed(2)} mas`;

/**
 * Gaia parallaxes for a mover and the target (its Gaia counterpart, gaiacheck.js), from the
 * manifest's own `overlays.gaia`; null unless both are there.
 */
export function parallaxPair(m, mv) {
  const star = plx((m?.overlays?.gaia || []).find((g) => g.id === mv.gaia_id));
  const c = m && gaiaCounterpart(m);
  const target = c?.status === 'match' ? plx(c.source) : null;
  return star && target && star.id !== target.id ? { star, target } : null;
}

/**
 * When a catalogued mover shares the target's motion: the sentence and what Gaia's parallaxes say
 * ('same' or 'different' distance, or null when either is missing); else null. Two unrelated
 * stars this close on the sky do not move the same way at the same speed by chance.
 * @param {object} mv cleaned mover
 * @param {object[]} movers every cleaned mover in the block
 * @param {number} scale arcsec per pixel
 * @param {object} [m] the manifest, for the Gaia parallaxes
 * @param {{numbers?: boolean}} [opts] numbers: false leaves the parallax values out (Simple)
 * @returns {{line: string, distance: 'same'|'different'|null}|null}
 */
export function comoving(mv, movers, scale, m = null, { numbers = true } = {}) {
  const target = movers.find((o) => o.label === 'target');
  if (!target || mv.label === 'target' || mv.label === 'candidate' || !fin(scale)) return null;
  const speed = Math.hypot(target.pmra_masyr, target.pmdec_masyr);
  const apart = Math.hypot(mv.pmra_masyr - target.pmra_masyr, mv.pmdec_masyr - target.pmdec_masyr);
  if (speed < COMOVING_MIN_MASYR || apart > COMOVING_MAX_FRACTION * speed) return null;
  const sep = roundSig(Math.hypot(mv.px[0] - target.px[0], mv.px[1] - target.px[1]) * scale, 2);
  const base = `It moves the same way as the target at the same speed, ${sep} arcsec away on the sky`;
  const p = parallaxPair(m, mv);
  if (!p) return { line: `${base}, so the two are probably travelling together.`, distance: null };
  const both = numbers ? ` (parallax ${plxText(p.star)} for this star and ${plxText(p.target)} for the target)` : '';
  const sigma = Math.hypot(p.star.parallax_error_mas, p.target.parallax_error_mas);
  return Math.abs(p.star.parallax_mas - p.target.parallax_mas) <= PARALLAX_SIGMA * sigma
    ? { line: `${base}, and Gaia puts both at the same distance${both}, so the two travel together.`, distance: 'same' }
    : { line: `${base}, but Gaia puts them at different distances${both}, so they share only a motion on the sky.`, distance: 'different' };
}

/** The sentence of `comoving`, or null. */
export function comovingLine(mv, movers, scale, m = null, opts = {}) {
  return comoving(mv, movers, scale, m, opts)?.line ?? null;
}

/**
 * Where the mover's fitted track puts it at `year`, in image pixels (row 0 north, east to the left).
 * @param {object} mv cleaned mover
 * @param {number} year decimal year
 * @param {number} scale arcsec per pixel
 */
export function moverPx(mv, year, scale) {
  const dt = year - mv.epoch;
  return [mv.px[0] - (mv.pmra_masyr * dt) / 1000 / scale, mv.px[1] - (mv.pmdec_masyr * dt) / 1000 / scale];
}

/** How the search was checked, from the block's own numbers; null when it has none. */
export function checkLine(fm) {
  if (!fin(fm.null_trials) || !fin(fm.null_count) || fm.null_trials < 1) return null;
  const most = fin(fm.null_max) ? ` and ${fm.null_max} at most` : '';
  return `As a check, we shuffled the visit dates ${fm.null_trials} times so that nothing real could line up, and the same search then found ${roundSig(fm.null_count, 2)} movers on average${most}.`;
}

/** The plain line for unexplained tracks we do not show, or null. */
export function withheldLine(fm) {
  const n = fm.n_candidates;
  if (!n || !fm.candidates_withheld) return null;
  return `${n} ${n === 1 ? 'track does' : 'tracks do'} not match any catalogue and ${n === 1 ? 'is' : 'are'} not shown, because we cannot yet tell ${n === 1 ? 'it' : 'them'} from noise.`;
}

/**
 * The Advanced block: the sentence, the check line, the movers found with a toggle each that
 * rings it on the blink, and the withheld note; one reason line when the search did not run.
 * @param {object} m validated manifest
 * @param {(on: Set<number>) => void} onShow the movers (indexes into fm.movers) to ring on the blink
 */
export function fieldMoversSection(m, onShow) {
  const fm = m.field_movers;
  if (!fm) return null;
  const head = el('h2', { id: 'movers-h', text: 'What else moved in this patch?' });
  if (fm.status !== 'searched') {
    return el('section', { class: 'card field-movers', id: 'movers', 'aria-labelledby': 'movers-h' }, [
      head, el('p', { text: fm.sentence }), fm.reason ? el('p', { class: 'small muted', text: `Not searched: ${fm.reason.replace(/\.$/, '')}.` }) : null]);
  }
  const shown = new Set();
  const scale = m.fov_arcsec / m.size_px;
  const items = fm.movers.map((mv, i) => {
    const together = comovingLine(mv, fm.movers, scale, m);
    const box = el('input', { type: 'checkbox', onChange: (e) => { if (e.target.checked) shown.add(i); else shown.delete(i); onShow(new Set(shown)); } });
    return el('li', { class: 'mover' }, [
      el('p', { class: 'mover-name', text: moverName(mv) }),
      el('p', { class: 'small mono', text: moverMotion(mv) }),
      together ? el('p', { class: 'small', text: together }) : null,
      el('label', { class: 'check small' }, [box, ' Ring it on the images']),
    ]);
  });
  // The chance test is the strongest evidence, so it comes straight after the answer.
  return el('section', { class: 'card field-movers', id: 'movers', 'aria-labelledby': 'movers-h' }, [
    head,
    el('p', { text: fm.sentence }),
    checkLine(fm) ? el('p', { class: 'movers-check', text: checkLine(fm) }) : null,
    items.length ? el('ul', { class: 'movers' }, items) : null,
    withheldLine(fm) ? el('p', { class: 'small', text: withheldLine(fm) }) : null,
  ]);
}

/** Simple view: only the sentence, or null. */
export function fieldMoversLine(m) {
  const fm = m?.field_movers;
  if (!fm) return null;
  const together = fm.movers.map((mv) => comovingLine(mv, fm.movers, m.fov_arcsec / m.size_px, m, { numbers: false })).find(Boolean); // Simple: the conclusion, not the parallaxes
  const text = together ? `${fm.sentence} One of them stands out: ${together[0].toLowerCase()}${together.slice(1)}` : fm.sentence;
  return el('p', { class: 'card small field-movers-line', text });
}
