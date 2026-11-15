import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { readingText } from '../js/bodytext.js';
import { pretty, reflYRange, cleanSolarSystem, depthText, reflSpectra, passChoices, bodyFrames, iceSentence, planetXNote, bodyFacts, detectionNote, compositionIceNote } from '../js/bodytext.js';

const d = (label, over) => ({ label, wl_um: [1, 2], ratio: 0.4, err: 0.05, depth: 0.6, depth_min: null, saturated: false, sigma: 12, detected: true, ...over });
const HAUMEA = {
  shown_pass: 'spx-2025a',
  passes: [
    { id: 'spx-2025a', date_start: '2025-06-20T14:48:36Z', best_snr: 48.44, detected: true,
      bands: [{ band: 'spx-b1', flux_ujy: 572.56, err_ujy: 11.82, snr: 48.44 }],
      ephemeris: [{ mjd: 1, rate_arcsec_h: 2.0, r_au: 50.1, delta_au: 49.8, vmag: 17.3 }, { mjd: 2, rate_arcsec_h: 2.2, r_au: 50.3, delta_au: 49.9, vmag: 17.4 }, { mjd: 3, rate_arcsec_h: 2.4, r_au: 50.5, delta_au: 50.0, vmag: 17.5 }] },
    { id: 'spx-2026a', date_start: '2026-01-16T22:27:21Z', best_snr: 42.4, detected: true, bands: [], ephemeris: [] },
  ],
  reflectance: [
    { spectrum_id: 'spx-2025a', r_au: 50.3, points: [{ wl_um: 0.8, bw_um: 0.02, refl: 1.0, err: 0.07 }], band_depths: [], reading: 'r1' },
    { spectrum_id: 'all-detected', r_au: 50.3, points: [{ wl_um: 0.8, bw_um: 0.02, refl: 0.98, err: 0.03 }, { wl_um: 3.0, refl: -0.04, err: 0.05 }],
      band_depths: [
        d('1.5 um (H2O)', { depth: 0.358, err: 0.023 }), d('2.0 um (H2O)', { depth: 0.625, err: 0.03 }),
        d('2.3 um (CH4)', { depth: 0.387, err: 0.04 }),
        d('3.0 um (H2O)', { ratio: -0.04, err: 0.054, depth: null, depth_min: 0.911, saturated: true }),
      ], reading: 'SPHEREx sees absorption at ...' },
  ],
  body_frames: { size_px: 90, frames: [
    { id: 'spx-2025a-spx-b1-body', band: 'spx-b1', wavelength_um: [0.75, 1.1], image: 'body/a.png', n_exposures: 17 },
    { id: 'spx-2026a-spx-b1-body', band: 'spx-b1', wavelength_um: [0.75, 1.1], image: 'body/b.png', n_exposures: 16 },
  ] },
  sky_track_arcsec: 91.4,
};

test('absent or malformed block: no body mode', () => {
  assert.equal(cleanSolarSystem(undefined), null);
  assert.equal(cleanSolarSystem([]), null);
  assert.equal(cleanSolarSystem({ passes: 'x' }), null);
});

test('clean keeps passes, reflectance and frames with images, drops junk', () => {
  const ss = cleanSolarSystem({ ...HAUMEA, body_frames: { frames: [...HAUMEA.body_frames.frames, { id: 'x' }] }, reflectance: [...HAUMEA.reflectance, { spectrum_id: 7 }] });
  assert.equal(ss.passes.length, 2);
  assert.equal(ss.reflectance.length, 2);
  assert.equal(ss.body_frames.frames.length, 2);
  assert.equal(ss.shown_pass, 'spx-2025a');
});

