// "Notes about this view": the manifest's warnings gathered behind one quiet disclosure, with a
// short visible line only for a note that changes how the view should be read. Pure; every
// phrase is derived from the manifest's own warnings, never invented.

const HEADLINES = [
  [/spectrum point.*unusable|no spectrum to judge/i, (w) => (/saturat/i.test(w)
    ? 'No spectrum: the star saturates SPHEREx.' : 'No spectrum: no usable SPHEREx points.')],
  [/spectrum is not classified/i, (w) => (/gaia star/i.test(w)
    ? 'Spectrum not classified: a neighbouring star shares the pixel.' : 'Spectrum not classified.')],
  // Only a missing run of years is a headline; a missing 2010 season is background detail.
  [/search for WISE frames.*failed|NEOWISE\)? failed/i, (w) => { const gone = missingWise(w).filter(longGap); return gone.length ? `${gone.join(' and ')} are missing, so the motion rests on fewer frames.` : null; }],
  [/image\(s\) could not be loaded/i, (w) => `${w.replace(/ and show as.*$/i, '')}.`],
];
/**
 * A few words for why a target has no tool type, from its warnings: "saturated",
 * "too faint to classify", "a neighbouring star shares the pixel", else a plain fallback.
 */
export function noTypeWhy(warnings, hasSpectra) {
  const has = (re) => warnings.some((w) => re.test(w));
  if (has(/saturat/i) && has(/unusable|no spectrum/i)) return 'saturated';
  if (has(/gaia star/i) && has(/not classified/i)) return 'a neighbouring star shares the pixel';
  // A partial view (the object's images or the neighbour catalogues did not load): not checked, not a finding.
  if (has(/WISE images could not be loaded/i) && has(/not found in any WISE or SPHEREx image/i)) return 'could not be checked: the WISE images did not load';
  if (has(/checks for neighbours .* could not be run/i)) return 'could not be checked: the catalogues of neighbouring stars did not load';
  if (has(/too faint/i)) return 'too faint to classify';
  if (has(/too little of the spectrum/i)) return 'too little of the spectrum detected';
  return hasSpectra ? 'spectrum too poor to classify' : 'no usable spectrum';
}

const SHARED_LIGHT =/spectrum may include light from a gaia star/i;

/** A one-line reading-changing summary of a warning, or null when it is background detail. */
export function headlineFor(w) {
  for (const [re, say] of HEADLINES) if (re.test(w)) return say(w);
  return null;
}

/**
 * Which WISE frames a failed archive search cost, phase by phase, in the pipeline's own years
 * (src/pxs/wise/search.py PHASE_YEARS): "WISE frames from 2013 to 2024" for NEOWISE, "the 2010
 * three-band WISE frames" for a single-year phase. [] for any other warning.
 * @returns {string[]}
 */
export function missingWise(w) {
  const m = /search for WISE frames from (.+?) failed/i.exec(w);
  if (!m) return /NEOWISE\)? failed/i.test(w) ? ['WISE frames from 2013 to 2024'] : [];
  const phases = [...m[1].matchAll(/(\d{4})(?:-(\d{4}))?(?: \(([^)]+)\))?/g)];
  return phases.map(([, y0, y1, label]) => (y1 ? `WISE frames from ${y0} to ${y1}` : `the ${y0} ${label ? `${label} ` : ''}WISE frames`));
}

/** True when a missing phase spans years of the baseline (NEOWISE), not one 2010 season. */
const longGap = (phrase) => { const y = /from (\d{4}) to (\d{4})/.exec(phrase); return !!y && y[2] - y[1] >= 3; };

const MISSING = [
  [/frame-quality scores.*three-band frames/i, 'a few 2010 WISE frames'],
  [/CatWISE2020 sources could not/i, 'catalogue markers'],
];

/** What the warnings say is missing from the view, as short phrases; [] when they name nothing. */
export function missingParts(warnings) {
  const wise = [...new Set(warnings.flatMap(missingWise))];
  return [...wise, ...MISSING.filter(([re]) => warnings.some((w) => re.test(w))).map(([, t]) => t)];
}

const joinWords = (xs) => (xs.length < 2 ? xs.join('') : `${xs.slice(0, -1).join(', ')} and ${xs.at(-1)}`);

/** The quiet line for a view built from partial data, naming what the warnings say is missing. */
export function degradedLine(warnings) {
  const gone = missingParts(warnings);
  if (!gone.length) return 'Built while an archive service was unavailable, so some data is missing.';
  return `Built while an archive service was unavailable; ${joinWords(gone)} are missing.`;
}

/**
 * @param {string[]} warnings manifest warnings plus page-level problems
 * @param {{degraded?: boolean, live?: boolean, hasMatch?: boolean}} opts
 * @returns {{all: string[], headlines: string[], degradedLine: string|null, count: number}}
 *   `degradedLine` is set for a stored (gallery) degraded view only; a live view keeps its banner.
 */
export function summariseNotes(warnings, { degraded = false, live = false, hasMatch = false } = {}) {
  const all = [...new Set(warnings)];
  const headlines = [];
  for (const w of all) {
    const h = headlineFor(w) || (hasMatch && SHARED_LIGHT.test(w) ? 'The spectrum may include light from a neighbouring star.' : null);
    if (h && !headlines.includes(h)) headlines.push(h);
  }
  return {
    all, headlines, count: all.length,
    degradedLine: degraded && !live ? degradedLine(all) : null,
  };
}
