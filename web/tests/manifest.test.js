import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, existsSync, readdirSync } from 'node:fs';
import { validateManifest, validateIndex, ManifestError } from '../js/manifest.js';

const raw = (slug) => JSON.parse(readFileSync(new URL(`./fixtures/gallery/${slug}/manifest.json`, import.meta.url)));

test('fixtures validate without problems', () => {
  for (const slug of ['synthetic-fast-mover', 'synthetic-no-motion']) {
    const { manifest, problems } = validateManifest(raw(slug));
    assert.deepEqual(problems, [], slug);
    assert.ok(manifest.frames.length > 0);
  }
});

test('the real Haumea manifest keeps its solar_system block; sky views have none', () => {
  const url = new URL('../gallery/haumea/manifest.json', import.meta.url);
  if (!existsSync(url)) return;
  const { manifest, problems } = validateManifest(JSON.parse(readFileSync(url)));
  assert.deepEqual(problems, []);
  assert.equal(manifest.solar_system.passes.length, 3);
  assert.ok(manifest.solar_system.reflectance.some((r) => r.spectrum_id === 'all-detected'));
  assert.ok(manifest.solar_system.body_frames.frames.length >= 6);
  assert.equal(validateManifest(raw('synthetic-fast-mover')).manifest.solar_system, null);
});

test('fixtures exercise the hard cases', () => {
  const a = validateManifest(raw('synthetic-fast-mover')).manifest;
  assert.ok(a.frames.some((f) => f.centroid_px === null));
  assert.ok(a.frames.some((f) => f.warnings.length));
  assert.ok(a.spectra.filter((s) => s.id !== 'spx-all').length >= 2);
  const b = validateManifest(raw('synthetic-no-motion')).manifest;
  assert.equal(b.match, null);
  assert.deepEqual(b.track, []);
  assert.equal(b.measured_motion, null);
  assert.ok(b.frames.every((f) => f.predicted_px === null));
});

test('fatal problems throw ManifestError', () => {
  assert.throws(() => validateManifest(null), ManifestError);
  assert.throws(() => validateManifest([]), ManifestError);
  assert.throws(() => validateManifest({ schema: 1, center: { ra: 1, dec: 2 }, size_px: 10, fov_arcsec: 10, frames: [] }), ManifestError);
  assert.throws(() => validateManifest({ ...raw('synthetic-fast-mover'), size_px: 'big' }), ManifestError);
});

test('malformed fields are cleaned, not trusted', () => {
  const m = raw('synthetic-fast-mover');
  m.frames[0] = { id: 'x' }; // unusable frame
  m.frames[1].centroid_px = ['a', 2];
  m.frames[2].warnings = 'oops';
  m.match = { verdict: 5 };
  m.overlays = null;
  m.warnings = [1, 'ok'];
  const { manifest, problems } = validateManifest(m);
  assert.equal(manifest.frames.length, m.frames.length - 1);
  assert.ok(manifest.frames.every((f) => Array.isArray(f.warnings)));
  assert.equal(manifest.match, null);
  assert.deepEqual(manifest.overlays, { gaia: [], catwise: [] });
  assert.deepEqual(manifest.warnings, ['ok']);
  assert.equal(problems.length, 2);
  assert.ok(manifest.frames.some((f) => f.centroid_px === null && f.centroid_err_arcsec === null));
});

test('index validation drops unsafe slugs', () => {
  const t = validateIndex({ targets: [{ slug: 'ok-1' }, { slug: '../x' }, null, { slug: 'b', manifest: 'b/m.json' }] });
  assert.deepEqual(t.map((x) => x.slug), ['ok-1', 'b']);
  assert.equal(t[0].manifest, 'ok-1/manifest.json');
});

test('the shipped gallery index is valid and lists no fixture', () => {
  const shipped = JSON.parse(readFileSync(new URL('../gallery/index.json', import.meta.url)));
  assert.equal(shipped.schema, 1);
  assert.ok(Array.isArray(shipped.targets));
  assert.equal(validateIndex(shipped).length, shipped.targets.length);
  assert.deepEqual(shipped.targets.filter((t) => /synthetic/i.test(JSON.stringify(t))), []);
});

test('an empty index validates to no targets', () => {
  assert.deepEqual(validateIndex({ schema: 1, targets: [] }), []);
  assert.deepEqual(validateIndex({ schema: 1 }), []);
});

test('no synthetic fixture can ship in the gallery or be deployed', () => {
  const ignore = readFileSync(new URL('../.vercelignore', import.meta.url), 'utf8').split('\n').map((l) => l.trim());
  assert.ok(ignore.includes('tests'), 'web/.vercelignore must exclude tests/, which holds the fixtures');
  assert.ok(existsSync(new URL('./fixtures/gallery/index.json', import.meta.url)));
  assert.deepEqual(readdirSync(new URL('../gallery/', import.meta.url)).filter((n) => n.startsWith('synthetic')), []);
});
