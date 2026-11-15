import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { falseColourPlan, falseColourCaption } from '../js/falsecolour.js';
import { passFrames } from '../js/framesets.js';
import { setLabel } from '../js/labels.js';
import { parseState, serializeState } from '../js/urlstate.js';
import { validateManifest } from '../js/manifest.js';

const fixture = (slug) => validateManifest(JSON.parse(readFileSync(new URL(`./fixtures/gallery/${slug}/manifest.json`, import.meta.url)))).manifest;

test('channels chosen by wavelength: red 4.42-5.0, green 1.65-2.42, blue 2.42-3.82 µm', () => {
  const m = fixture('synthetic-fast-mover');
  const spx = m.frames.find((f) => f.mission === 'SPHEREx');
  const plan = falseColourPlan(passFrames(m.frames, spx.mjd));
  assert.equal(plan.ok, true);
  assert.deepEqual(plan.channels.map((c) => c.set.window), [[4.42, 5.0], [1.65, 2.42], [2.42, 3.82]]);
  const mjds = plan.channels.map((c) => c.frame.mjd);
  assert.ok(Math.max(...mjds) - Math.min(...mjds) <= 30, 'all three from one pass');
  const cap = falseColourCaption(plan, setLabel);
  assert.match(cap, /^False colour, not true colour: red SPHEREx 4\.42–5\.0 µm, green SPHEREx 1\.65–2\.42 µm, blue SPHEREx 2\.42–3\.82 µm\./);
  assert.match(cap, /not flux ratios/);
});

test('disabled with a reason when bands or images are missing', () => {
  const m = fixture('synthetic-faint'); // only the 3.82-4.42 and 4.42-5.0 µm bands
  const plan = falseColourPlan(passFrames(m.frames, m.frames.at(-1).mjd));
  assert.equal(plan.ok, false);
  assert.match(plan.reason, /1\.65–2\.4 µm and 2\.4–3\.8 µm images, which are not in this view/);
  const full = fixture('synthetic-fast-mover');
  const spx = full.frames.find((f) => f.mission === 'SPHEREx');
  const broken = falseColourPlan(passFrames(full.frames, spx.mjd), (f) => f.band !== 'spx-b4');
  assert.equal(broken.ok, false);
  assert.match(broken.reason, /did not load/);
});

test('false colour URL flag round-trips and is off by default', () => {
  assert.equal(parseState('?target=x').fc, false);
  const s = parseState('?target=x&fc=1');
  assert.equal(s.fc, true);
  assert.equal(serializeState(s), '?target=x&fc=1');
  assert.equal(parseState('?target=x&fc=yes').fc, false);
  assert.equal(serializeState(parseState('?fc=1')), '');
});
