// Small plain lines for the simple view and the landing: what to look for in the blink, measured
// against catalogue at a glance, the published type in a sentence, the patch against the full Moon,
// and which gallery target to show someone who wants to see something move. Pure.

import { describeMotion, motionHeadline, motionBasis, compassWord, motionSignificant } from './summary.js';
import { VARIABLE_SLUGS, summarySentences } from './variabilitytext.js';
import { setLabel } from './labels.js';

const MOON_ARCSEC = 1800; // the full Moon is about half a degree across
const lowerFirst = (s) => (/^[A-Z][a-z]/.test(s) ? s.charAt(0).toLowerCase() + s.slice(1) : s);

/** Letters whose names start with a vowel sound: "an M4", "an L9", but "a K1", "a T8". */
const VOWEL_LETTERS = 'AEFHILMNORSX';

function article(phrase) {
  if (/^[A-Z][\d.]/.test(phrase)) return VOWEL_LETTERS.includes(phrase[0]) ? 'an' : 'a';
  return /^[aeiou]/i.test(phrase) ? 'an' : 'a';
}

/**
 * The published type as a sentence: a noun phrase ("M4 star", "Dwarf planet, water ice") is
 * "Astronomers list it as an M4 star."; a bare spectral type ("T8", "sdT3") is "Its published type is T8."
 * @param {string|null} known
 */
export function publishedSentence(known) {
  if (!known) return '';
  const t = known.trim();
  if (!/\b(star|giant|dwarf|planet)\b/i.test(t.replace(/\(.*\)/, ''))) return `Its published type is ${t}.`;
  const noun = lowerFirst(t).replace(/^(dwarf planet), /i, '$1 with ');
  return `Astronomers list it as ${article(noun)} ${noun}.`;
}

/**
 * "Measured 10.41 arcsec a year. Catalogue 10.39. They agree." Null without both motions.
 * @returns {{text: string, agree: boolean}|null}
 */
export function motionPill(m) {
  const mm = m.measured_motion;
  const head = motionSignificant(mm) && motionHeadline(mm, m.target);
  if (!head) return null;
  const meas = describeMotion(mm.pmra_masyr, mm.pmdec_masyr).arcsecPerYear;
  const cat = describeMotion(m.target.pmra_masyr, m.target.pmdec_masyr).arcsecPerYear;
  return { text: `Measured ${meas.toFixed(2)} arcsec a year. Catalogue ${cat.toFixed(2)}. ${head.agree ? 'They agree.' : 'They differ by more than our error allows.'}`, agree: head.agree };
}

const yearsWord = (y) => (y < 0.95 ? 'under a year' : `${Math.round(y)} ${Math.round(y) === 1 ? 'year' : 'years'}`);
const arcsec = (x) => (x >= 10 ? x.toFixed(0) : x.toFixed(1));

/** How the object moves in these images: 'none', 'tiny' (under a pixel), 'clear', or null without a fit. */
function motionClass(m) {
  const mm = m.measured_motion;
  if (!mm) return null;
  const d = describeMotion(mm.pmra_masyr, mm.pmdec_masyr);
  if (!motionSignificant(mm)) return { kind: 'none', d };
  const moved = d.arcsecPerYear * mm.baseline_years;
  return { kind: moved < m.fov_arcsec / m.size_px ? 'tiny' : 'clear', d, moved };
}

/** The variable-star line, from data/variability.json's own sentences; null without the data. */
function variableLook(slug, cls, variability) {
  const said = summarySentences(slug, variability)[0] || '';
  const lead = cls?.kind === 'clear' ? 'It also changes in brightness' : cls?.kind === 'tiny' ? 'This one barely moves' : 'This one does not move';
  const r = said.match(/by about ([\d.]+) magnitudes \(a factor of about (\d+)\)/);
  if (slug === 'r-draconis' && r) {
    const period = Math.round(variability.stars[slug].catalogue.period_days);
    // The factor in the data is for the shortest wavelength; the blink plays 4.6 µm, where the swing is smaller.
    return `${lead}: it brightens and fades over its ${period}-day cycle, most strongly at short wavelengths. Play SPHEREx only to see it change.`;
  }
  const w = said.match(/faded by a factor of about ([\d.]+) between (.+?) and (.+?),/);
  if (slug === 'rw-aurigae' && w) return `${lead}: SPHEREx saw it fade by a factor of about ${w[1]} between ${w[2]} and ${w[3]}. Play SPHEREx only to see it.`;
  return null;
}

/**
 * One phrase saying what to watch for in the blink, from the measured motion (and, for the two
 * variable stars, from the variability data when it has loaded).
 * @param {object} m validated manifest
 * @param {{variability?: object|null}} [opts]
 */
