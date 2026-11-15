import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { validateManifest } from '../js/manifest.js';
import { passSummary, templateCurves } from '../js/matchtext.js';
import { groupTargets, groupHeading } from '../js/gallery.js';

const base = () => JSON.parse(readFileSync(new URL('./fixtures/gallery/synthetic-fast-mover/manifest.json', import.meta.url)));
const curve = (y) => [[1, y], [2, y]];

// 1. pair curve
test('manifest keeps pair.model and tolerates its absence', () => {
  const m = base();
  m.match = { best: { type: 'T2' }, runner_up: { type: 'T6' }, models: { T2: curve(1), 'T2 + T6': curve(2) },
    pair: { types: ['T2', 'T6'], chi2: 1, delta_vs_single: 30, model: 'T2 + T6' } };
  assert.equal(validateManifest(m).manifest.match.pair.model, 'T2 + T6');
  m.match.pair = { types: ['T2', 'T6'] };
  assert.equal(validateManifest(m).manifest.match.pair.model, null);
});

test('templateCurves adds an emphasised pair curve when present', () => {
  const match = { best: { type: 'T2' }, runner_up: { type: 'T6' }, pair: { model: 'T2 + T6' },
    models: { T2: curve(1), T6: curve(2), 'T2 + T6': curve(3) } };
  const c = templateCurves(match);
  assert.deepEqual(c.map((x) => x.role), ['best', 'runner-up', 'pair']);
  const pair = c.at(-1);
  assert.equal(pair.label, 'T2 + T6 blend');
  assert.ok(pair.width > Math.max(...c.slice(0, 2).map((x) => x.width)));
  assert.notEqual(pair.dash, c[0].dash);
});

test('templateCurves without a pair, or with the curve missing, draws best and runner-up only', () => {
  const models = { T2: curve(1), T6: curve(2) };
  const noPair = templateCurves({ best: { type: 'T2' }, runner_up: { type: 'T6' }, pair: null, models });
  assert.deepEqual(noPair.map((x) => x.role), ['best', 'runner-up']);
  assert.equal(noPair[0].width, 3);
  const missing = templateCurves({ best: { type: 'T2' }, runner_up: null, pair: { model: 'T2 + T6' }, models });
  assert.deepEqual(missing.map((x) => x.role), ['best']);
  assert.deepEqual(templateCurves(null), []);
});

// 2. pass agreement
test('passSummary prefers pass_agreement.sentence over the exact-type comparison', () => {
  const per_pass = [{ class: 'brown dwarf', type: 'T8' }, { class: 'brown dwarf', type: 'T7' }];
  const sentence = 'All 2 passes typed on their own agree.';
  assert.equal(passSummary({ per_pass, pass_agreement: { status: 'agree', sentence } }), sentence);
  assert.equal(passSummary({ per_pass }), 'Passes disagree: T8, T7');
  assert.equal(passSummary({ per_pass, pass_agreement: null }), 'Passes disagree: T8, T7');
});

test('manifest keeps pass_agreement, dropping unreadable values', () => {
  const m = base();
  m.match = { best: { type: 'T2' }, pass_agreement: { status: 'agree', sentence: 'They agree.' } };
  assert.deepEqual(validateManifest(m).manifest.match.pass_agreement, { status: 'agree', sentence: 'They agree.' });
  m.match.pass_agreement = { status: 'agree' };
  assert.equal(validateManifest(m).manifest.match.pass_agreement, null);
  delete m.match.pass_agreement;
  assert.equal(validateManifest(m).manifest.match.pass_agreement, null);
});

// 3. gallery groups
test('groupHeading maps known groups and capitalises unknown ones', () => {
  assert.equal(groupHeading('brief'), 'From the challenge brief');
  assert.equal(groupHeading('backyard-worlds'), 'Backyard Worlds discoveries');
  assert.equal(groupHeading('benchmark'), 'Brown dwarfs with published spectral types');
  assert.equal(groupHeading('misc-things'), 'Misc-things');
  assert.equal(groupHeading(null), null);
});

test('groupTargets puts brief first and keeps ungrouped targets in one group', () => {
  const t = [{ slug: 'a', group: 'benchmark' }, { slug: 'b' }, { slug: 'c', group: 'brief' },
    { slug: 'd', group: 'backyard-worlds' }, { slug: 'e', group: null }];
  const g = groupTargets(t);
  assert.deepEqual(g.map((x) => x.group), ['brief', 'benchmark', 'backyard-worlds', null]);
  assert.deepEqual(g.at(-1).targets.map((x) => x.slug), ['b', 'e']);
});

test('Solar System bodies get their heading and come after every other group', () => {
  assert.equal(groupHeading('solar-system'), 'Solar System objects');
  const g = groupTargets([{ slug: 'h', group: 'solar-system' }, { slug: 'b' }, { slug: 'c', group: 'brief' }]);
  assert.deepEqual(g.map((x) => x.group), ['brief', null, 'solar-system']);
});
