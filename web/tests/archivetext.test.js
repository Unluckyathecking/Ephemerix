import { test } from 'node:test';
import assert from 'node:assert/strict';
import { cleanStatus, troubleSentence, formatWhen, historyLine, measuredText, stripItems, countLine, joinWords, phrase, lookupUses, isStale, formatTime, statusLead } from '../js/archivetext.js';

const A = (id, name, usedFor, status, extra = {}) => ({ id, name, used_for: usedFor, status, latency_ms: status === 'down' ? null : 400, detail: status === 'down' ? 'HTTP 502' : null, backup: false, ...extra });
const raw = (over = {}, history = {}) => ({
  checked_at: '2026-11-15T18:10:00Z',
  archives: [
    A('irsa_sia', 'NASA IRSA image search', 'WISE and SPHEREx images', over.irsa_sia || 'up'),
    A('irsa_tap', 'NASA IRSA catalogue service', 'CatWISE sources and WISE frame checks', over.irsa_tap || 'up'),
    A('gaia', 'ESA Gaia archive', 'Gaia stars', over.gaia || 'up'),
    A('datalab', 'NOIRLab Astro Data Lab', 'backup copies of Gaia and CatWISE', over.datalab || 'up', { backup: true }),
  ],
  history,
});
const UTC = { timeZone: 'UTC' };
const TAIL = 'This is on their side; try again in a few minutes.';

test('rejects anything that is not an archive status', () => {
  assert.equal(cleanStatus(null), null);
  assert.equal(cleanStatus('<html>'), null);
  assert.equal(cleanStatus({ archives: [{ id: 'x', name: 'X', status: 'weird' }] }), null);
  const c = cleanStatus(raw());
  assert.equal(c.archives.length, 4);
  assert.deepEqual(c.history, {});
});

test('nothing to say when everything answers', () => {
  assert.equal(troubleSentence(cleanStatus(raw())), null);
  assert.equal(troubleSentence(null), null);
  assert.deepEqual(stripItems(cleanStatus(raw())).map((i) => i.short), ['IRSA images', 'IRSA tables', 'Gaia']);
});

test('one archive down: one plain sentence naming what may be missing', () => {
  assert.equal(troubleSentence(cleanStatus(raw({ irsa_sia: 'down' }))),
    `NASA IRSA image search is not answering right now, so WISE and SPHEREx images may be missing. ${TAIL}`);
});

test('a mirrored archive is not called missing while the mirror answers', () => {
  assert.equal(troubleSentence(cleanStatus(raw({ gaia: 'down' }))), null);
  assert.equal(troubleSentence(cleanStatus(raw({ irsa_tap: 'down' }))),
    `NASA IRSA catalogue service is not answering right now, so some 2010 WISE images may be missing. ${TAIL}`);
  assert.equal(troubleSentence(cleanStatus(raw({ gaia: 'down', datalab: 'down' }))),
    `ESA Gaia archive is not answering right now, so Gaia stars may be missing. ${TAIL}`);
});

test('the backup alone failing says nothing to a visitor', () => {
  const d = cleanStatus(raw({ datalab: 'down' }));
  assert.equal(troubleSentence(d), null);
  assert.deepEqual(stripItems(d).map((i) => [i.short, i.word]), [['IRSA images', ''], ['IRSA tables', ''], ['Gaia', ''], ['Data Lab', 'down']]);
});

test('two down are joined; slow has its own sentence', () => {
  assert.equal(troubleSentence(cleanStatus(raw({ irsa_sia: 'down', gaia: 'down', datalab: 'down' }))),
    `NASA IRSA image search and ESA Gaia archive are not answering right now, so WISE and SPHEREx images and Gaia stars may be missing. ${TAIL}`);
  assert.equal(troubleSentence(cleanStatus(raw({ irsa_sia: 'slow' }))),
    `NASA IRSA image search is slow to answer right now, so WISE and SPHEREx images may take longer to arrive. ${TAIL}`);
  assert.equal(countLine(stripItems(cleanStatus(raw({ irsa_sia: 'down', gaia: 'down', irsa_tap: 'slow' })))), '1 of 3 answering');
});

