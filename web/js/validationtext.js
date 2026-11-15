// Words and numbers for the validation page. Pure: no DOM, so node can test it.

import { emptyState, serializeState } from './urlstate.js';

export const VERDICT_LABELS = {
  pass: 'Pass',
  fail: 'Differs',
  refused: 'Unclassified',
  not_applicable: 'Not applicable',
};

const isNum = (x) => typeof x === 'number' && Number.isFinite(x);

export function verdictLabel(v) {
  return VERDICT_LABELS[v] || 'Unknown';
}

/** A motion pass the report marks a weak test (catalogue motion below 3 times our error). */
export const isWeakPass = (m) => m?.verdict === 'pass' && m?.weak_test === true;

/** The label of a motion result: "Consistent (weak)" for a weak pass (the note under the scoreboard explains it), else verdictLabel. */
export function motionLabel(m) {
  return isWeakPass(m) ? 'Consistent (weak)' : verdictLabel(m?.verdict);
}

/** The line under the scoreboard on weak passes, counted from the rows; '' when there are none. */
export function weakTestNote(targets) {
  const k = (targets || []).filter((t) => isWeakPass(t.motion)).length;
  if (!k) return '';
  return k === 1
    ? 'For 1 slow star agreement only shows we measure no false motion.'
    : `For ${k} slow stars agreement only shows we measure no false motion.`;
}

/** Fixed decimals, or an em dash when the value is missing. */
export function fmt(x, digits = 1) {
  return isNum(x) ? x.toFixed(digits) : '—';
}

/** Like fmt, with an explicit sign (a true minus sign, not a hyphen). */
export function fmtSigned(x, digits = 1) {
  if (!isNum(x)) return '—';
  const s = Math.abs(x).toFixed(digits);
  if (Number(s) === 0) return s;
  return `${x < 0 ? '−' : '+'}${s}`;
}

/** Percentage difference, e.g. "+0.65%". */
export function fmtPct(x) {
  return isNum(x) ? `${fmtSigned(x, 2)}%` : '—';
}

/** Largest component difference in sigma, e.g. "7.3 σ". */
export function fmtSigma(x) {
  return isNum(x) ? `${x.toFixed(1)} σ` : '—';
}

/** Link to a target's view, built with the site's own query-string serializer. */
export function viewHref(slug) {
  if (typeof slug !== 'string') return './';
  return `./${serializeState({ ...emptyState(), target: slug })}`;
}

/** "14 Nov 2026, 18:24 UTC" from an ISO time, or null. */
export function builtText(iso) {
  const d = new Date(iso);
  if (typeof iso !== 'string' || Number.isNaN(d.getTime())) return null;
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const hh = String(d.getUTCHours()).padStart(2, '0');
  const mm = String(d.getUTCMinutes()).padStart(2, '0');
  return `${d.getUTCDate()} ${months[d.getUTCMonth()]} ${d.getUTCFullYear()}, ${hh}:${mm} UTC`;
}

/** The three summary figures. Refusals are counted on their own, not as passes or fails. */
export function summaryCells(summary) {
  const s = summary || {};
  const m = s.motion || {};
  const t = s.type || {};
  return [
    { key: 'motion', value: `${m.passed ?? 0} of ${m.total ?? 0}`, label: 'motion checks passed' },
    { key: 'type', value: `${t.passed ?? 0} of ${t.total ?? 0}`, label: 'type checks passed' },
    { key: 'refused', value: String(t.refused ?? 0), label: t.refused === 1 ? 'target unclassified' : 'targets unclassified' },
  ];
}

/** Residual as "2.2″ (0.36 SPHEREx pixel) in spx-b2-2026a", or the reason there is none. */
export function residualText(r) {
  if (!r || !isNum(r.max_px)) return 'no frame with a detection';
  const native = isNum(r.max_native_px) ? ` (${r.max_native_px.toFixed(2)} ${r.mission || ''} pixel)` : '';
  return `${r.max_arcsec.toFixed(1)}″${native} in ${r.frame_id}`;
}

/** "46 frames, 23 epochs" for one mission block. */
export function framesText(block) {
  if (!block) return '—';
  const f = block.frames ?? 0;
  const e = block.epochs ?? 0;
  return `${f} frame${f === 1 ? '' : 's'}, ${e} epoch${e === 1 ? '' : 's'}`;
}

/** "2010 to 2024", "2010 only", or an em dash. */
export function yearSpan(block) {
  if (!block || !isNum(block.first_year)) return '—';
  return block.first_year === block.last_year ? `${block.first_year} only` : `${block.first_year} to ${block.last_year}`;
}

/** The tool's type range as text, honouring open ends. */
export function rangeText(type) {
  const r = type?.range;
  if (!Array.isArray(r) || r.length !== 2) return '—';
  const w = type.range_open_warm ? `${r[0]} or warmer` : r[0];
  const c = type.range_open_cold ? `${r[1]} or colder` : r[1];
  return r[0] === r[1] && !type.range_open_warm && !type.range_open_cold ? r[0] : `${w} to ${c}`;
}

