import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  VARIABLE_SLUGS, foldPhase, monthYear, mjdToIso, variabilityProblem, summarySentences, limitSentence,
  seriesTraces, findingsList, binMedians, axisText, AVERAGE_LABEL, shortFinding, plainLimit, keyItems, markNote, yView, clippedNote,
} from '../js/variabilitytext.js';

const data = JSON.parse(readFileSync(new URL('../data/variability.json', import.meta.url)));

test('only the two variable stars get a block', () => {
  assert.deepEqual([...VARIABLE_SLUGS].sort(), ['r-draconis', 'rw-aurigae']);
});

test('fold puts the catalogue maximum at phase 0 and wraps into [0, 1)', () => {
  assert.equal(foldPhase(100, 200, 100), 0);
  assert.equal(foldPhase(150, 200, 100), 0.25);
  assert.equal(foldPhase(50, 200, 100), 0.75);
  assert.ok(Math.abs(foldPhase(100 + 3 * 246.12, 246.12, 100)) < 1e-9);
});

test('dates come from MJD without a time zone shift', () => {
  assert.equal(mjdToIso(51544), '2000-01-01');
  assert.equal(mjdToIso(61275.8), '2026-08-23');
  assert.equal(monthYear('2025-09-11'), 'September 2025');
});

test('the shipped data has the shape the block needs', () => {
  assert.equal(variabilityProblem(data), null);
  assert.match(variabilityProblem({}), /stars/);
  assert.match(variabilityProblem({ stars: { 'r-draconis': { bands: [] } } }), /R Draconis|r-draconis/);
});

test('R Draconis: how much, over how long, when bright and faint, all from the data', () => {
  const [what, when] = summarySentences('r-draconis', data);
  assert.match(what, /about 1\.3 magnitudes/);
  assert.match(what, /0\.75 to 1\.1 µm/);
  assert.match(what, /0\.7 magnitudes/);
  assert.match(what, /246-day/);
  assert.match(when, /bright in August 2026/);
  assert.match(when, /faint in September 2025/);
  for (const s of [what, when, limitSentence('r-draconis')]) {
    assert.doesNotMatch(s, /—|–/, 'no dashes');
    assert.doesNotMatch(s, /the tool/i);
  }
  assert.match(limitSentence('r-draconis'), /relative/i);
  assert.match(limitSentence('r-draconis'), /saturat/);
});

test('RW Aurigae: the long-wave fade with its control, and an honest "cannot tell" for the rest', () => {
  const s = summarySentences('rw-aurigae', data).join(' ');
  assert.match(s, /3\.8 to 5\.0 µm/);
  assert.match(s, /factor of about 1\.[5-8]/);
  assert.match(s, /September 2025/);
  assert.match(s, /September 2026/);
  assert.match(s, /cannot tell/);
  assert.match(limitSentence('rw-aurigae'), /relative/i);
});

test('no sentences for a target without variability data', () => {
  assert.deepEqual(summarySentences('barnards-star', data), []);
  assert.deepEqual(summarySentences('r-draconis', null), []);
});

test('medians: exposures grouped into short runs, each with its spread and how many it stands for', () => {
  const rows = [[0, 1, 0.1, 0, ''], [1, 2, 0.1, 0, ''], [2, 3, 0.1, 0, ''], [30, 5, 0.1, 1, ''], [31, 5, 0.1, 1, ''], [32, 7, 0.1, 1, ''], [33, null, 0.1, 1, ''], [34, 9, 0.1, 1, 'flagged']];
  const m = binMedians(rows, { gap: 5, span: 15, minN: 3 });
  assert.equal(m.length, 2);
  assert.deepEqual([m[0].med, m[0].n, m[1].med, m[1].n], [2, 3, 5, 3], 'missing and flagged points left out');
  assert.ok(m[0].lo <= m[0].med && m[0].hi >= m[0].med);
  const long = Array.from({ length: 40 }, (_, i) => [i, 1, 0.1, 0, '']);
  assert.ok(binMedians(long, { gap: 5, span: 15, minN: 3 }).length >= 3, 'a long continuous pass is split');
  assert.equal(binMedians([[0, 1, 0, 0, ''], [1, 1, 0, 0, '']], { minN: 3 }).length, 0, 'fewer than minN: no mark');
});