test('a lookup hears only of archives it uses', () => {
  const jpl = { ...raw(), archives: [A('horizons', 'JPL Horizons', 'Solar System body positions', 'down'),
    A('sbdb', 'JPL Small-Body Database', 'Solar System body name lookups', 'up'), A('sesame', 'CDS Sesame name lookup', 'object name lookups', 'down')] };
  const d = cleanStatus(jpl);
  assert.equal(troubleSentence(d, { uses: { body: false, name: false } }), null);
  assert.match(troubleSentence(d, { uses: { body: true, name: false } }), /^JPL Horizons is not answering/);
  assert.match(troubleSentence(d, { uses: { body: false, name: true } }), /^CDS Sesame name lookup is not answering/);
  assert.match(troubleSentence(d), /^JPL Horizons and CDS Sesame name lookup are not answering/); // the strip: all
});

test('what a lookup uses comes from its URL', () => {
  assert.deepEqual(lookupUses('?body=Ceres'), { body: true, name: false });
  assert.deepEqual(lookupUses('?ra=1&dec=2&label=Vega'), { body: false, name: true });
  assert.deepEqual(lookupUses('?ra=1&dec=2'), { body: false, name: false });
  assert.deepEqual(lookupUses(''), { body: false, name: false });
});

test('recent failures speak only when asked (partial lookups)', () => {
  const d = cleanStatus(raw({}, { irsa_sia: { checks: 6, answered: 5, since: '2026-11-15T17:10:00Z', failed_last_hour: 1 } }));
  assert.equal(troubleSentence(d), null);
  assert.equal(troubleSentence(d, { recent: true }),
    `NASA IRSA image search is answering now but missed some of our checks in the last hour, so WISE and SPHEREx images may have been missing. ${TAIL}`);
});

test('dates and times read "18:10 on 15 Nov"', () => {
  assert.equal(formatWhen('2026-11-15T18:10:00Z', { timeZone: 'UTC' }), '18:10 on 15 Nov');
  assert.equal(formatWhen('2026-11-15T18:10:00Z', { timeZone: 'America/New_York' }), '13:10 on 15 Nov');
  assert.equal(formatWhen('nonsense'), '');
});

test('history line says what was measured and since when', () => {
  assert.equal(historyLine({ checks: 52, answered: 41, since: '2026-11-15T18:10:00Z' }, { timeZone: 'UTC' }),
    'answered 41 of the last 52 checks since 18:10 on 15 Nov');
  assert.equal(historyLine({ checks: 1, answered: 1, since: 'x' }), 'answered 1 of the one check');
  assert.equal(historyLine({ checks: 0 }), null);
  assert.equal(historyLine(undefined), null);
});

test('small words', () => {
  assert.equal(joinWords(['a', 'b', 'c']), 'a, b and c');
  assert.equal(phrase('down'), 'not answering');
  assert.equal(measuredText({ status: 'up', latencyMs: 1234 }), '1.2 s');
  assert.equal(measuredText({ status: 'down', detail: 'HTTP 502' }), 'HTTP 502');
});

test('checks older than 30 minutes, or missing, mean the status is unknown', () => {
  const t = Date.parse('2026-11-15T18:10:00Z');
  assert.equal(isStale('2026-11-15T18:10:00Z', t + 29 * 60000), false);
  assert.equal(isStale('2026-11-15T18:10:00Z', t + 31 * 60000), true);
  assert.equal(isStale(null, t), true);
  assert.equal(isStale('', t), true);
  assert.equal(formatTime('2026-11-15T17:20:00Z', UTC), '17:20');
  assert.equal(formatTime('nope'), '');
});

test('status page lead: no data, no checks, stale, trouble, all well', () => {
  const t = Date.parse('2026-11-15T18:10:00Z');
  assert.equal(statusLead(null, t), 'The archive checks could not be loaded just now.');
  assert.equal(statusLead(cleanStatus({ checked_at: null, archives: [] }), t), 'No archive checks are available yet.');
  assert.match(statusLead(cleanStatus(raw()), t + 45 * 60000, UTC), /^Our archive checks last ran at 18:10 on 15 Nov, more than 30 minutes ago/);
  assert.match(statusLead(cleanStatus(raw({ irsa_sia: 'down' })), t, UTC), /^NASA IRSA image search is not answering right now.*Checked at 18:10\.$/);
  assert.equal(statusLead(cleanStatus(raw()), t, UTC), 'Every archive we use answered our last check, at 18:10.');
});
