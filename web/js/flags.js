// Plain-word quality notes: per-frame flags and warnings, flagged spectrum points, and
// the reason a spectrum got no type call. Pure. Reasons are picked out of the manifest's
// free-text `warnings`; nothing is invented.

const pct = (x) => `${Math.round(x * 100)}%`;

const KNOWN = [
  [/saturat/i, 'a bright star overloaded the detector here, so brightness and position near it are unreliable.'],
  [/partial coverage/i, 'only some of the exposures cover this spot, so the image is noisier.'],
  [/persist/i, 'a bright source left an after-image on the detector, which can mimic a faint object.'],
  [/neighbou?r|blend|gaia star/i, 'a second star is close enough to blend with the object.'],
];

/** One sentence for a frame warning. */
export function explainWarning(w) {
  const hit = KNOWN.find(([re]) => re.test(w));
  const head = w.charAt(0).toUpperCase() + w.slice(1);
  return hit ? `${head}: ${hit[1]}` : `${head}.`;
}

/**
 * Badge for the frame on screen, or null when it is clean.
 * @returns {{short: string, long: string}|null}
 */
export function frameFlag(f) {
  if (!f) return null;
  const share = Number.isFinite(f.flag_fraction) && f.flag_fraction >= 0.01 ? f.flag_fraction : null;
  if (share == null && !f.warnings.length) return null;
  const short = [share != null && `${pct(share)} flagged`, ...f.warnings].filter(Boolean).join(' · ');
  const long = [
    share != null && `${pct(share)} of the pixels stacked into this image were dropped by the quality flags (for example cosmic-ray hits, saturated or bad pixels), so brightness here is less certain.`,
    ...f.warnings.map(explainWarning),
  ].filter(Boolean).join(' ');
  return { short, long };
}

// Which frame notes change how an image should be read. Most real frames carry a flagged share
// near 1% and "frame quality unknown for N frames"; those are routine and stay out of sight.
const ROUTINE = [/^frame quality unknown/i, /^registered to \d+ gaia/i];
const MATTERS = [
  [/saturat/i, 'saturated'],
  [/catalogued star/i, 'found a known star'],
  [/disagrees with/i, 'position uncertain'],
];
const BIG_FLAG_SHARE = 0.1;

/** The short reading-changing labels of a frame (deduplicated, in order); empty for a routine frame. */
export function frameMatters(f) {
  if (!f) return [];
  const out = [];
  const add = (l) => { if (!out.includes(l)) out.push(l); };
  for (const w of f.warnings || []) {
    if (ROUTINE.some((re) => re.test(w))) continue;
    const hit = MATTERS.find(([re]) => re.test(w));
    add(hit ? hit[1] : 'quality note');
  }
  if (Number.isFinite(f.flag_fraction) && f.flag_fraction >= BIG_FLAG_SHARE) add(`${pct(f.flag_fraction)} flagged`);
  return out;
}

/**
 * The small chip on the image: one short label when one thing matters, else a warning sign and a
 * count. Null for a frame with nothing that changes how it reads. `long` is the full text.
 * @returns {{short: string, long: string}|null}
 */
export function frameChip(f) {
  const m = frameMatters(f);
  if (!m.length) return null;
  return { short: m.length === 1 ? m[0] : `${m.length} notes`, long: frameFlag(f).long };
}

const FLAG_REASON = /flag|saturat|contamin|persist|cosmic|bad pixel/i;
const STRONG_REASON = /not classified|unusable|no spectrum|too faint|type call|too few/i;
const SPEC_REASON = /spectr|faint|classif|type call|s\/n|signal|too few/i;

/** "7 of 102 points were flagged ..." plus reasons from warnings, or null if none flagged. */
export function flaggedNote(spec, warnings = []) {
  const n = spec.points.filter((p) => p.flagged).length;
  if (!n) return null;
  const why = warnings.filter((w) => FLAG_REASON.test(w) && !/synthetic test data/i.test(w));
  return `${n} of ${spec.points.length} points were flagged and left out of the fit (hollow grey dots).${why.length ? ` ${why.join(' ')}` : ''}`;
}

/** Why there is no type call, from the manifest's warnings, or null. */
export function noMatchReason(warnings = []) {
  const real = warnings.filter((w) => !/synthetic test data/i.test(w));
  return real.find((w) => STRONG_REASON.test(w)) || real.find((w) => SPEC_REASON.test(w)) || null;
}

const LEFT_OUT = /spectrum points?\b.*\b(?:left out|unusable)\b/i;

/** Reason phrases for left-out points: per-point `reason` counts, else the pipeline's own warning. */
function missingReasons(missing, warnings) {
  const counts = new Map();
  for (const g of missing) if (g.reason) counts.set(g.reason, (counts.get(g.reason) || 0) + 1);
  if (counts.size) return [...counts].map(([r, n]) => `${r}${counts.size > 1 || n > 1 ? ` ${n}` : ''}`).join(' / ');
  const w = warnings.find((x) => LEFT_OUT.test(x) && /\(([^()]+)\)/.test(x));
  if (!w) return null;
  const inner = w.match(/\(([^()]+)\)/)[1];
  return inner.split(',').map((r) => r.trim().replace(/^\d+\s+/, '')).filter(Boolean).join(' / ');
}

/**
 * Note for flagged points that have no flux at all, so they cannot be plotted: how many, and why
 * if the manifest says (per point, or in the pipeline's warning). Null when there are none.
 */
export function missingNote(spec, warnings = []) {
  const miss = spec?.missing || [];
  if (!miss.length) return null;
  const why = missingReasons(miss, warnings);
  return `${miss.length} point${miss.length === 1 ? '' : 's'} left out of this spectrum: no usable flux${why ? ` (${why})` : ''}. Small ticks on the wavelength axis mark where.`;
}
