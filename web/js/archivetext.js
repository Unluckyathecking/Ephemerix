// Words for the archive uptime indicator, from /api/archives. Pure: no DOM, no fetch.
// Only what was measured is said: an archive is named as not answering only when our own
// check of it failed, and a mirror (Data Lab) that answers means its catalogues are not missing.

const PHRASE = { up: 'answering', slow: 'slow', down: 'not answering' };
// While the Data Lab mirror answers, what each mirrored archive's failure still loses (null: nothing).
const MIRRORED = { gaia: null, irsa_tap: 'some 2010 WISE images' };
const ON_THEIR_SIDE = 'This is on their side; try again in a few minutes.';

const str = (v) => (typeof v === 'string' ? v : '');
const count = (v) => (Number.isInteger(v) && v >= 0 ? v : 0);

/** The response, checked and tidied; null when it is not an archive status at all. */
export function cleanStatus(raw) {
  if (!raw || typeof raw !== 'object' || !Array.isArray(raw.archives)) return null;
  const archives = raw.archives
    .filter((a) => a && str(a.id) && str(a.name) && PHRASE[a.status])
    .map((a) => ({ id: a.id, name: a.name, usedFor: str(a.used_for), backup: a.backup === true,
      status: a.status, latencyMs: Number.isFinite(a.latency_ms) ? a.latency_ms : null, detail: str(a.detail) }));
  const obj = (v) => (v && typeof v === 'object' ? v : {});
  if (!archives.length) return raw.checked_at === null ? { checkedAt: '', archives: [], history: {}, checks: {}, days: {} } : null;
  return { checkedAt: str(raw.checked_at), archives, history: obj(raw.history), checks: obj(raw.checks), days: obj(raw.days) };
}

export const STALE_MS = 30 * 60 * 1000;
// How the checks are made: mirrors src/pxs/api/archivestatus.py (SLOW_S, TIMEOUT_S) and the
// 5-minute schedule in deploy/modal_app.py.
export const CHECK = { everyMin: 5, slowS: 5, connectS: 5, answerS: 10 };

/** The status page's opening sentence for this answer at `nowMs` (null: nothing could be read). */
export function statusLead(data, nowMs, opts = {}) {
  if (!data) return 'The archive checks could not be loaded just now.';
  if (!data.checkedAt) return 'No archive checks are available yet.';
  if (isStale(data.checkedAt, nowMs)) {
    return `Our archive checks last ran at ${formatWhen(data.checkedAt, opts)}, more than 30 minutes ago, so we cannot say how the archives are doing now.`;
  }
  const trouble = troubleSentence(data);
  return trouble ? `${trouble} Checked at ${formatTime(data.checkedAt, opts)}.`
    : `Every archive we use answered our last check, at ${formatTime(data.checkedAt, opts)}.`;
}

/** True when the newest saved check is missing or older than 30 minutes: status unknown. */
export function isStale(checkedAt, nowMs) {
  const t = Date.parse(checkedAt);
  return !Number.isFinite(t) || nowMs - t > STALE_MS;
}

/** "18:10" in the viewer's time zone (or `timeZone`); '' for a bad time. */
export function formatTime(iso, { timeZone } = {}) {
  const d = new Date(iso);
  if (!str(iso) || Number.isNaN(d.getTime())) return '';
  return d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone });
}

/** "answering", "slow" or "not answering". */
export const phrase = (status) => PHRASE[status] || '';

/** "A", "A and B", "A, B and C". */
export function joinWords(list) {
  return list.length > 1 ? `${list.slice(0, -1).join(', ')} and ${list[list.length - 1]}` : list[0] || '';
}

/** What a failing archive costs a view, given the others; null when a mirror covers it. */
function loss(a, data) {
  if (a.backup) return null;
  const mirrorUp = data.archives.some((m) => m.id === 'datalab' && m.status !== 'down');
  if (mirrorUp && a.id in MIRRORED) return MIRRORED[a.id];
  return a.usedFor || null;
}

