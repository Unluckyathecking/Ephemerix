import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { searchLead, pilotSentence } from '../js/searchdata.js';

const movers = JSON.parse(readFileSync(new URL('../data/movers.json', import.meta.url)));
const p9 = JSON.parse(readFileSync(new URL('../data/p9-search.json', import.meta.url)));

test('search lead: what we tried, the known bodies, nothing new, and the pilot cannot test Planet Nine', () => {
  const t = searchLead(movers, p9);
  assert.match(t, new RegExp(`${movers.fields.length} small patches`));
  assert.match(t, new RegExp(`all ${movers.known_bodies.length} known dwarf planets`));
  assert.match(t, /nothing new above the noise/);
  assert.match(t, new RegExp(`V ${p9.pooled.vmag50.toFixed(1)}`));
  assert.match(t, new RegExp(`${p9.area_deg2.toFixed(1)} square degrees`));
  assert.match(t, /cannot test Planet Nine/);
  assert.match(t, /none of the favoured/);
  assert.ok(!/—/.test(t));
});

test('pilot sentence: the most likely 10-Earth-mass reach from the data, against the predicted range', () => {
  const nom = p9.planetx_reach.at_pooled_flux50.find((r) => r.key === 'se10').reach_nom_au;
  const t = pilotSentence(p9);
  if (nom < 400) assert.match(t, new RegExp(`about ${Math.round(nom)} au, short of the 400 to 800 au`));
  const far = { ...p9, planetx_reach: { at_pooled_flux50: [{ key: 'se10', reach_nom_au: 450 }] } };
  assert.ok(!/short of/.test(pilotSentence(far)));
  const none = { ...p9, planetx_reach: undefined };
  assert.ok(!/short of/.test(pilotSentence(none)) && /cannot test Planet Nine/.test(pilotSentence(none)));
  assert.equal(pilotSentence({}), null);
});

test('search lead: the real sky against the backwards search, counted from the data', () => {
  const t = searchLead(movers, p9);
  const sum = (k) => movers.fields.filter((f) => f.kind !== 'control').reduce((a, f) => a + f.peaks[k], 0);
  assert.ok(t.includes(`${sum('real_ge7')} peaks at S/N 7 or above`), t);
  assert.ok(t.includes(`where nothing real moves: ${sum('null_ge7')}`), t);
  assert.match(t, /a validation, not a discovery/);
  assert.ok(t.indexOf('Haumea') < t.indexOf('backwards'));
});

test('search lead without the pilot file says nothing about Planet Nine', () => {
  const t = searchLead(movers, null);
  assert.ok(!/Planet Nine/.test(t));
  assert.match(t, /nothing new above the noise/);
});