/**
 * The chip beside a provisional type, or null. A neighbour's light gives "Provisional"; a type
 * given to a faint object from a fit to all its points says so, and says when its range has an
 * open end.
 * @param {{provisional?: string|null, provisional_kind?: string|null, range_open_warm?: boolean, range_open_cold?: boolean}|null|undefined} type
 * @returns {string|null}
 */
export function provisionalLabel(type) {
  if (!type?.provisional) return null;
  if (type.provisional_kind !== 'faint') return 'Provisional';
  return type.range_open_warm || type.range_open_cold ? 'Provisional: faint, open-ended range' : 'Provisional: faint';
}

/**
 * The sentences on types given to faint objects, which the report counts apart from the other
 * types (summary.type.faint); '' when there are none.
 * @param {{faint?: {passed?: number, failed?: number, open_ended?: number}}|null|undefined} typeSummary
 * @returns {string}
 */
export function faintTypesText(typeSummary) {
  const f = typeSummary?.faint || {};
  const passed = f.passed ?? 0;
  const n = passed + (f.failed ?? 0);
  const open = f.open_ended ?? 0;
  if (!n) return '';
  const scored = typeSummary?.total ?? 0;
  const prov = typeSummary?.provisional ? `, ${typeSummary.provisional} of them provisional` : '';
  const all = `In all we gave ${scored + n} types: the ${scored} scored above (${typeSummary?.passed ?? 0} contain the published type${prov}) and ${n === 1 ? 'one' : n} more. `;
  if (n === 1) {
    return `${all}That one was given to an object too faint to detect at many wavelengths one by one, from a fit to all of its points together. It ${passed ? 'contains' : 'does not contain'} the published type${open ? ', with a range that is open at one end' : ''}. It is provisional and is counted apart from the types above.`;
  }
  return `${all}Those were given to objects too faint to detect at many wavelengths one by one, from a fit to all of their points together. ${passed} of them contain the published type${open ? ` (${open} with a range that is open at one end)` : ''}. They are provisional and are counted apart from the types above.`;
}

/** Rejects a report the page cannot draw; returns null when usable, else a message. */
export function reportProblem(body) {
  if (!body || typeof body !== 'object') return 'The validation data is not an object.';
  if (body.schema !== 1) return 'The validation data has an unknown version.';
  if (!Array.isArray(body.targets) || !body.summary) return 'The validation data is incomplete.';
  return null;
}

const GROUPS = [
  ['brief', 'Brief targets'],
  ['backyard-worlds', 'Backyard Worlds discoveries'],
  ['benchmark', 'Benchmark brown dwarfs'],
];

/** Rows split by gallery group in a fixed order; unknown or missing groups go last as "other". */
export function groupRows(rows) {
  const known = new Set(GROUPS.map(([k]) => k));
  const sets = [...GROUPS, ['other', 'Other targets']].map(([key, label]) => ({
    key, label,
    rows: rows.filter((r) => (key === 'other' ? !known.has(r.group) : r.group === key)),
  }));
  return sets.filter((g) => g.rows.length);
}

const pair = (a, b, digits, f = fmt) => (isNum(a) && isNum(b) ? `${f(a, digits)}, ${f(b, digits)}` : '—');

/** Every cell of a motion row as text; a missing value is a dash, never "undefined" or "NaN". */
export function motionText(m) {
  const cat = m?.catalogue || {};
  const meas = m?.measured || {};
  const diff = m?.diff || {};
  const err = m?.err_masyr || {};
  const total = isNum(meas.total_arcsec_yr) && isNum(cat.total_arcsec_yr)
    ? `${fmt(meas.total_arcsec_yr, 3)} / ${fmt(cat.total_arcsec_yr, 3)}` : '—';
  return {
    catalogue: pair(cat.pmra, cat.pmdec, 1),
    measured: pair(meas.pmra, meas.pmdec, 1),
    diff: pair(diff.pmra, diff.pmdec, 1, fmtSigned),
    total,
    totalDiff: fmtPct(diff.total_pct),
    error: err.pmra === err.pmdec ? fmt(err.pmra, 2) : pair(err.pmra, err.pmdec, 2),
    sigma: fmtSigma(m?.sigma?.max),
    baseline: isNum(m?.baseline_years) ? `${fmt(m.baseline_years, 1)} yr` : '—',
    // A motion fitted on all images at once has no detections to count (pxs.trackmotion).
    detections: m?.method === 'all_frames'
      ? `${isNum(m.n_frames) ? m.n_frames : 'all'} images at once`
      : String(m?.n_detections ?? 0),
  };
}

/** "10 passed, 3 failed, 4 not applicable"; zero refusals are left out. */
export function countsText(c) {
  const parts = [`${c.passed ?? 0} passed`, `${c.failed ?? 0} failed`];
  if (c.refused) parts.push(`${c.refused} unclassified`);
  parts.push(`${c.not_applicable ?? 0} not applicable`);
  return parts.join(', ');
}