test('depth text: measured, saturated, legacy over 100%, not significant, missing', () => {
  assert.equal(depthText(d('2.0', { depth: 0.625, err: 0.03 })), '63% ± 3%');
  assert.equal(depthText(d('3.0', { ratio: -0.04, err: 0.054, depth: null, depth_min: 0.911, saturated: true })), 'saturated: deeper than 91% (95% confidence)');
  // An older manifest without the saturated fields: 1.16 must never be shown.
  const legacy = depthText({ label: '3.0', ratio: -0.159, err: 0.106, depth: 1.159, sigma: 11, detected: true });
  assert.equal(legacy, 'saturated: deeper than 83% (95% confidence)');
  assert.equal(depthText(d('1.7', { depth: 0.08, err: 0.053, sigma: 1.5, detected: false })), '8% ± 5%, not significant');
  assert.equal(depthText(d('3.3', { ratio: null, depth: null, err: null })), 'no data in this window');
});

test('spectra for the plot: one per reflectance block, all passes first and labelled', () => {
  const s = reflSpectra(HAUMEA);
  assert.deepEqual(s.map((x) => x.id), ['all-detected', 'spx-2025a']);
  assert.equal(s[0].label, 'All detected passes');
  assert.equal(s[1].label, 'Pass of 2025-06-20');
  assert.deepEqual(s[0].points[0], { wl_um: 0.8, bw_um: 0.02, flux: 0.98, err: 0.03, flagged: false, detector: null });
  assert.equal(passChoices(HAUMEA)[0].id, 'all-detected');
});

test('body-centred frames for a pass; all passes use the shown pass', () => {
  assert.deepEqual(bodyFrames(HAUMEA, 'spx-2026a').map((f) => f.image), ['body/b.png']);
  assert.deepEqual(bodyFrames(HAUMEA, 'all-detected').map((f) => f.image), ['body/a.png']);
});

test('ice sentence names water ice from the 2.0 vs 2.3 µm pattern and the saturated 3 µm band', () => {
  const s = iceSentence('Haumea', HAUMEA.reflectance[1]);
  assert.match(s, /^SPHEREx sees Haumea’s water ice/);
  assert.match(s, /dips at 1\.5, 2\.0 and 2\.3 µm/);
  assert.match(s, /almost no light comes back at 3\.0 µm/);
  assert.doesNotMatch(s, /1\d\d%/);
});

test('ice sentence without a detection is plain about it', () => {
  const r = { band_depths: [d('2.0 um (H2O)', { depth: 0.05, err: 0.05, sigma: 1, detected: false })] };
  assert.equal(iceSentence('Eris', r), 'In this pass SPHEREx does not see a clear ice band on Eris; the light is reflected sunlight with no dip measured at 3 sigma.');
});

test('methane pattern', () => {
  const r = { band_depths: [d('2.0 um (H2O)', { depth: 0.2, err: 0.04 }), d('2.3 um (CH4)', { depth: 0.6, err: 0.04 })] };
  assert.match(iceSentence('Makemake', r), /^SPHEREx sees Makemake’s methane ice/);
});

test('Planet X note scales the measured S/N by distance to the fourth power', () => {
  const n = planetXNote('Haumea', HAUMEA);
  assert.match(n, /50 au/);
  assert.match(n, /1,300 times fainter at 300 au/);
  assert.match(n, /160,000 times at 1,000 au/);
  assert.match(n, /S\/N 48/);
  assert.match(n, /at the same noise would become S\/N 0\.04 at 300 au and 0\.0003 at 1,000 au\./);
  assert.doesNotMatch(n, /e-/);
  assert.match(n, /not a detection/);
});

test('the ice the published composition names, read from the composition text', () => {
  const rows = { reflectance: [{ band_depths: ['1.5 um (H2O)', '1.7 um (CH4; H2O 1.65)', '2.0 um (H2O)', '2.3 um (CH4)', '3.0 um (H2O)', '3.3 um (CH4; H2O wing)'].map((l) => d(l)) }] };
  const haumea = compositionIceNote('Haumea', { ...rows, composition: 'crystalline water ice with deep 1.5 and 2.0 um bands' });
  assert.match(haumea, /names water ice and not methane, so we read the dips in windows where water ice has a band as water ice; a dip at 2\.3 µm, where only methane ice has a band, is left unassigned\.$/);
  const makemake = compositionIceNote('Makemake', { ...rows, composition: 'methane ice dominates, with strong CH4 bands' });
  assert.match(makemake, /names methane ice and not water ice, so we read the dips in windows where methane ice has a band as methane ice; dips at 1\.5, 2\.0 and 3\.0 µm, where only water ice has a band, are left unassigned\.$/);
  assert.match(compositionIceNote('X', { composition: 'water ice' }), /has a band as water ice\.$/);
  assert.match(compositionIceNote('X', { composition: 'water and methane ice' }), /names both water and methane ice\.$/);
  assert.equal(compositionIceNote('X', { composition: 'tholins' }), '');
  assert.equal(compositionIceNote('X', {}), '');
});