function sentence(list, verb, data, tail) {
  const losses = [...new Set(list.map((a) => loss(a, data)))];
  const names = joinWords(list.map((a) => a.name));
  const be = list.length > 1 ? 'are' : 'is';
  return `${names} ${be} ${verb}, so ${joinWords(losses)} ${tail} ${ON_THEIR_SIDE}`;
}

// Archives only some lookups use: JPL for Solar System bodies, Sesame for lookups by name.
const ONLY_FOR = { horizons: 'body', sbdb: 'body', sesame: 'name' };

/** What a lookup at this query string uses: {body, name}. Null (no lookup) means every archive. */
export function lookupUses(search) {
  const q = new URLSearchParams(search || '');
  return { body: q.has('body'), name: q.has('label') || q.has('name') };
}

/**
 * One plain sentence when something we depend on is failing now, else null.
 * recent: also speak of archives that answer now but failed one of our checks in the last hour.
 * uses: the lookup's {body, name}, so archives it does not use are left out; null keeps all.
 */
export function troubleSentence(data, { recent = false, uses = null } = {}) {
  if (!data) return null;
  const used = (a) => !uses || !ONLY_FOR[a.id] || uses[ONLY_FOR[a.id]];
  const hurts = (a) => used(a) && loss(a, data) !== null;
  const down = data.archives.filter((a) => a.status === 'down' && hurts(a));
  if (down.length) return sentence(down, 'not answering right now', data, 'may be missing.');
  const slow = data.archives.filter((a) => a.status === 'slow' && hurts(a));
  if (slow.length) return sentence(slow, 'slow to answer right now', data, 'may take longer to arrive.');
  if (!recent) return null;
  const flaky = data.archives.filter((a) => count(data.history[a.id]?.failed_last_hour) > 0 && hurts(a));
  if (flaky.length) return sentence(flaky, 'answering now but missed some of our checks in the last hour', data, 'may have been missing.');
  return null;
}

/** "18:10 on 15 Nov" in the viewer's time zone (or `timeZone`); '' for a bad time. */
export function formatWhen(iso, { timeZone } = {}) {
  const d = new Date(iso);
  if (!str(iso) || Number.isNaN(d.getTime())) return '';
  const time = d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone });
  const day = d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', timeZone });
  return `${time} on ${day}`;
}

/** "answered 41 of the last 52 checks since 18:10 on 15 Nov"; null with no history. */
export function historyLine(h, opts = {}) {
  const checks = count(h?.checks);
  if (!checks) return null;
  const answered = Math.min(count(h.answered), checks);
  const since = formatWhen(h.since, opts);
  const last = checks === 1 ? 'the one check' : `the last ${checks} checks`;
  return `answered ${answered} of ${last}${since ? ` since ${since}` : ''}`;
}

/** "0.4 s", or the failure as measured ("HTTP 502"). */
export function measuredText(a) {
  if (a.status === 'down') return a.detail || 'no answer';
  return a.latencyMs == null ? '' : `${(a.latencyMs / 1000).toFixed(1)} s`;
}

const SHORT = { irsa_sia: 'IRSA images', irsa_tap: 'IRSA tables', wise_s3: 'WISE files', spherex_s3: 'SPHEREx files',
  gaia: 'Gaia', datalab: 'Data Lab', sesame: 'Sesame', horizons: 'Horizons', sbdb: 'SBDB' };
const WORD = { up: '', slow: 'slow', down: 'down' };

/** The compact row's items: {id, short, status, word}. The backup mirror only when it is failing. */
export function stripItems(data) {
  return data.archives.filter((a) => !a.backup || a.status !== 'up')
    .map((a) => ({ id: a.id, short: SHORT[a.id] || a.name, status: a.status, word: WORD[a.status] }));
}

/** "7 of 8 answering" over the row's items (slow ones answer). */
export function countLine(items) {
  return `${items.filter((i) => i.status !== 'down').length} of ${items.length} answering`;
}
