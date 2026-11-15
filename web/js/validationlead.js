// The top of the results page in plain words: the two-sentence answer, the five targets the
// brief names in one small table, how the 17 were chosen, and the partial-data tile. Pure: no
// DOM, so node can test it. Every count is read from data/validation.json.

import { motionText, rangeText, isWeakPass } from './validationtext.js';
import { summarySentences } from './variabilitytext.js';

const n = (x) => (Number.isFinite(x) ? x : 0);

/**
 * The answer in two sentences: motions that agree and differ, types that contain the published
 * type, and how many are left unclassified.
 * @param {object} s `summary` of the validation report
 * @returns {[string, string]}
 */
export function resultsLead(s) {
  const m = s?.motion || {}, t = s?.type || {};
  const agree = n(m.failed)
    ? `${n(m.passed)} agree with the catalogue and ${n(m.failed)} ${n(m.failed) === 1 ? 'differs' : 'differ'}`
    : `all ${n(m.passed)} agree with the catalogue`;
  const one = n(t.total) === 1;
  const types = n(t.passed) === n(t.total) && n(t.total) > 1
    ? `all ${n(t.total)} types we gave contain`
    : `${n(t.passed)} of the ${n(t.total)} ${one ? 'type we gave contains' : 'types we gave contain'}`;
  const prov = n(t.provisional) ? ` (${n(t.provisional)} marked provisional)` : '';
  const left = `we left ${n(t.refused)} unclassified rather than guess`;
  const fp = n(t.faint?.passed), fn = fp + n(t.faint?.failed);
  const typeSentence = fn
    ? `From the SPHEREx spectra we gave ${n(t.total) + fn} types: ${types.replace(' types we gave', ' scored types').replace(' type we gave', ' scored type')} the published type${prov}, and ${
      fp === fn ? `the ${fn} more for ${fn === 1 ? 'a faint object' : 'faint objects'}, counted apart, ${fn === 1 ? 'also contains it' : 'also contain it'}`
        : `${fp} of the ${fn} more for faint objects, counted apart, contain it`}. Apart from these, ${left}.`
    : `From the SPHEREx spectra, ${types} the published type${prov}, and ${left}.`;
  return [
    `We measured how ${n(m.total)} of our ${n(s?.targets)} targets move across the sky: ${agree}.`,
    typeSentence,
  ];
}

// A long reason, said in a few words; the full reason stays in the spectral-type table.
const TYPE_REASONS = [
  [/saturates the detector/i, 'it saturates the SPHEREx detectors'],
  [/not found in any WISE or SPHEREx image/i, 'not found in any image'],
  [/only \d+ of its points .* usable/i, 'too few usable points in its spectrum'],
  [/Gaia star comes within|brighter catalogued source|neighbour/i, 'a nearby star may add its light'],
];

/**
 * Our type against the published one, or why there is none, in a few words.
 * @returns {{verdict: string, text: string}}
 */
export function typeShort(t) {
  const ty = t?.type || {};
  if (ty.best) return { verdict: ty.verdict, text: `${ty.best} (range ${rangeText(ty)}) against ${t.known_type || ty.published || 'no published type'}` };
  const hit = TYPE_REASONS.find(([re]) => re.test(ty.reason || ''));
  return { verdict: ty.verdict, text: `None: ${hit ? hit[1] : 'see the spectral types below'}` };
}

const MOTION_WORD = { pass: 'agrees', fail: 'differs' };

/**
 * Our total motion against the catalogue's ("10.410 / 10.393 ″/yr") and one word for the verdict.
 * @returns {{verdict: string, text: string, word: string}}
 */
export function motionShort(t) {
  const m = t?.motion || {};
  const total = motionText(m).total;
  const word = isWeakPass(m) ? 'consistent (weak test)' : MOTION_WORD[m.verdict] || 'not checked';
  return { verdict: m.verdict, text: total === '—' ? 'not measured' : `${total} ″/yr`, word };
}

/** One row per target the brief names, in report order. */
export function briefRows(report, variability) {
  return (report?.targets || []).filter((t) => t.group === 'brief').map((t) => ({
    slug: t.slug, name: t.name, motion: motionShort(t), type: typeShort(t),
    brightness: summarySentences(t.slug, variability)[0] || null,
  }));
}

const GROUP_WORDS = [
  ['backyard-worlds', 'brown dwarfs found by the Backyard Worlds citizen-science project'],
  ['benchmark', 'well-studied benchmark brown dwarfs'],
];

/** How the targets were chosen, with each group's count from the report. */
export function choiceSentence(targets) {
  const count = (g) => (targets || []).filter((t) => t.group === g).length;
  const others = GROUP_WORDS.filter(([g]) => count(g)).map(([g, words]) => `${count(g)} ${words}`);
  const list = others.length > 1 ? `${others.slice(0, -1).join(', ')} and ${others[others.length - 1]}` : others.join('');
  return `The ${(targets || []).length} targets are the ${count('brief')} the challenge brief names${list ? `, plus ${list}, each with a published spectral type and motion to check against` : ''}.`;
}

/** The scoreboard tile for views built from partial data; at zero it says so plainly. */
export function partialTile(s) {
  const k = n(s?.degraded);
  return { value: String(k), of: `of ${n(s?.targets)}`, label: k ? 'Views built from partial data' : 'Views built from partial data: every view has its full data' };
}