export function lookFor(m, { variability = null } = {}) {
  if (m.solar_system) return `The view follows ${m.target.name || 'the body'}: watch the stars slide past behind it.`;
  const cls = motionClass(m);
  const slug = m.target.slug;
  if (variability && VARIABLE_SLUGS.has(slug)) {
    const v = variableLook(slug, cls, variability);
    if (v) return v;
  }
  if (!cls) {
    // In glare (docs/api.md `field.saturated`) the bright patch is the object's glare, not the object.
    if (m.field?.saturated) return 'The ring marks where the object is; what you see around it is mostly its glare, not the object itself.';
    return m.frames.some((f) => f.centroid_px)
      ? 'The ring marks the object. We found it in too few images to measure a motion.'
      : 'We could not find it in these images: the ring marks where the catalogue says it should be.';
  }
  if (motionBasis(m.measured_motion).allFrames) return 'It is too faint to see in single images: the ring marks where it is, and its motion comes from all the images together.';
  const span = yearsWord(m.measured_motion.baseline_years);
  if (cls.kind === 'none') return 'This one does not move measurably: the dot in the ring stays put while the images change.';
  if (cls.kind === 'tiny') return `This one barely moves: about ${arcsec(cls.moved)} arcseconds in ${span}, less than one pixel of these images.`;
  return `Watch the ringed dot drift ${compassWord(cls.d.pa)}, about ${arcsec(cls.moved)} arcseconds in ${span}.`;
}

const ORDINALS = [null, null, 'half', 'third', 'quarter', 'fifth', 'sixth', 'seventh', 'eighth', 'ninth', 'tenth', 'eleventh',
  'twelfth', 'thirteenth', 'fourteenth', 'fifteenth', 'sixteenth', 'seventeenth', 'eighteenth', 'nineteenth', 'twentieth'];

/**
 * The patch shown, against the full Moon: "This patch of sky is 4 arcminutes across, about an eighth of the full Moon's width."
 * @param {number} fovArcsec the image's width
 * @param {number} zoom the view's zoom (the visible patch is fov / zoom)
 */
export function scaleLine(fovArcsec, zoom = 1) {
  const w = fovArcsec / (zoom > 0 ? zoom : 1);
  if (!Number.isFinite(w) || w <= 0) return '';
  const arcmin = w / 60;
  const across = `This patch of sky is ${arcmin >= 10 ? arcmin.toFixed(0) : +arcmin.toFixed(1)} arcminutes across`;
  const ratio = w / MOON_ARCSEC;
  if (ratio >= 0.75) return `${across}, about ${ratio < 1.5 ? 'the' : `${Math.round(ratio)} times the`} full Moon's width.`;
  const n = Math.round(1 / ratio);
  if (n === 2) return `${across}, about half the full Moon's width.`;
  const word = ORDINALS[n];
  return word ? `${across}, about ${/^[ae]/.test(word) ? 'an' : 'a'} ${word} of the full Moon's width.` : `${across}, a tiny part of the full Moon's width.`;
}

const yearSpan = (fs) => { const a = fs[0].date.slice(0, 4), b = fs.at(-1).date.slice(0, 4); return a === b ? a : `${a} to ${b}`; };

/**
 * What the video plays, counted against all the images the full view lists, so the two never seem
 * to disagree; with SPHEREx alone, how often we find the object in those images.
 * @param {object[]} active the frames being played
 * @param {object[]} all every frame of the view
 */
export function videoLine(active, all) {
  const parts = ['WISE', 'SPHEREx'].map((mission) => {
    const fs = active.filter((f) => f.mission === mission);
    return fs.length ? `${fs.length} from ${setLabel(fs[0])}, ${yearSpan(fs)}` : null;
  }).filter(Boolean);
  const head = `This video plays ${active.length} of all ${all.length} images, the ones at one wavelength so they compare: ${parts.join(", and ")}.`;
  if (!active.length || active.some((f) => f.mission !== 'SPHEREx')) return head;
  const found = active.filter((f) => f.centroid_px).length;
  if (!found) return `${head} It is too faint to see in these SPHEREx images; the ring marks where it should be.`;
  return found < active.length ? `${head} We find the object in ${found} of these ${active.length} SPHEREx images; it is faint at this wavelength.` : head;
}

/** "SPHEREx only: 23 images, 2025 to 2026" for the SPHEREx frames the switch would play. */
export function spherexLabel(frames) {
  const y0 = frames[0]?.date.slice(0, 4), y1 = frames.at(-1)?.date.slice(0, 4);
  const n = frames.length;
  return `SPHEREx only: ${n} ${n === 1 ? 'image' : 'images'}${y0 ? `, ${y0 === y1 ? y0 : `${y0} to ${y1}`}` : ''}`;
}

/**
 * A gallery target that clearly moves in its blink (at least five pixels), chosen with rand(); null when none.
 * @param {{entry: {slug: string}, manifest: object|null}[]} cands the landing's loaded gallery
 * @param {() => number} rand
 */
export function pickMover(cands, rand) {
  const movers = cands.filter(({ entry, manifest: m }) => {
    if (!m || m.solar_system || VARIABLE_SLUGS.has(entry.slug)) return false;
    const cls = motionClass(m);
    return cls?.kind === 'clear' && cls.moved >= 5 * (m.fov_arcsec / m.size_px);
  });
  return movers.length ? movers[Math.min(movers.length - 1, Math.floor(rand() * movers.length))].entry.slug : null;
}
