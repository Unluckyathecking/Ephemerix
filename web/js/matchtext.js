// Words for the template match. `confidence` is about the class call (brown dwarf or not),
// never the subtype; the subtype uncertainty is `type_range`. Every newer field is optional. Pure.

import { isStarType } from './manifest.js';

export const CONFIDENCE_WORDS = {
  high: 'The spectrum is clearly unlike an ordinary star.',
  medium: 'This classification is tentative. Either no template fits closely or another kind of object fits almost as well.',
  low: 'The spectrum gives only a weak indication of the object’s class.',
};

/** "Neutral" classes are a statement about the source, not a warning, so the page does not colour them by confidence. */
export function neutralClass(match) {
  return match?.class === 'not a brown dwarf' || match?.class === 'uncertain';
}

/** True when the matcher says this is not a brown dwarf. */
export function notBrownDwarf(match) {
  if (!match) return false;
  if (match.class === 'star' || match.class === 'not a brown dwarf') return true;
  return !match.class && isStarType(match.best?.type);
}

/** "about T8", "T7 to T9", "Y1 or colder", "M8 or warmer to L2"; null without a range. */
export function typeRangeText(match) {
  const r = match?.type_range;
  if (!r) return null;
  const [warm, cold] = r;
  const w = match.range_open_warm ? `${warm} or warmer` : warm;
  const c = match.range_open_cold ? `${cold} or colder` : cold;
  if (warm === cold) {
    if (match.range_open_warm && match.range_open_cold) return `${warm}, open at both ends`;
    if (match.range_open_warm || match.range_open_cold) return match.range_open_cold ? c : w;
    return `about ${warm}`;
  }
  return `${w} to ${c}`;
}

/** A sentence about the class, or null when the manifest gives none. */
export function classText(match) {
  switch (match?.class) {
    case 'brown dwarf': return 'Class: brown dwarf.';
    case 'star': return 'Class: a star, not a brown dwarf.';
    case 'not a brown dwarf': return 'Class: not a brown dwarf.';
    case 'uncertain': return 'Class: uncertain. The spectrum does not clearly match a brown dwarf or a plain star.';
    default: return null;
  }
}

/**
 * The blended-pair line, or null. Null as well when the verdict sentence already names both
 * types, so the pair is stated once.
 */
export function pairText(match) {
  const p = match?.pair;
  if (!p || !Array.isArray(p.types) || p.types.length !== 2) return null;
  const verdict = typeof match.verdict === 'string' ? match.verdict : '';
  if (p.types.every((t) => verdict.includes(t))) return null;
  return `Fits better as two blended brown dwarfs, about ${p.types[0]} and ${p.types[1]}.`;
}

/** What one pass calls the source: the type for a brown dwarf, otherwise the class. */
function passToken(p) {
  if (p.class && p.class !== 'brown dwarf') return p.class;
  return p.type || p.class || 'no call';
}

/**
 * The pipeline's own sentence when the manifest has `pass_agreement`; otherwise "All 4 passes agree: T8"
 * or "Passes disagree: T8, T8, T7, uncertain" from the per-pass calls; null with fewer than two passes.
 */
export function passSummary(match) {
  const said = match?.pass_agreement?.sentence;
  if (typeof said === 'string' && said.trim()) return said;
  const passes = match?.per_pass;
  if (!Array.isArray(passes) || passes.length < 2) return null;
  const tokens = passes.map(passToken);
  return tokens.every((t) => t === tokens[0])
    ? `All ${tokens.length} passes agree: ${tokens[0]}`
    : `Passes disagree: ${tokens.join(', ')}`;
}

/** Raw numbers of the match, as [label, value] rows for the details disclosure. */
export function matchDetails(match) {
  if (!match) return [];
  const fit = (f) => (f ? `${f.type}${f.chi2 != null ? ` (χ² ${f.chi2}${f.dof ? ` / ${f.dof} dof` : ''})` : ''}` : null);
  const p = match.pair;
  const rows = [
    ['Best template', fit(match.best)],
    ['Runner-up', fit(match.runner_up)],
    ['Score gap', match.delta_chi2 != null ? `${match.delta_chi2} (runner-up score minus best score; a score is χ² adjusted for how many parameters the model has)` : null],
    ['Class gap', match.delta_class != null ? `${match.delta_class} (score of the best model on the losing side minus the winning side's)` : null],
    ['Molecular bands seen', match.bands_detected?.length ? match.bands_detected.join(', ') : null],
    ['Blended pair', p ? `${p.types.join(' + ')}${p.chi2 != null ? `, χ² ${p.chi2}` : ''}${p.delta_vs_single != null ? `; ${p.delta_vs_single} better than one template (rescaled χ²)` : ''}` : null],
  ];
  return rows.filter(([, v]) => v != null);
}

/** True when the fit prefers two blended brown dwarfs, so a single-type range would contradict it. */
export function hasPair(match) {
  return Array.isArray(match?.pair?.types) && match.pair.types.length === 2;
}

/** A subtype is worth stating only when the class call is "brown dwarf" (or not given). */
export function showsType(match) {
  return !!match && !notBrownDwarf(match) && match.class !== 'uncertain';
}

/** The subtype sentence for the verdict block, or null. */
export function rangeSentence(match) {
  if (!showsType(match) || hasPair(match)) return null;
  const r = typeRangeText(match);
  return r ? `Likely type: ${r}. This range is an estimate. A dedicated spectrograph can measure the type more precisely.` : null;
}

/**
 * The template curves to draw: best, runner-up, and the blended pair's summed curve when the
 * manifest names one (`pair.model`) and has it in `models`. The pair is the emphasised line
 * because the verdict names it. Pure; curves missing from `models` are left out.
 * @returns {{key: string, role: string, label: string, color: string, dash: string, width: number, curve: number[][]}[]}
 */
export function templateCurves(match) {
  if (!match) return [];
  const models = match.models || {};
  const pairKey = match.pair?.model;
  const hasPair = !!(pairKey && models[pairKey]);
  const out = [];
  for (const [fit, role, color, dash] of [[match.best, 'best', '#ffb547', 'solid'], [match.runner_up, 'runner-up', '#c8a2ff', 'dash']]) {
    const curve = fit && models[fit.type];
    if (curve) out.push({ key: fit.type, role, label: `${fit.type} template, ${role}`, color, dash, width: role === 'best' && !hasPair ? 3 : 2, curve });
  }
  if (hasPair) out.push({ key: pairKey, role: 'pair', label: `${pairKey} blend`, color: '#7be0a4', dash: 'dot', width: 3.5, curve: models[pairKey] });
  return out;
}
