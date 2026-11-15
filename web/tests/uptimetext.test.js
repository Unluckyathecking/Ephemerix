import { test } from 'node:test';
import assert from 'node:assert/strict';
import { decodeChecks, level, dayBlocks, hourBlocks, checkWords, shareLine, recordLine, longestGap, gapLine, dayLabel } from '../js/uptimetext.js';

const UTC = { timeZone: 'UTC' };
const T = Date.parse('2026-11-15T17:35:00Z') / 1000;
const CHECKS = {
  times: [T, T + 300, T + 600, T + 900, T + 1200],
  archives: { irsa_sia: { codes: 'udd-s', ms: [400, null, null, null, 6100], fail: { 1: 'HTTP 502', 2: 'no answer within 10 s' } } },
};

test('decode: one entry per check, unchecked dropped, details kept', () => {
  const d = decodeChecks(CHECKS).irsa_sia;
  assert.deepEqual(d.map((c) => c.code), ['u', 'd', 'd', 's']);
  assert.equal(d[1].detail, 'HTTP 502');
  assert.equal(d[0].ms, 400);
  assert.deepEqual(decodeChecks(null), {});
  assert.deepEqual(decodeChecks({ times: [T], archives: { x: { codes: 5 } } }), { x: [] });
});

test('levels: none, up, mixed, down', () => {
  assert.equal(level(0, 0, 0), 'none');
  assert.equal(level(12, 12, 0), 'up');
  assert.equal(level(12, 12, 1), 'mixed');
  assert.equal(level(12, 9, 0), 'mixed');
  assert.equal(level(12, 0, 0), 'down');
});

test('day blocks: 30 days ending today, days before watching began empty', () => {
  const days = { dates: ['2026-11-14', '2026-11-15'], archives: { gaia: [[288, 288, 0], [200, 180, 3]] } };
  const b = dayBlocks(days, 'gaia', '2026-11-15');
  assert.equal(b.length, 30);
  assert.equal(b[0].date, '2026-10-17');
  assert.ok(b.slice(0, 28).every((x) => x.level === 'none' && x.label.endsWith('no checks')));
  assert.deepEqual([b[28].level, b[29].level], ['up', 'mixed']);
  assert.equal(b[29].label, '15 Nov: 180 of 200 checks answered, 3 slow');
  assert.equal(dayBlocks(days, 'nothing', '2026-11-15')[29].level, 'none');
  assert.deepEqual(dayBlocks(days, 'gaia', 'bad'), []);
  assert.equal(dayLabel('2026-11-05'), '5 Nov');
});

test('hour blocks: 24 per day, checks in their hour, labelled', () => {
  const h = hourBlocks(decodeChecks(CHECKS).irsa_sia, '2026-11-15', UTC);
  assert.equal(h.length, 24);
  assert.equal(h[17].checks.length, 4);
  assert.equal(h[17].level, 'mixed');
  assert.equal(h[17].label, '17:00 to 18:00: 2 of 4 checks answered, 1 slow');
  assert.equal(h[18].label, '18:00 to 19:00: no checks');
  assert.equal(h[3].label, '03:00 to 04:00: no checks');
});

test('a check in words', () => {
  const [up, down] = decodeChecks(CHECKS).irsa_sia;
  assert.deepEqual(checkWords(up, UTC), { time: '17:35', state: 'answering', response: '0.4 s', detail: '' });
  assert.deepEqual(checkWords(down, UTC), { time: '17:40', state: 'not answering', response: '', detail: 'HTTP 502' });
});

test('share answered never rounds up to 100%', () => {
  assert.equal(shareLine([{ checks: 8640, answered: 8412 }]), 'answered 8,412 of 8,640 checks, 97%');
  assert.equal(shareLine([{ checks: 1000, answered: 999 }]), 'answered 999 of 1,000 checks, 99%');
  assert.equal(shareLine([{ checks: 0, answered: 0 }]), null);
});

test('longest gap: the longest run of failed checks in a row', () => {
  const list = decodeChecks(CHECKS).irsa_sia;
  const g = longestGap(list);
  assert.equal(g.count, 2);
  assert.equal(gapLine(g, UTC), 'longest gap: 17:40 to 17:45 on 15 Nov (2 checks)');
  assert.equal(gapLine(longestGap(list.slice(0, 2)), UTC), 'longest gap: one check at 17:40 on 15 Nov');
  assert.equal(longestGap(list.filter((c) => c.code !== 'd')), null);
  assert.equal(gapLine(null), null);
});

test('record line: says how long the record really is', () => {
  const blocks = (held) => Array.from({ length: 30 }, (_, i) => {
    const date = new Date(Date.UTC(2026, 10, 15) - (29 - i) * 86400000).toISOString().slice(0, 10);
    const [checks, answered] = held[i] ?? [0, 0];
    return { date, checks, answered };
  });
  const first = Date.UTC(2026, 10, 15, 18, 47);
  const today = (c, a) => blocks({ 29: [c, a] });
  assert.equal(recordLine(today(6, 6), first, UTC), 'Since checks began at 18:47 on 15 Nov: answered 6 of 6 checks');
  assert.equal(recordLine(today(6, 0), first, UTC), 'Since checks began at 18:47 on 15 Nov: answered 0 of 6 checks');
  assert.equal(recordLine(today(60, 59), first, UTC), 'Since checks began at 18:47 on 15 Nov: answered 59 of 60 checks, 98%');
  assert.equal(recordLine(blocks({ 27: [288, 288], 28: [288, 280], 29: [100, 100] }), first, UTC), 'Since 13 Nov: answered 668 of 676 checks, 98%');
  assert.equal(recordLine(blocks({ 0: [288, 280], 29: [288, 288] }), first, UTC), 'Last 30 days: answered 568 of 576 checks, 98%');
  assert.equal(recordLine(blocks({}), null, UTC), null);
});
