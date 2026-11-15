import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { pickHero, heroTraits } from '../js/hero.js';
import { noTypeWhy } from '../js/notes.js';
import { validateManifest, validateIndex } from '../js/manifest.js';

const GAL = new URL('../gallery/', import.meta.url);
const real = existsSync(new URL('index.json', GAL)) && validateIndex(JSON.parse(readFileSync(new URL('index.json', GAL)))).length > 0;

test('the real gallery leads with a typed, unsaturated, agreeing, fast target (no slug in the rule)', { skip: !real }, () => {
  const idx = validateIndex(JSON.parse(readFileSync(new URL('index.json', GAL))));
  const cands = idx.map((entry) => ({ entry, manifest: validateManifest(JSON.parse(readFileSync(new URL(entry.manifest, GAL)))).manifest }));
  const hero = pickHero(cands);
  const t = heroTraits(cands.find((c) => c.entry === hero).manifest);
  assert.ok(t.bothMissions && t.typed && t.unsaturated && t.agrees && t.speed > 1, JSON.stringify(t));
  assert.equal(hero.slug, '2mass-0415-0935');
});

const m = (over = {}) => ({
  frames: [{ mission: 'WISE', warnings: [] }, { mission: 'SPHEREx', warnings: [] }],
  match: { best: { type: 'T8' } }, target: { pmra_masyr: 1000, pmdec_masyr: 0 },
  measured_motion: { pmra_masyr: 1001, pmdec_masyr: 0, err_masyr: 5 }, ...over,
});
const c = (slug, manifest) => ({ entry: { slug }, manifest });

test('weaker candidates win only when nothing qualifies; larger motion breaks ties, then index order', () => {
  const sat = m({ frames: [{ mission: 'WISE', warnings: ['saturated'] }, { mission: 'SPHEREx', warnings: [] }] });
  const noMatch = m({ match: null });
  assert.equal(pickHero([c('a', sat), c('b', noMatch), c('c', m())]).slug, 'c');
  assert.equal(pickHero([c('a', sat), c('b', noMatch)]).slug, 'a');
  const fast = m({ target: { pmra_masyr: 3000, pmdec_masyr: 0 }, measured_motion: { pmra_masyr: 3002, pmdec_masyr: 0, err_masyr: 5 } });
  assert.equal(pickHero([c('a', m()), c('b', fast)]).slug, 'b');
});

test('with no manifests at all, the first entry; with none, null', () => {
  assert.equal(pickHero([{ entry: { slug: 'x' }, manifest: null }, { entry: { slug: 'y' }, manifest: null }]).slug, 'x');
  assert.equal(pickHero([]), null);
});

test('a still target is never preferred to a moving one', () => {
  assert.equal(pickHero([c('a', m({ measured_motion: null })), c('b', m({ match: null }))]).slug, 'b');
});

test('reasons for no type call come from the warnings', () => {
  assert.equal(noTypeWhy(['Every SPHEREx spectrum point is unusable (357 where the target saturates the detector), so there is no spectrum to judge.'], false), 'saturated');
  assert.equal(noTypeWhy(['The spectrum is not classified because a Gaia star comes within one SPHEREx pixel'], true), 'a neighbouring star shares the pixel');
  assert.equal(noTypeWhy(['Detected, but too faint to classify (S/N 3).'], true), 'too faint to classify');
  assert.equal(noTypeWhy([], false), 'no usable spectrum');
});