test('facts from the shown pass ephemeris (medians)', () => {
  const f = bodyFacts(HAUMEA);
  assert.equal(f.rate, 2.2);
  assert.equal(f.r_au, 50.3);
  assert.equal(f.delta_au, 49.9);
  assert.equal(f.track, 91.4);
});

test('pretty: µm and ± in pipeline text', () => {
  assert.equal(pretty('band depths 0.36 +- 0.05 at 1.50 um; 1.5 um (H2O)'), 'band depths 0.36 ± 0.05 at 1.50 µm; 1.5 µm (H2O)');
  assert.equal(pretty(null), '');
});

test('methane pattern when the 2.3 µm band is saturated (Makemake, all passes)', () => {
  const r = { band_depths: [d('2.0 um (H2O)', { ratio: 0.858, depth: 0.142, err: 0.036 }), d('2.3 um (CH4)', { ratio: 0.04, err: 0.046, depth: null, depth_min: 0.884, saturated: true })] };
  const s = iceSentence('Makemake', r);
  assert.match(s, /^SPHEREx sees Makemake’s methane ice: its reflected sunlight dips at 2\.0 µm, and almost no light comes back at 2\.3 µm/);
});

test('reflectance y range comes from the points short of 3.8 µm', () => {
  const pts = [0.9, 1.0, 1.1, 0.5, 0.0].map((f, i) => ({ wl_um: 1 + 0.5 * i, flux: f })).concat([{ wl_um: 4.5, flux: 6 }, { wl_um: 4.6, flux: -5 }]);
  const [lo, hi] = reflYRange({ points: pts });
  assert.equal(lo, -0.2);
  assert.ok(hi >= 1.2 && hi < 1.4);
  assert.equal(reflYRange({ points: [] }), null);
});

test('detection note states the two-band rule and counts outcomes, older manifests by `detected`', () => {
  const ss = cleanSolarSystem({ passes: [
    { id: 'a', outcome: 'detected', detected: true }, { id: 'b', outcome: 'marginal', detected: false },
    { id: 'c', detected: false }, { id: 'd', detected: true },
  ] });
  assert.deepEqual(ss.passes.map((p) => p.outcome), ['detected', 'marginal', 'not detected', 'detected']);
  const t = detectionNote(ss);
  assert.match(t, /S\/N 5 or more in at least two detector bands/);
  assert.match(t, /2 of 4 passes are detected/);
  assert.match(t, /1 is marginal/);
  assert.doesNotMatch(detectionNote(cleanSolarSystem({ passes: [{ id: 'a', detected: true }] })), /marginal/);
});

test('the method text rounds each depth as the table does (Haumea 1.7 µm: 0.211 ± 0.035)', () => {
  const ss = cleanSolarSystem(JSON.parse(readFileSync(new URL('../gallery/haumea/manifest.json', import.meta.url))).solar_system);
  const s = readingText(ss.reflectance.find((r) => r.spectrum_id === 'all-detected'));
  assert.match(s, /1\.7 µm \(CH4; H2O 1\.65\) 21% ± 4%;/);
  assert.match(s, /\(depth against the 0\.75-1\.3 µm continuum\)\. Deep at 2\.0 µm/);
  assert.equal(readingText({ reading: 'No absorption band is detected.', band_depths: [] }), 'No absorption band is detected.');
});
