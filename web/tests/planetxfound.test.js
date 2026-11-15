import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { foundLines, blindLine, recoveryLine, iceClause } from '../js/planetxfound.js';

const j = (p) => JSON.parse(readFileSync(new URL(p, import.meta.url)));
const movers = j('../data/movers.json');
const bodies = j('../data/body-recovery.json');
const haumea = j('../gallery/haumea/manifest.json');
const makemake = j('../gallery/makemake/manifest.json');

test('found lines: three, in order, each with a link, never a discovery claimed', () => {
  const lines = foundLines({ movers, bodies, haumea, makemake });
  assert.equal(lines.length, 3);
  assert.deepEqual(lines.map((l) => l.href), ['search.html', 'validation.html#bodies', 'index.html?target=haumea']);
  for (const l of lines) assert.ok(!/candidate|discovered|—/.test(l.text), l.text);
});

test('blind line: names and S/N come from movers.json; a validation, not a discovery', () => {
  const t = blindLine(movers).text;
  for (const k of movers.known_bodies) assert.ok(t.includes(k.name) && t.includes(k.snr.toFixed(1)), t);
  assert.match(t, /strongest signal in its field/);
  assert.match(t, /a validation, not a discovery/);
  const off = { ...movers, known_bodies: movers.known_bodies.map((k) => ({ ...k, rank: 2 })) };
  assert.ok(!/strongest/.test(blindLine(off).text));
  assert.equal(blindLine({}), null);
});

test('recovery line: counts from body-recovery.json', () => {
  const t = recoveryLine(bodies).text;
  assert.ok(t.includes(`${bodies.bodies.recovered} of ${bodies.bodies.n}`), t);
  assert.ok(t.includes(`(${bodies.by_class.TNO.recovered} of ${bodies.by_class.TNO.n} beyond Neptune`), t);
  assert.equal(recoveryLine(null), null);
});

test('ice: the pipeline reading picks the band; a saturated band reads as a lower limit', () => {
  assert.match(iceClause('Haumea', haumea), /water ice \(the 2\.0 µm band \d+% ± \d+% deep\)/);
  assert.match(iceClause('Makemake', makemake), /methane ice \(the 2\.3 µm band deeper than \d+%\)/);
  assert.equal(iceClause('X', { solar_system: { reflectance: [] } }), null);
  assert.equal(foundLines({ movers }).length, 1);
});
