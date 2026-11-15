import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { bestReach, reachBars, leadAnswer, P9_RANGE_AU } from '../js/planetxdata.js';

const data = JSON.parse(readFileSync(new URL('../data/planetx-limits.json', import.meta.url)));
const se10Reach = () => bestReach(data.cases.find((c) => c.key === 'se10'), 'spx_one_map_channel');

test('reach bars: numbers for plotting, clipped to the grid, with words for the likely value', () => {
  const bars = reachBars(data, 'spx_one_map_channel');
  assert.equal(bars.length, data.cases.length);
  const se10 = bars.find((b) => b.key === 'se10');
  const r = se10Reach();
  assert.deepEqual([se10.lo, se10.nom, se10.hi], [r.lo, r.nom, r.hi]);
  assert.equal(se10.text, `${r.nom} au`);
  const fake = { cases: [{ key: 'x', label: 'X', reach_au: { d: { A: { lo: '<200', nom: '<200', hi: '>1500' } } } }] };
  assert.deepEqual(reachBars(fake, 'd')[0], { key: 'x', label: 'X', lo: 200, nom: 200, hi: 1500, text: 'under 200 au' });
});

test('lead answer: verdict, the reach against the predicted range, and never a detection', () => {
  const lead = leadAnswer(data);
  const r = se10Reach();
  assert.match(lead.detail, new RegExp(`about ${r.nom} au`));
  assert.match(lead.detail, new RegExp(`${P9_RANGE_AU[0]} to ${P9_RANGE_AU[1]} au`));
  assert.match(lead.detail, /not a detection/);
  assert.ok(!/—/.test(lead.verdict + lead.detail));
  const mk = (lo, nom, hi) => ({ cases: [{ key: 'se10', reach_au: { spx_one_map_channel: { A: { lo, nom, hi } } } }] });
  assert.match(leadAnswer(mk(200, 300, 350)).verdict, /^Probably not\./);
  assert.match(leadAnswer(mk(225, 375, 550)).verdict, /^Only just/);
  assert.match(leadAnswer(mk(450, 600, 900)).verdict, /^Yes/);
  assert.equal(leadAnswer({ cases: [] }), null);
});
