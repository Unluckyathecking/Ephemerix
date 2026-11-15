// The validation report (data/validation.json) in the words the landing page uses: the
// scoreboard strip and the pass / refused / differs marks on each gallery row. Pure.
// Counts are always read from the report; nothing here is typed in.

const n = (x) => (Number.isFinite(x) ? x : 0);

/**
 * The three figures of the strip, each with its failures beside it.
 * @param {object} summary `summary` of the validation report
 * @returns {{key: string, label: string, value: string, of: string, sub: string, fail: string|null, calm?: string|null}[]}
 *   `fail` is the count that differ; `calm` a count that stands but is marked provisional
 */
export function scoreTiles(summary) {
  const m = summary?.motion || {}, t = summary?.type || {};
  const differ = (k) => (n(k.failed) ? `${n(k.failed)} ${n(k.failed) === 1 ? 'differs' : 'differ'}` : null);
  return [
    { key: 'motion', label: 'Motion', value: String(n(m.passed)), of: `of ${n(m.total)}`, sub: 'agree with the catalogue', fail: differ(m) },
    { key: 'type', label: 'Spectral type', value: String(n(t.passed)), of: `of ${n(t.total)}`, sub: 'contain the published type', fail: differ(t),
      calm: n(t.provisional) ? `${n(t.provisional)} provisional` : null },
    { key: 'refused', label: 'Unclassified', value: String(n(t.refused)), of: '', sub: 'targets without a reliable classification', fail: null },
  ];
}

/**
 * The home page's one-line proof: "Checked on 17 objects with published values: 14 of 16 motions
 * agree, 2 do not." Null when the report lacks the counts.
 * @param {object} summary `summary` of the validation report
 */
export function proofLine(summary) {
  const m = summary?.motion;
  if (!Number.isFinite(summary?.targets) || !Number.isFinite(m?.total) || !m.total || !Number.isFinite(m.passed)) return null;
  const fail = n(m.failed);
  const tail = fail ? `, ${fail} ${fail === 1 ? 'does' : 'do'} not` : '';
  return `Checked on ${summary.targets} objects with published values: ${m.passed} of ${m.total} motions agree${tail}.`;
}

/** Targets whose motion could not be checked because the object was not detected. */
export function notDetected(targets) {
  return (targets || []).filter((t) => t.motion?.verdict === 'not_applicable' && /not detected/i.test(t.motion?.reason || ''));
}

const MOTION = {
  pass: { tone: 'pass', text: 'Motion agrees' },
  fail: { tone: 'fail', text: 'Motion differs' },
  refused: { tone: 'refused', text: 'Motion unavailable' },
};
const TYPE = {
  pass: { tone: 'pass', text: 'Type agrees' },
  fail: { tone: 'fail', text: 'Type differs' },
  refused: { tone: 'refused', text: 'Unclassified' },
  not_applicable: { tone: 'not_applicable', text: 'No type check' },
};

/**
 * The marks on a gallery row: how the tool's motion and type compare with the published ones.
 * @param {object|null} v this target's entry in the validation report
 * @returns {{tone: 'pass'|'fail'|'refused'|'not_applicable'|'provisional', text: string}[]} [] when there is no entry
 */
export function cardMarks(v) {
  if (!v) return [];
  // A pass on a star too slow for the test to fail says only that we measured no false motion.
  const weak = v.motion?.verdict === 'pass' && v.motion?.weak_test === true;
  const motion = (weak ? { tone: 'pass', text: 'Motion consistent (weak test)' } : MOTION[v.motion?.verdict])
    || { tone: 'not_applicable', text: /not detected/i.test(v.motion?.reason || '') ? 'Not detected' : 'No motion check' };
  const type = TYPE[v.type?.verdict];
  // A type the pipeline marks provisional keeps its verdict and gains a calm second mark.
  const prov = v.type?.provisional ? { tone: 'provisional', text: 'Provisional' } : null;
  return [motion, type, prov].filter(Boolean);
}

/** Look a target up in the report by slug; null when the report or the entry is missing. */
export function validationFor(report, slug) {
  return report?.targets?.find((t) => t.slug === slug) || null;
}
