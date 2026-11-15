import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resultsLead, typeShort, motionShort, briefRows, choiceSentence, partialTile } from '../js/validationlead.js';
import { summarySentences } from '../js/variabilitytext.js';
import { motionText } from '../js/validationtext.js';

const report = JSON.parse(readFileSync(new URL('../data/validation.json', import.meta.url)));
const variability = JSON.parse(readFileSync(new URL('../data/variability.json', import.meta.url)));
const s = report.summary;

test('lead: two sentences with the motion and type counts from the summary', () => {
  const lead = resultsLead(s);
  assert.equal(lead.length, 2);
  assert.match(lead[0], new RegExp(`${s.motion.total} of our ${s.targets} targets`));
  assert.match(lead[0], new RegExp(`${s.motion.passed} agree with the catalogue and ${s.motion.failed} differ`));
  const types = s.type.passed === s.type.total ? `all ${s.type.total} scored types` : `${s.type.passed} of the ${s.type.total} scored types`;
  assert.match(lead[1], new RegExp(`${types} contain the published type`));
  const faint = s.type.faint.passed + s.type.faint.failed;
  assert.match(lead[1], new RegExp(`we gave ${s.type.total + faint} types`));
  assert.match(lead[1], /counted apart/);
  assert.match(lead[1], new RegExp(`${s.type.refused} unclassified`));
  assert.ok(!/—/.test(lead.join(' ')));
});

test('lead: singulars and no failures read naturally', () => {
  const lead = resultsLead({ targets: 3, motion: { passed: 3, failed: 0, total: 3 }, type: { passed: 1, total: 1, refused: 1 } });
  assert.match(lead[0], /all 3 agree with the catalogue\./);
  assert.match(lead[1], /1 of the 1 type we gave contains/);
  assert.match(lead[1], /1 unclassified/);
});

test('type in a few words: the verdict against the published type, or why there is none', () => {
  const by = Object.fromEntries(report.targets.map((t) => [t.slug, t]));
  assert.equal(typeShort(by['epsilon-indi-b']).text, 'T2 (range T1 to T3) against T1-1.5 + T6 (unresolved pair)');
  assert.equal(typeShort(by['epsilon-indi-b']).verdict, 'pass');
  assert.equal(typeShort(by['barnards-star']).text, 'None: it saturates the SPHEREx detectors');
  assert.equal(typeShort(by['r-draconis']).text, 'None: it saturates the SPHEREx detectors');
  assert.equal(typeShort(by['wise-0855-0714']).text, 'None: a nearby star may add its light');
  assert.equal(typeShort(by['rw-aurigae']).text, 'None: too few usable points in its spectrum');
  assert.equal(typeShort(by['cwise-2021-1524']).text, 'None: not found in any image');
  assert.equal(typeShort({ type: { verdict: 'refused', reason: 'Something new.' } }).text, 'None: see the spectral types below');
});

test('motion in a few words: ours against the catalogue through motionText', () => {
  const t = report.targets.find((x) => x.slug === 'barnards-star');
  const m = motionShort(t);
  assert.equal(m.text, `${motionText(t.motion).total} ″/yr`);
  assert.equal(m.word, 'agrees');
  for (const slug of ['r-draconis', 'rw-aurigae']) {
    assert.equal(motionShort(report.targets.find((x) => x.slug === slug)).word, 'consistent (weak test)');
  }
  const f = report.targets.find((x) => x.motion.verdict === 'fail');
  assert.equal(motionShort(f).word, 'differs');
});

test('the five brief targets, in order, with the measured brightness change for the two variable stars only', () => {
  const rows = briefRows(report, variability);
  assert.deepEqual(rows.map((r) => r.slug), report.targets.filter((t) => t.group === 'brief').map((t) => t.slug));
  assert.equal(rows.length, 5);
  assert.equal(rows.filter((r) => r.type.verdict === 'pass').length, 1);
  assert.equal(rows.find((r) => r.slug === 'r-draconis').brightness, summarySentences('r-draconis', variability)[0]);
  assert.equal(rows.find((r) => r.slug === 'rw-aurigae').brightness, summarySentences('rw-aurigae', variability)[0]);
  assert.equal(rows.find((r) => r.slug === 'barnards-star').brightness, null);
  assert.equal(briefRows(report, null).find((r) => r.slug === 'r-draconis').brightness, null);
});

test('how the targets were chosen: counts per group from the report', () => {
  const t = choiceSentence(report.targets);
  const n = (g) => report.targets.filter((x) => x.group === g).length;
  assert.match(t, new RegExp(`^The ${report.targets.length} targets are the ${n('brief')} the challenge brief names`));
  assert.match(t, new RegExp(`${n('backyard-worlds')} brown dwarfs found by the Backyard Worlds citizen-science project`));
  assert.match(t, new RegExp(`${n('benchmark')} well-studied benchmark brown dwarfs`));
  assert.match(t, /published spectral type and motion/);
});

test('partial-data tile: shown with its count, or a calm line when there are none', () => {
  assert.deepEqual(partialTile({ targets: 17, degraded: 8 }), { value: '8', of: 'of 17', label: 'Views built from partial data' });
  assert.deepEqual(partialTile({ targets: 17, degraded: 0 }), { value: '0', of: 'of 17', label: 'Views built from partial data: every view has its full data' });
  assert.deepEqual(partialTile({ targets: 17 }), partialTile({ targets: 17, degraded: 0 }));
});
