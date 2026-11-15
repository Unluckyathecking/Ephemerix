// The plain sentences of the simple view: is it moving, how far over how many years, and what it
// probably is. Built on the same tests as the full view (summary.js, verdict.js); never stronger. Pure.

import { describeMotion, motionHeadline, noMotionReason, motionSignificant, nothingVisible } from './summary.js';
import { verdictTiles } from './verdict.js';
import { missingParts } from './notes.js';
import { bodyFacts } from './bodytext.js';
import { publishedSentence } from './simplelook.js';

const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
const lowerFirst = (s) => (/^[A-Z][a-z]/.test(s) ? s.charAt(0).toLowerCase() + s.slice(1) : s);
const stop = (s) => (/[.!?]$/.test(s) ? s : `${s}.`);
const joinWords = (xs) => (xs.length < 2 ? xs.join('') : `${xs.slice(0, -1).join(', ')} and ${xs.at(-1)}`);

/** "3 May 2025" from an ISO date; '' when unreadable. */
export function plainDate(iso) {
  const m = String(iso ?? '').match(/^(\d{4})-(\d{2})-(\d{2})/);
  return m ? `${Number(m[3])} ${MONTHS[Number(m[2]) - 1]} ${m[1]}` : '';
}

/** "SPHEREx image, 3 May 2025": what the frame on screen is. */
export function frameCaption(f) {
  return f ? `${f.mission || 'Sky'} image, ${plainDate(f.date)}` : '';
}

/** "23 images: 12 from WISE (2010 to 2020) and 11 from SPHEREx (2025 to 2026)." */
export function missionLine(frames) {
  const parts = ['WISE', 'SPHEREx'].map((mission) => {
    const fs = frames.filter((f) => f.mission === mission);
    if (!fs.length) return null;
    const y0 = fs[0].date.slice(0, 4), y1 = fs.at(-1).date.slice(0, 4);
    return `${fs.length} from ${mission} (${y0 === y1 ? y0 : `${y0} to ${y1}`})`;
  }).filter(Boolean);
  const n = frames.length;
  return `${n} ${n === 1 ? 'image' : 'images'}${parts.length ? `: ${joinWords(parts)}` : ''}.`;
}

const arcsec = (x) => (x >= 10 ? x.toFixed(0) : x.toFixed(1));

/** "16 years", "1 year", "under a year"; '' when unknown. */
function yearsText(y) {
  if (!Number.isFinite(y) || y <= 0) return '';
  if (y < 0.95) return 'under a year';
  const n = Math.round(y);
  return `${n} ${n === 1 ? 'year' : 'years'}`;
}

/**
 * Is it moving, how far, over how many years, and does that match the catalogue. One or two sentences.
 * @param {object} m validated manifest
 */
export function motionSentence(m, { withCatalogue = true } = {}) {
  if (m.solar_system) {
    const rate = bodyFacts(m.solar_system).rate;
    return Number.isFinite(rate)
      ? `It is moving along its orbit, about ${rate.toFixed(1)} arcseconds an hour, so the view follows it and the stars slide past.`
      : 'It is moving along its orbit, so the view follows it and the stars slide past.';
  }
  const mm = m.measured_motion;
  if (!mm && nothingVisible(m)) return 'Nothing is visible at this position in these infrared images. An object can be too faint, or too blue, for WISE and SPHEREx to see.';
  if (!mm) return stop(`We could not measure a motion: ${lowerFirst(noMotionReason(m) || 'too few detections')}`);
  const d = describeMotion(mm.pmra_masyr, mm.pmdec_masyr);
  const span = yearsText(mm.baseline_years);
  if (!motionSignificant(mm)) return `We see no motion we can measure${!span ? '' : span === 'under a year' ? ' in under a year' : ` over ${span}`}.`;
  const rate = `about ${d.arcsecPerYear.toFixed(2)} arcseconds a year`;
  const moved = d.arcsecPerYear * mm.baseline_years;
  // Under one image pixel the video cannot show it, however well the fit measures it.
  const pixel = m.fov_arcsec / m.size_px;
  const unseen = Number.isFinite(pixel) && moved < pixel ? ', too small to see in these images' : '';
  const lead = span
    ? `It is moving: ${span === "under a year" ? "in under a year of measurements" : `over the ${span === "1 year" ? "year" : span} we could measure it,`} it crossed ${arcsec(moved)} arcseconds of sky${unseen}, ${rate}.`
    : `It is moving, ${rate}.`;
  const head = motionHeadline(mm, m.target);
  if (!head) return `${lead} There is no catalogue motion to compare with.`;
  if (!withCatalogue) return lead; // said beside it, with both numbers (simplelook.motionPill)
  return head.agree ? `${lead} That matches the catalogue.` : `${lead} That differs from the catalogue value, so the full analysis is worth a look.`;
}

const BODY = {
  'Ice bands seen': 'SPHEREx sees ice bands in the sunlight it reflects.',
  'No ice band seen': 'SPHEREx sees no ice band in the sunlight it reflects.',
  'Marginal detection': 'SPHEREx barely detects it here, so we do not count it.',
  'Not detected': 'SPHEREx does not detect it in the pass shown.',
};

function spectrumWords(m, tile) {
  if (m.solar_system) return BODY[tile.value] || '';
  const match = m.match;
  if (!match) {
    return tile.value === 'Unclassified' ? stop(`We leave it unclassified: ${tile.sub}`) : stop(`We cannot say what it is from SPHEREx: ${tile.sub}`);
  }
  if (match.pair?.types?.length === 2) return `Its SPHEREx spectrum fits best as two brown dwarfs blended together (${match.pair.types.join(' and ')}).`;
  if (tile.value === 'Not a brown dwarf') return 'Its SPHEREx spectrum does not look like a brown dwarf.';
  if (tile.value === 'Uncertain') return 'Its SPHEREx spectrum fits no single type clearly, so we leave the type uncertain.';
  const cls = typeof match.class === 'string' && match.class ? match.class : 'brown dwarf';
  const prov = match.provisional ? ' This type is provisional.' : '';
  return `Its SPHEREx spectrum looks most like a ${cls} of type ${lowerFirst(tile.value)}.${prov}`;
}

/**
 * What it probably is, from the SPHEREx spectrum, then the published type when we know it.
 * @param {object} m validated manifest
 * @param {{knownType?: string|null}} [opts] the published type of a gallery target
 */
export function whatSentence(m, { knownType = null } = {}) {
  const tile = verdictTiles(m).find((t) => t.key === 'spectrum');
  const known = knownType ? ` ${publishedSentence(knownType)}` : '';
  return `${spectrumWords(m, tile)}${known}`.trim();
}

/** "This view is partial: ... are missing." or null for a complete view. */
export function partialSentence(m) {
  if (!m.degraded) return null;
  const gone = missingParts(m.warnings);
  return gone.length ? `This view is partial: ${joinWords(gone)} are missing.` : 'This view is partial: an archive was unavailable when it was built.';
}
