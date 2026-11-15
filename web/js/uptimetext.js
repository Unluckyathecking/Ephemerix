// The status page's history: decode the saved checks from /api/archives, group them into day and
// hour blocks, and say what they show. Pure: no DOM, no fetch. Days are UTC days (as saved);
// times are shown in the viewer's time zone (or `timeZone`, for tests).

const STATE = { u: 'answering', s: 'slow', d: 'not answering' };
const DAY_MS = 86400000;
const HOUR_MS = 3600000;
const n = (v) => (Number.isInteger(v) && v >= 0 ? v : 0);
const fmt = (x) => x.toLocaleString('en-GB');

/** {id: [{t (ms), code, ms, detail}]} from the compact `checks`, unchecked times dropped. */
export function decodeChecks(checks) {
  const times = Array.isArray(checks?.times) ? checks.times : [];
  const out = {};
  for (const [id, a] of Object.entries(checks?.archives || {})) {
    const codes = typeof a?.codes === 'string' ? a.codes : '';
    out[id] = times.map((t, i) => ({ t: t * 1000, code: codes[i], ms: Number.isFinite(a.ms?.[i]) ? a.ms[i] : null, detail: a.fail?.[i] || '' }))
      .filter((c) => Number.isFinite(c.t) && STATE[c.code]);
  }
  return out;
}

/** 'none' (no checks), 'up' (all answered), 'mixed' (some failed or slow), 'down' (none answered). */
export function level(checks, answered, slow) {
  if (!checks) return 'none';
  if (!answered) return 'down';
  return answered >= checks && !slow ? 'up' : 'mixed';
}

/** "286 of 288 checks answered, 2 slow" or "no checks". */
function counts(checks, answered, slow) {
  if (!checks) return 'no checks';
  return `${Math.min(answered, checks)} of ${checks} ${checks === 1 ? 'check' : 'checks'} answered${slow ? `, ${slow} slow` : ''}`;
}

export function dayLabel(iso) {
  const d = new Date(`${iso}T00:00:00Z`);
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', timeZone: 'UTC' });
}

export function timeLabel(ms, { timeZone } = {}) {
  return new Date(ms).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone });
}

/** The last `count` UTC days ending with `lastIso`, oldest first, as {date, checks, answered, slow, level, label}. */
export function dayBlocks(days, id, lastIso, count = 30) {
  const end = Date.parse(`${lastIso}T00:00:00Z`);
  if (!Number.isFinite(end)) return [];
  const held = new Map((days?.dates || []).map((d, i) => [d, days.archives?.[id]?.[i]]));
  return Array.from({ length: count }, (_, i) => {
    const date = new Date(end - (count - 1 - i) * DAY_MS).toISOString().slice(0, 10);
    const [c, a, s] = (held.get(date) || [0, 0, 0]).map(n);
    return { date, checks: c, answered: a, slow: s, level: level(c, a, s), label: `${dayLabel(date)}: ${counts(c, a, s)}` };
  });
}

/** The 24 hours of UTC day `dateIso` from one archive's checks: {start, checks: [...], level, label}. */
export function hourBlocks(list, dateIso, opts = {}) {
  const start = Date.parse(`${dateIso}T00:00:00Z`);
  if (!Number.isFinite(start)) return [];
  return Array.from({ length: 24 }, (_, i) => {
    const from = start + i * HOUR_MS;
    const checks = (list || []).filter((c) => c.t >= from && c.t < from + HOUR_MS);
    const a = checks.filter((c) => c.code !== 'd').length;
    const s = checks.filter((c) => c.code === 's').length;
    return { start: from, checks, level: level(checks.length, a, s),
      label: `${timeLabel(from, opts)} to ${timeLabel(from + HOUR_MS, opts)}: ${counts(checks.length, a, s)}` };
  });
}

/** One check in words: {time, state, response, detail}. */
export function checkWords(c, opts = {}) {
  return { time: timeLabel(c.t, opts), state: STATE[c.code] || '',
    response: c.ms == null ? '' : `${(c.ms / 1000).toFixed(1)} s`, detail: c.detail || '' };
}

/** "answered 8,412 of 8,640 checks, 97%" over day sums; null without checks. Never rounds up to 100%. */
export function shareLine(blocks, { percent = true } = {}) {
  const c = blocks.reduce((x, b) => x + b.checks, 0);
  const a = blocks.reduce((x, b) => x + Math.min(b.answered, b.checks), 0);
  if (!c) return null;
  return `answered ${fmt(a)} of ${fmt(c)} ${c === 1 ? 'check' : 'checks'}${percent ? `, ${Math.floor((a / c) * 100)}%` : ''}`;
}

export const MIN_FOR_PERCENT = 50;

/**
 * The record's sentence over the day blocks (oldest first), honest about its length. Thirty full days:
 * "Last 30 days: answered N of M checks, P%". Fewer: "Since checks began at 18:47 on 15 Nov: answered
 * N of M checks." (no percentage under 50 checks). `firstMs` is the earliest detailed check; it is used
 * only when it falls on the earliest day held, else only the day is known: "Since 15 Nov". Null without checks.
 */
export function recordLine(blocks, firstMs = null, opts = {}) {
  const first = blocks.find((x) => x.checks > 0);
  if (!first) return null;
  if (first === blocks[0]) return `Last 30 days: ${shareLine(blocks)}`;
  const total = blocks.reduce((x, c) => x + c.checks, 0);
  const exact = Number.isFinite(firstMs) && new Date(firstMs).toISOString().slice(0, 10) === first.date;
  const date = new Date(firstMs).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', timeZone: opts.timeZone });
  const since = exact ? `Since checks began at ${timeLabel(firstMs, opts)} on ${date}` : `Since ${dayLabel(first.date)}`;
  return `${since}: ${shareLine(blocks, { percent: total >= MIN_FOR_PERCENT })}`;
}

/** The longest run of checks in a row not answering: {from, to, count} (times in ms), or null. */
export function longestGap(list) {
  let best = null;
  let run = null;
  for (const c of list || []) {
    if (c.code === 'd') {
      run = run ? { ...run, to: c.t, count: run.count + 1 } : { from: c.t, to: c.t, count: 1 };
      if (!best || run.count > best.count) best = run;
    } else run = null;
  }
  return best;
}

/** "longest gap: 17:35 to 18:20 on 15 Nov (10 checks)" or null. */
export function gapLine(gap, opts = {}) {
  if (!gap) return null;
  const day = new Date(gap.to).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', timeZone: opts.timeZone });
  const span = gap.count === 1 ? `one check at ${timeLabel(gap.from, opts)}` : `${timeLabel(gap.from, opts)} to ${timeLabel(gap.to, opts)}`;
  return `longest gap: ${span} on ${day}${gap.count > 1 ? ` (${gap.count} checks)` : ''}`;
}
