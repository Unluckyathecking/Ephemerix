import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { validateManifest } from '../js/manifest.js';
import { publishedSentence, motionPill, lookFor, scaleLine, spherexLabel, pickMover } from '../js/simplelook.js';

const read = (p) => JSON.parse(readFileSync(new URL(p, import.meta.url)));
const fixture = (slug) => validateManifest(read(`./fixtures/gallery/${slug}/manifest.json`)).manifest;
const real = (slug) => validateManifest(read(`../gallery/${slug}/manifest.json`)).manifest;
const fast = fixture('synthetic-fast-mover');
const variability = read('../data/variability.json');

test('every published type in the gallery reads as a natural sentence', () => {
  const want = {
    'M4 star': 'Astronomers list it as an M4 star.',
    'T1-1.5 + T6 (unresolved pair)': 'Its published type is T1-1.5 + T6 (unresolved pair).',
    'K1-K5 young star (T Tauri)': 'Astronomers list it as a K1-K5 young star (T Tauri).',
    'M4.5-M6 giant (Mira variable)': 'Astronomers list it as an M4.5-M6 giant (Mira variable).',
    'Dwarf planet, water ice': 'Astronomers list it as a dwarf planet with water ice.',
    T8: 'Its published type is T8.',
    'L1 (blue)': 'Its published type is L1 (blue).',
  };
  for (const [k, v] of Object.entries(want)) assert.equal(publishedSentence(k), v);
  for (const t of read('../gallery/index.json').targets) {
    const s = publishedSentence(t.known_type);
    assert.match(s, /^(Astronomers list it as (a|an) |Its published type is )\S.*\.$/, t.known_type);
    assert.doesNotMatch(s, / a [aeiou]| an [bcdgjkpqtvwyz][a-z]/i, s);
  }
  assert.equal(publishedSentence(null), '');
});

test('measured against catalogue, both numbers, at a glance', () => {
  const p = motionPill(fast);
  assert.match(p.text, /^Measured 2\.98 arcsec a year\. Catalogue 2\.95\. They agree\.$/);
  assert.equal(p.agree, true);
  const off = { ...fast, measured_motion: { ...fast.measured_motion, pmra_masyr: -1000, pmdec_masyr: 0, err_masyr: 10, err_pmra_masyr: 10, err_pmdec_masyr: 10 } };
  assert.match(motionPill(off).text, /They differ by more than our error allows\.$/);
  assert.equal(motionPill({ ...fast, measured_motion: null }), null);
  assert.equal(motionPill({ ...fast, target: { ...fast.target, pmra_masyr: null, pmdec_masyr: null } }), null);
});

test('what to look for: direction and size from the measured motion', () => {
  assert.match(lookFor(real('barnards-star')), /^Watch the ringed dot drift north, about 171 arcseconds in 16 years\.$/);
  assert.match(lookFor(real('wise-0855-0714')), /^Watch the ringed dot drift west/);
  assert.match(lookFor(real('epsilon-indi-b')), /^Watch the ringed dot drift south-east|^Watch the ringed dot drift east/);
});

test('what to look for: a variable star brightens and fades, from the variability data', () => {
  const r = lookFor(real('r-draconis'), { variability });
  assert.match(r, /^This one does not move: it brightens and fades/);
  assert.match(r, /246-day cycle/);
  assert.match(r, /SPHEREx only/);
  const w = lookFor(real('rw-aurigae'), { variability });
  assert.match(w, /^This one barely moves: SPHEREx saw it fade/);
  // Without the data, no claim about brightness.
  assert.doesNotMatch(lookFor(real('r-draconis')), /brighten|fade/);
});

test('what to look for: too faint for single images, not found, and bodies', () => {
  const faint = { ...fast, measured_motion: { ...fast.measured_motion, method: 'all_frames', n_frames: 12 } };
  assert.match(lookFor(faint), /too faint to see in single images/);
  const none = { ...fast, measured_motion: null, frames: fast.frames.map((f) => ({ ...f, centroid_px: null })) };
  assert.match(lookFor(none), /could not find it/);
  assert.match(lookFor(real('haumea')), /stars slide past/);
});

test('the patch against the full Moon', () => {
  assert.equal(scaleLine(240, 1), 'This patch of sky is 4 arcminutes across, about an eighth of the full Moon\'s width.');
  assert.equal(scaleLine(240, 2), 'This patch of sky is 2 arcminutes across, about a fifteenth of the full Moon\'s width.');
  assert.equal(scaleLine(900, 1), 'This patch of sky is 15 arcminutes across, about half the full Moon\'s width.');
  assert.equal(scaleLine(NaN, 1), '');
});

test('the video line says which of all the images it plays, so it never contradicts the full view', async () => {
  const { videoLine } = await import('../js/simplelook.js');
  const { activeFrames, defaultBands, presetBands } = await import('../js/framesets.js');
  const m = real('wise-0855-0714');
  const both = videoLine(activeFrames(m.frames, defaultBands(m.frames)), m.frames);
  assert.equal(both, 'This video plays 27 of all 68 images, the ones at one wavelength so they compare: 23 from WISE W2 (4.6 µm), 2010 to 2024, and 4 from SPHEREx 4.42–5.0 µm, 2025 to 2026.');
  const spx = videoLine(activeFrames(m.frames, presetBands(m.frames, 'spherex')), m.frames);
  assert.match(spx, /^This video plays 4 of all 68 images, the ones at one wavelength so they compare: 4 from SPHEREx 4\.42–5\.0 µm, 2025 to 2026\./);
  assert.match(spx, / We find the object in 3 of these 4 SPHEREx images; it is faint at this wavelength\.$/);
  const unseen = activeFrames(m.frames, presetBands(m.frames, 'spherex')).map((f) => ({ ...f, centroid_px: null }));
  assert.match(videoLine(unseen, m.frames), /It is too faint to see in these SPHEREx images; the ring marks where it should be\.$/);
  assert.doesNotMatch(both, /faint/);
});

test('the predicted track stops at the newest image, so no label runs past it', async () => {
  const { trackUntil } = await import('../js/overlays.js');
  const track = [2010, 2018, 2026, 2027].map((year) => ({ year, px: [0, 0] }));
  assert.deepEqual(trackUntil(track, 2026.34).map((t) => t.year), [2010, 2018, 2026]);
  assert.equal(trackUntil(track, null).length, 4);
});

test('SPHEREx only says how many images and over what dates', () => {
  assert.equal(spherexLabel([{ date: '2025-04-01' }, { date: '2026-09-25' }]), 'SPHEREx only: 2 images, 2025 to 2026');
  assert.equal(spherexLabel([{ date: '2025-04-01' }, { date: '2025-09-25' }]), 'SPHEREx only: 2 images, 2025');
});

test('show me something that moves: a clear mover, never a still or variable star', () => {
  const cands = [
    { entry: { slug: 'barnards-star', group: 'brief' }, manifest: real('barnards-star') },
    { entry: { slug: 'r-draconis', group: 'brief' }, manifest: real('r-draconis') },
    { entry: { slug: 'rw-aurigae', group: 'brief' }, manifest: real('rw-aurigae') },
    { entry: { slug: 'haumea', group: 'solar-system' }, manifest: real('haumea') },
  ];
  for (const r of [0, 0.5, 0.99]) assert.equal(pickMover(cands, () => r), 'barnards-star');
  assert.equal(pickMover([], () => 0), null);
});