test('R Draconis traces: medians are the main marks, single exposures faint and out of the legend, the comparison star kept', () => {
  const t = seriesTraces('r-draconis', data, { folded: false });
  const main = t.filter((x) => x.showlegend !== false);
  assert.ok(main.some((x) => /^R Draconis, 0\.75/.test(x.name)));
  assert.ok(main.some((x) => /^Comparison star/.test(x.name)));
  const star = main.find((x) => /^R Draconis, 0\.75/.test(x.name));
  assert.ok(star.x.length >= 6 && star.x.length < 60, `${star.x.length} medians`);
  assert.ok(star.customdata.every((c) => c[0] >= 3), 'each mark says how many exposures');
  assert.ok(star.error_y.array.length === star.x.length && star.error_y.arrayminus.length === star.x.length);
  assert.ok(typeof star.x[0] === 'string', 'dates on the time axis');
  const single = t.filter((x) => x.showlegend === false && /single exposures/.test(x.name));
  assert.ok(single.length >= 2 && single.every((x) => x.marker.opacity <= 0.3));
  const allMed = main.filter((x) => /^R Draconis/.test(x.name)).flatMap((x) => x.y);
  assert.ok(Math.max(...allMed) < 2.6, 'medians stay near the cycle the sentence describes');
  const f = seriesTraces('r-draconis', data, { folded: true });
  const fs = f.find((x) => /^R Draconis, 0\.75/.test(x.name) && x.showlegend !== false);
  assert.ok(fs.x.every((p) => p >= 0 && p < 2), 'two cycles shown');
  assert.equal(fs.x.length, 2 * star.x.length);
  assert.ok(f.some((x) => x.mode === 'lines'), 'the fitted cycle is drawn when folded');
});

test('RW Aurigae traces: one mark per visit with its exposure count, single exposures faint', () => {
  const rw = seriesTraces('rw-aurigae', data, { folded: false });
  const main = rw.filter((x) => x.showlegend !== false);
  assert.equal(main.length, 4, 'star and comparison star in both bands');
  assert.ok(main.every((x) => x.x.length === 3 && x.customdata.every((c) => c[0] >= 3)));
  assert.ok(main.some((x) => /^RW Aurigae/.test(x.name)) && main.some((x) => /^Comparison star/.test(x.name)));
  assert.ok(rw.filter((x) => x.showlegend === false).every((x) => x.marker.opacity <= 0.3));
  assert.deepEqual(seriesTraces('rw-aurigae', data, { folded: true }), [], 'no period to fold RW Aur on');
});

test('axes in plain words: brightness compared with its average, readable dates, the cycle', () => {
  const t = axisText(false);
  assert.equal(t.y, 'Brightness compared with its average');
  assert.equal(t.x, '');
  assert.equal(t.tickformat, '%b %Y');
  assert.equal(axisText(true, 246.12).x, 'Position in its 246-day cycle');
  assert.equal(AVERAGE_LABEL, '1 = average');
});

test('a one-line finding per star, about 20 words, plain, for the simple view and the results table', () => {
  for (const slug of ['r-draconis', 'rw-aurigae']) {
    const s = shortFinding(slug, data);
    const words = s.split(/\s+/).length;
    assert.ok(words >= 12 && words <= 24, `${slug}: ${words} words: ${s}`);
    assert.doesNotMatch(s, /µm|magnitude|—|–|relative|phase/i);
    assert.match(plainLimit(slug), /saturat|too bright/i);
  }
  assert.match(shortFinding('r-draconis', data), /246 days/);
  assert.match(shortFinding('r-draconis', data), /three/);
  assert.match(shortFinding('rw-aurigae', data), /September 2025/);
  assert.equal(shortFinding('barnards-star', data), '');
  assert.equal(shortFinding('r-draconis', null), '');
});

test('the y range fits the medians and their spread; single exposures above it are counted, not hidden silently', () => {
  for (const folded of [false, true]) {
    const t = seriesTraces('r-draconis', data, { folded });
    const { top, clipped } = yView(t);
    const meds = t.filter((x) => x.showlegend !== false);
    assert.ok(meds.every((x) => x.y.every((y, i) => y + x.error_y.array[i] <= top)));
    assert.ok(top % 0.5 === 0 && top >= 1.5);
    const singles = t.filter((x) => /single exposures/.test(x.name)).flatMap((x) => x.y);
    assert.equal(clipped, singles.filter((y) => y > top).length);
  }
  assert.match(clippedNote(3), /3 single exposures lie above the top of the chart/);
  assert.equal(clippedNote(0), '');
  assert.match(clippedNote(1), /1 single exposure lies/);
});

test('the key names every main mark and what one mark stands for', () => {
  const k = keyItems('r-draconis', data);
  assert.ok(k.some((x) => /R Draconis/.test(x.label)) && k.some((x) => /Comparison star/.test(x.label)));
  assert.ok(k.every((x) => x.colour));
  assert.match(markNote('r-draconis', data), /median of \d+ to \d+ exposures/);
  assert.match(markNote('rw-aurigae', data), /median of \d+ to \d+ exposures/);
});

test('findings list covers what held and what failed', () => {
  const items = findingsList(data).map((x) => x.join(' ')).join(' ');
  assert.match(items, /1\.65-2\.4 µm/);
  assert.match(items, /2\.4-3\.8 µm/);
  assert.match(items, /253/);
  assert.match(items, /246/);
  assert.match(items, /NEOWISE/);
  assert.match(items, /after seeing/i);
});
