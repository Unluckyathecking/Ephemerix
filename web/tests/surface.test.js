// The judge-critique additions: the home page's proof line, and the fourth verdict tile
// (the blind search of the patch, or a variable star's brightness).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { proofLine } from '../js/scoreboard.js';
import { verdictTiles, searchTile, brightnessTile } from '../js/verdict.js';
import { validateManifest } from '../js/manifest.js';
import { shortFinding } from '../js/variabilitytext.js';
import { comovingLine } from '../js/fieldmovers.js';

const read = (p) => JSON.parse(readFileSync(new URL(`../${p}`, import.meta.url)));
const view = (slug) => validateManifest(read(`gallery/${slug}/manifest.json`)).manifest;

test('proof line: every number from the report, the failures said plainly', () => {
  const s = read('data/validation.json').summary;
  const { targets, motion: m } = s;
  const tail = m.failed ? `, ${m.failed} ${m.failed === 1 ? 'does' : 'do'} not` : '';
  assert.equal(proofLine(s), `Checked on ${targets} objects with published values: ${m.passed} of ${m.total} motions agree${tail}.`);
  assert.equal(proofLine({ targets: 17, motion: { passed: 14, failed: 2, total: 16 } }), 'Checked on 17 objects with published values: 14 of 16 motions agree, 2 do not.');
  assert.equal(proofLine({ targets: 5, motion: { passed: 4, failed: 1, total: 5 } }), 'Checked on 5 objects with published values: 4 of 5 motions agree, 1 does not.');
  assert.equal(proofLine({ targets: 5, motion: { passed: 5, failed: 0, total: 5 } }), 'Checked on 5 objects with published values: 5 of 5 motions agree.');
  for (const bad of [null, {}, { targets: 5 }, { targets: 5, motion: { passed: 0, total: 0 } }]) assert.equal(proofLine(bad), null);
});

test('search tile: from the block\'s own movers, linked to the block, absent when not searched', () => {
  const plain = view('wise-0855-0714');
  assert.deepEqual(searchTile(plain), { key: 'search', href: '#movers', label: 'Search', sub: 'blind search of this patch', value: 'Nothing else moved', tone: 'quiet' });
  assert.deepEqual(verdictTiles(plain).map((t) => t.key), ['motion', 'spectrum', 'data', 'search']);
  const fm = plain.field_movers;
  assert.equal(searchTile({ ...plain, field_movers: { ...fm, n_candidates: 2 } }).value, '2 unexplained tracks');
  const gaia = { ...fm.movers[0], label: 'gaia', pmra_masyr: 10, pmdec_masyr: 0 };
  assert.equal(searchTile({ ...plain, field_movers: { ...fm, movers: [...fm.movers, gaia] } }).value, '1 known mover');
  const twin = { ...fm.movers[0], label: 'gaia', px: [fm.movers[0].px[0] + 3, fm.movers[0].px[1]] };
  assert.equal(searchTile({ ...plain, field_movers: { ...fm, movers: [...fm.movers, twin] } }).value, 'A star moves with it');
  // The real case: CWISE J2029-7910's host star, recovered blind and at the same Gaia distance.
  assert.equal(searchTile(view('cwise-2029-7910')).value, 'Its companion star, found blind');
  assert.equal(searchTile({ ...plain, field_movers: { ...fm, status: 'not_searched' } }), null);
  assert.equal(searchTile({ ...plain, field_movers: null }), null);
  assert.deepEqual(verdictTiles({ ...plain, field_movers: null }).map((t) => t.key), ['motion', 'spectrum', 'data']);
});

test('brightness tile: a variable star\'s finding, never with the search tile, four tiles at most', () => {
  const d = read('data/variability.json');
  for (const slug of ['r-draconis', 'rw-aurigae']) {
    const m = view(slug);
    const f = shortFinding(slug, d);
    const t = brightnessTile(f);
    assert.equal(t.href, '#variability');
    assert.ok(t.value.length < 60 && !/Draconis|Aurigae/.test(t.value), t.value);
    assert.ok(t.value.length < 25 && f.includes(`${t.value.slice(1)} ${t.sub}`), [t.value, t.sub]);
    assert.deepEqual(verdictTiles(m, { variable: true }).map((x) => x.key), ['motion', 'spectrum', 'data']);
    assert.deepEqual(verdictTiles(m, { variable: true, finding: f }).map((x) => x.key), ['motion', 'spectrum', 'data', 'brightness']);
  }
});

test('Simple keeps the co-moving conclusion without the parallax numbers', () => {
  const m = view('cwise-2029-7910');
  const star = m.field_movers.movers.find((mv) => mv.label === 'gaia');
  const text = comovingLine(star, m.field_movers.movers, m.fov_arcsec / m.size_px, m, { numbers: false });
  assert.ok(text.includes('Gaia puts both at the same distance, so the two travel together.') && !text.includes('mas'), text);
});
