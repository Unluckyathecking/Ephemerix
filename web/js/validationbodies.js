// Words and numbers for the "Known bodies recovered" section of the validation page, from
// data/body-recovery.json (tools/solarsystem_validation/analyse.py). Pure: no DOM, so node can test it.

const isNum = (x) => typeof x === 'number' && Number.isFinite(x);
const obj = (x) => x && typeof x === 'object' && !Array.isArray(x);
const pct = (x, d = 1) => `${(x * 100).toFixed(d)}%`;

/** A reason the file cannot be drawn, or null when it has what the section needs. */
export function bodyRecoveryProblem(d) {
  if (!obj(d)) return 'not an object';
  if (!Array.isArray(d.by_predicted_v)) return 'no recovery table';
  if (!obj(d.false_detections) || !obj(d.false_detections.passes)) return 'no control rates';
  return null;
}

const rate = (r) => (obj(r) && isNum(r.k) && isNum(r.n) && r.n > 0 ? r : null);

/**
 * One row per V bin with covered passes: current-rule recovery with its 95% interval, and the
 * count under the rule before Nov 2026 when the file has it.
 */
export function recoveryRows(d) {
  const before = new Map((d.before?.by_predicted_v || []).map((r) => [r.bin, r]));
  return d.by_predicted_v.filter((r) => rate(r)).map((r) => {
    const [lo, hi] = Array.isArray(r.ci95) ? r.ci95 : [null, null];
    const b = rate(before.get(r.bin));
    return { bin: r.bin, n: r.n, k: r.k, frac: r.k / r.n, lo: isNum(lo) ? lo : null, hi: isNum(hi) ? hi : null,
      before: b ? b.k : null };
  });
}

/** "4 of 551 (0.7%; 95% interval 0.2–1.9%)". */
export function rateText(r) {
  if (!rate(r)) return '—';
  const ci = Array.isArray(r.ci95) && isNum(r.ci95[0]) && isNum(r.ci95[1]) ? `; 95% interval ${(r.ci95[0] * 100).toFixed(1)}–${pct(r.ci95[1])}` : '';
  return `${r.k} of ${r.n} (${pct(r.k / r.n)}${ci})`;
}

/** The control false-detection rate before and after the rule change, in one sentence. */
export function controlText(d) {
  const now = rateText(d.false_detections.passes);
  const old = d.before?.false_detections?.passes;
  return old ? `On empty control tracks (the same frames with the position moved 3 arcmin), the old rule, one band at S/N 5, counted ${rateText(old)} passes as detections; the current rule, two bands at S/N 5, counts ${now}.`
    : `On empty control tracks the current rule counts ${now} passes as detections.`;
}

const vLo = (bin) => Number(String(bin).split('-')[0]);

/** The plain limit statement: bright passes all recovered, and the faintest reliable bin. */
export function limitText(d) {
  const rows = recoveryRows(d);
  let brightTo = null, nBright = 0;
  for (const r of rows) {
    if (r.k !== r.n) break;
    brightTo = r.bin.split('-')[1];
    nBright += r.n;
  }
  const parts = [];
  if (brightTo) parts.push(`Every covered pass brighter than V ${brightTo} was recovered (${nBright} of ${nBright}).`);
  const rel = d.faintest_reliable_bin;
  if (rel) parts.push(`The faintest V bin recovered reliably (95% lower bound at least one half) is V ${rel.replace('-', '–')}.`);
  const faint = rows.filter((r) => rel && vLo(r.bin) > vLo(rel));
  if (faint.length) parts.push(`Fainter than that, recovery falls to ${faint.map((r) => `${pct(r.frac, 0)} at V ${r.bin.replace('-', '–')}`).join(', ')}.`);
  return parts.join(' ');
}
