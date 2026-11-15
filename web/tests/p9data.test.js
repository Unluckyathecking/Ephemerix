// The pilot search of the predicted Planet Nine region: words and numbers from p9-search.json.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { p9Problem, p9Statement, p9Pretty, p9Stats, p9ReachRows, p9PopulationText, p9Peaks, p9PeaksText, p9PeakHead, share } from '../js/p9data.js';

const D = {
  schema: 1,
  statement: 'Over 3.6 deg^2 (32 fields of 20 arcmin), no moving source brighter than 329 uJy at 1 um (V ~ 18.0) at 30-1000 au.',
  n_fields: 3, tile_arcmin: 20, area_deg2: 0.3333,
  pooled: { flux50_ujy: 120.99, flux90_ujy: 329.49, vmag50: 19.04, vmag90: 17.95 },
  pooled_snr7: { flux50_ujy: 76.1, flux90_ujy: 135.7 },
  fields: [{ name: 'A', flux90_ujy: 116.2 }, { name: 'B', flux90_ujy: null }, { name: 'C', flux90_ujy: 210 }],
  peaks: { fields_with_real_peak_above_null_max: 2, note: 'Real and null searches are alike.' },
  planetx_reach: {
    at_pooled_flux50: [{ key: 'se5', label: 'Super-Earth, 5 Earth masses', reach_lo_au: 225, reach_nom_au: 325, reach_hi_au: 450 }],
    at_pooled_flux90: [{ key: 'se5', label: 'Super-Earth, 5 Earth masses', reach_lo_au: null, reach_nom_au: 250, reach_hi_au: 350 }],
  },
  population: { fraction_of_population_in_fields: 0.000808, expected_fraction_excluded: 0.000091, expected_fraction_excluded_not_already_excluded_by_ztf_des_ps1: 5.56e-9 },
  unexplained_or_vetted_peaks_above_null_max: [
    { field: 'A', label: 'unvetted candidate', ra: 351.67132, dec: -16.87419, snr: 7.0624, flux_ujy: 56.39, flux_err_ujy: 7.98,
      assessment: { verdict: 'unexplained peak', why: 'Most likely noise. Flux 56 +- 8 uJy at S/N >= 7; implies 30-37 au. Not followed up in another pass.' } },
    { field: 'B', label: 'fails half-pass consistency', assessment: { verdict: 'artefact: bright-star residual', why: 'x' } },
    { field: 'B', label: 'unvetted candidate', assessment: { verdict: 'possible variable star or noise', why: 'y' } },
  ],
};

test('a file the section cannot draw is rejected with a reason', () => {
  assert.equal(p9Problem(D), null);
  assert.equal(p9Problem(null), 'unknown version');
  assert.equal(p9Problem({ ...D, schema: 2 }), 'unknown version');
  assert.equal(p9Problem({ ...D, pooled: { flux50_ujy: 1 } }), 'no pooled limits');
  assert.equal(p9Problem({ ...D, fields: null }), 'incomplete');
});

test('the statement is the report’s own, with units set properly and no word changed', () => {
  assert.equal(p9Statement(D), 'Over 3.6 deg² (32 fields of 20′), no moving source brighter than 329 µJy at 1 µm (V ≈ 18.0) at 30–1000 au.');
  assert.equal(p9Pretty('56 +- 8 uJy at S/N >= 7'), '56 ± 8 µJy at S/N ≥ 7');
  assert.equal(p9Pretty(null), '');
});

test('the limits shown are the ones above the null maximum, never the S/N 7 sensitivity', () => {
  const stats = p9Stats(D);
  assert.deepEqual(stats.map((s) => s.value), ['0.3 deg²', '121 µJy', '329 µJy', '2 of 3']);
  assert.equal(stats[1].sub, 'V 19.0 for a sunlit body');
  assert.ok(!JSON.stringify(stats).includes('76') && !JSON.stringify(stats).includes('136'));
});

test('reach rows: dark / most likely / bright, and "< 200" where the dark end falls short', () => {
  assert.deepEqual(p9ReachRows(D), [{ label: 'Super-Earth, 5 Earth masses', at50: '225 / 325 / 450 au', at90: '< 200 / 250 / 350 au' }]);
  assert.deepEqual(p9ReachRows({}), []);
});

test('population fractions: a percentage to one figure, or a power of ten when tiny', () => {
  assert.equal(share(0.000808), '0.08%');
  assert.equal(share(0.000091), '0.009%');
  assert.equal(share(5.56e-9), '6 × 10⁻⁹');
  assert.equal(share(0), null);
  assert.match(p9PopulationText(D), /hold an expected 0\.08% .* exclude an expected 0\.009% .* essentially none \(6 × 10⁻⁹\)\.$/);
  assert.equal(p9PopulationText({}), null);
});

test('peaks: counted by the report’s judgement; the pipeline’s "candidate" label is never used', () => {
  const p = p9Peaks(D);
  assert.equal(p.total, 3);
  assert.equal(p.unexplained.length, 1);
  assert.deepEqual(p.groups, [{ what: 'artefacts', n: 1 }, { what: 'possible variable stars or noise', n: 1 }]);
  const text = p9PeaksText(D);
  assert.equal(text, '3 peaks rose above their own field’s null maximum in 2 of the 3 fields. 2 of them are accounted for (1 artefacts, 1 possible variable stars or noise), and 1 is not.');
  assert.ok(!/candidate/i.test(text + p9PeakHead(p.unexplained[0])));
  assert.equal(p9PeakHead(p.unexplained[0]), 'Field A, RA 351.6713°, Dec −16.8742°, S/N 7.06, 56 ± 8 µJy');
  assert.equal(p9PeaksText({ ...D, unexplained_or_vetted_peaks_above_null_max: [] }), 'No peak rose above its field’s null maximum.');
});

test('the shipped file has what the section needs', () => {
  const d = JSON.parse(readFileSync(new URL('../data/p9-search.json', import.meta.url)));
  assert.equal(p9Problem(d), null);
  assert.equal(p9Stats(d).length, 4);
  assert.ok(p9ReachRows(d).length > 0);
  for (const u of p9Peaks(d).unexplained) assert.ok(u.assessment.why.length > 0);
});
