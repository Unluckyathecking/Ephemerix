import { test } from 'node:test';
import assert from 'node:assert/strict';
import { formatDate, dataStatusLine } from '../js/datastatus.js';

const GOOD = {
  schema: 1,
  index: { releases: [{ name: 'DR1', frames: 1179406 }, { name: 'QR3', frames: 448823 }],
    frames_total: 1628229, newest_frame: '2026-10-05', refreshed: '2026-11-14' },
  gallery: { newest_frame: '2026-10-02', built: '2026-11-15' },
};

test('formatDate gives "2 Oct 2026" and rejects non-dates', () => {
  assert.equal(formatDate('2026-10-02'), '2 Oct 2026');
  assert.equal(formatDate('2026-11-14'), '14 Nov 2026');
  for (const bad of ['2026-02-30', '2026-13-01', 'yesterday', '', null, undefined, 20261002]) assert.equal(formatDate(bad), null);
});

test('dataStatusLine states the index and the gallery separately', () => {
  assert.equal(dataStatusLine(GOOD),
    'SPHEREx data through 5 Oct 2026 (releases DR1 and QR3; 1,628,229 frames indexed, last refreshed 14 Nov 2026). '
    + 'The views on this site show SPHEREx frames to 2 Oct 2026 and were built on 15 Nov 2026.');
});

test('one release, three releases, and no gallery section', () => {
  const one = { ...GOOD, gallery: undefined, index: { ...GOOD.index, releases: [{ name: 'DR1', frames: 1628229 }] } };
  assert.equal(dataStatusLine(one),
    'SPHEREx data through 5 Oct 2026 (release DR1; 1,628,229 frames indexed, last refreshed 14 Nov 2026).');
  const three = { ...GOOD, index: { ...GOOD.index, releases: [{ name: 'DR1', frames: 1 }, { name: 'QR3', frames: 2 }, { name: 'QR4', frames: 1628226 }] } };
  assert.match(dataStatusLine(three), /releases DR1, QR3 and QR4;/);
});

test('missing or malformed data gives no line at all', () => {
  const broken = [null, undefined, 'x', {}, { index: null },
    { ...GOOD, index: { ...GOOD.index, newest_frame: 'soon' } },
    { ...GOOD, index: { ...GOOD.index, frames_total: -1 } },
    { ...GOOD, index: { ...GOOD.index, frames_total: 1.5 } },
    { ...GOOD, index: { ...GOOD.index, releases: [] } },
    { ...GOOD, index: { ...GOOD.index, releases: [{ name: '', frames: 1 }] } },
    { ...GOOD, index: { ...GOOD.index, refreshed: undefined } },
    { ...GOOD, gallery: { newest_frame: '2026-10-02' } }];
  for (const b of broken) assert.equal(dataStatusLine(b), '');
});
