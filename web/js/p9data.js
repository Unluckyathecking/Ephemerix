// Words and numbers for "A pilot search where Planet Nine is predicted", from
// data/p9-search.json (tools/p9_search/report.py). Pure: no DOM.
// The limits shown are the ones counted above each field's mirrored-null maximum, the bar a
// real peak had to clear to be examined; the plain S/N >= 7 sensitivity is never shown as a limit.

const isNum = (x) => typeof x === 'number' && Number.isFinite(x);
const obj = (x) => x && typeof x === 'object' && !Array.isArray(x);

/** A reason the file cannot be drawn, or null when it has what the section needs. */
export function p9Problem(d) {
  if (!obj(d) || d.schema !== 1) return 'unknown version';
  if (typeof d.statement !== 'string' || !obj(d.pooled) || !Array.isArray(d.fields)) return 'incomplete';
  if (!isNum(d.pooled.flux50_ujy) || !isNum(d.pooled.flux90_ujy)) return 'no pooled limits';
  return null;
}

/** The report's ASCII set properly: deg², µJy, µm, ≈, ±, ≥, ′ and en dashes in ranges. Words are untouched. */
export function p9Pretty(text) {
  return String(text ?? '').replace(/deg\^2/g, 'deg²').replace(/\buJy\b/g, 'µJy').replace(/(\d) um\b/g, '$1 µm')
    .replace(/ ~ /g, ' ≈ ').replace(/ \+- /g, ' ± ').replace(/>=/g, '≥').replace(/(\d) arcmin\b/g, '$1′').replace(/(\d)-(\d)/g, '$1–$2');
}

/** The report's own statement of the result. */
export function p9Statement(d) {
  return p9Pretty(d.statement);
}

/**
 * The four figures at the head of the section.
 * @returns {{label: string, value: string, sub: string}[]}
 */
export function p9Stats(d) {
  const p = d.pooled;
  const with90 = d.fields.filter((f) => isNum(f.flux90_ujy)).length;
  const v = (x) => (isNum(x) ? `V ${x.toFixed(1)}` : 'V unknown');
  return [
    { label: 'Area searched', value: `${d.area_deg2.toFixed(1)} deg²`, sub: `${d.n_fields} fields of ${Math.round(d.tile_arcmin)}′, one pass each` },
    { label: '50% limit, pooled', value: `${Math.round(p.flux50_ujy)} µJy`, sub: `${v(p.vmag50)} for a sunlit body` },
    { label: '90% limit, pooled', value: `${Math.round(p.flux90_ujy)} µJy`, sub: `${v(p.vmag90)} for a sunlit body` },
    { label: 'Fields reaching 90%', value: `${with90} of ${d.fields.length}`, sub: 'the rest have too many star residuals' },
  ];
}

const au = (x) => (isNum(x) ? String(Math.round(x)) : null);

/** "225 / 325 / 450 au", with "< 200" where the dark end falls short of the table's nearest distance. */
function reachCell(r) {
  const lo = au(r.reach_lo_au) ?? '< 200';
  const nom = au(r.reach_nom_au), hi = au(r.reach_hi_au);
  return nom && hi ? `${lo} / ${nom} / ${hi} au` : 'not reached';
}

/**
 * How far each Planet X case would be seen at the pooled limits (dark / most likely / bright).
 * @returns {{label: string, at50: string, at90: string}[]}
 */
export function p9ReachRows(d) {
  const r90 = new Map((d.planetx_reach?.at_pooled_flux90 || []).map((r) => [r.key, r]));
  return (d.planetx_reach?.at_pooled_flux50 || []).map((r) => ({
    label: r.label, at50: reachCell(r), at90: r90.has(r.key) ? reachCell(r90.get(r.key)) : '—',
  }));
}

const SUPERSCRIPT = '⁰¹²³⁴⁵⁶⁷⁸⁹';

/** A fraction as a percentage to one figure ("0.08%"), or as "6 × 10⁻⁹" when it is too small for that. */
export function share(x) {
  if (!isNum(x) || x <= 0) return null;
  if (x * 100 >= 0.001) return `${Number((x * 100).toPrecision(1))}%`;
  const [mant, exp] = x.toExponential(0).split('e-');
  return `${mant} × 10⁻${[...exp].map((c) => SUPERSCRIPT[c]).join('')}`;
}

/** What the fields are worth against the prediction, in the report's own fractions. */
export function p9PopulationText(d) {
  const p = d.population || {};
  const held = share(p.fraction_of_population_in_fields), excl = share(p.expected_fraction_excluded);
  const fresh = share(p.expected_fraction_excluded_not_already_excluded_by_ztf_des_ps1);
  if (!held || !excl) return null;
  return `The fields hold an expected ${held} of the predicted sky positions and exclude an expected ${excl} of the predicted population${fresh ? `; of the part that ZTF, DES and Pan-STARRS1 had not already excluded, they exclude essentially none (${fresh})` : ''}.`;
}

/**
 * The peaks above their field's null maximum, sorted for the page: how many, how the report
 * judged them, and the one it could not explain (if any). The pipeline's internal label for a
 * peak is never shown; the judgement is the report's `assessment`.
 * @returns {{total: number, groups: {what: string, n: number}[], unexplained: object[]}}
 */
export function p9Peaks(d) {
  const peaks = Array.isArray(d.unexplained_or_vetted_peaks_above_null_max) ? d.unexplained_or_vetted_peaks_above_null_max : [];
  const kind = (v) => (/^unexplained/i.test(v) ? 'unexplained' : /^artefact:/i.test(v) ? 'artefacts' : /variable star/i.test(v) ? 'possible variable stars or noise' : 'artefacts or noise');
  const counts = new Map();
  const unexplained = [];
  for (const p of peaks) {
    const k = kind(p.assessment?.verdict || '');
    if (k === 'unexplained') unexplained.push(p);
    else counts.set(k, (counts.get(k) || 0) + 1);
  }
  return { total: peaks.length, groups: [...counts].map(([what, n]) => ({ what, n })), unexplained };
}

/** One sentence on the explained peaks: "17 are explained: 14 artefacts, 2 possible variable stars or noise, ...". */
export function p9PeaksText(d) {
  const { total, groups, unexplained } = p9Peaks(d);
  if (!total) return 'No peak rose above its field’s null maximum.';
  const explained = total - unexplained.length;
  const parts = groups.map((g) => `${g.n} ${g.what}`).join(', ');
  const fields = d.peaks?.fields_with_real_peak_above_null_max;
  const where = isNum(fields) ? ` in ${fields} of the ${d.n_fields} fields` : '';
  return `${total} peaks rose above their own field’s null maximum${where}. ${explained} of them are accounted for (${parts})${unexplained.length ? `, and ${unexplained.length} ${unexplained.length === 1 ? 'is' : 'are'} not` : ''}.`;
}

/** Where and how bright an unexplained peak is, before the report's own account of it. */
export function p9PeakHead(p) {
  const pos = isNum(p.ra) && isNum(p.dec) ? `RA ${p.ra.toFixed(4)}°, Dec ${p.dec < 0 ? '−' : '+'}${Math.abs(p.dec).toFixed(4)}°` : '';
  const flux = isNum(p.flux_ujy) ? `${Math.round(p.flux_ujy)}${isNum(p.flux_err_ujy) ? ` ± ${Math.round(p.flux_err_ujy)}` : ''} µJy` : '';
  return [`Field ${p.field}`, pos, isNum(p.snr) ? `S/N ${p.snr.toFixed(2)}` : '', flux].filter(Boolean).join(', ');
}
