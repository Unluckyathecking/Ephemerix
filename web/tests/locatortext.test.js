import { test } from 'node:test';
import assert from 'node:assert/strict';
import { galToEq, eqToEcl } from '../js/skymath.js';
import { galacticPhrase, scaleSentence, describePosition } from '../js/locatortext.js';

test('galactic latitude wording at the thresholds', () => {
  assert.equal(galacticPhrase(45).phrase, 'far from the Milky Way');
  assert.equal(galacticPhrase(-30.5).phrase, 'far from the Milky Way');
  assert.equal(galacticPhrase(30).phrase, 'at moderate galactic latitude');
  assert.equal(galacticPhrase(10).phrase, 'at moderate galactic latitude');
  assert.equal(galacticPhrase(9.9).crowded, true);
  assert.match(galacticPhrase(-2).phrase, /close to the Milky Way’s plane, so the field is crowded/);
});

test('scale cue compares the field with the full Moon', () => {
  assert.equal(scaleSentence(240), 'This image is 4 arcminutes across, about one eighth the width of the full Moon.');
  assert.match(scaleSentence(900), /15 arcminutes across, about half the width/);
  assert.match(scaleSentence(1860), /about the width of the full Moon/);
  assert.match(scaleSentence(3720), /62 arcminutes across, about 2 times the width/);
  assert.match(scaleSentence(60), /1 arcminute across, under a tenth/);
  assert.match(scaleSentence(150), /2\.5 arcminutes across/);
});

test('Barnard\'s Star: Ophiuchus, moderate latitude, not near the ecliptic', () => {
  const d = describePosition(269.4485, 4.7394, 240);
  assert.equal(d.constellation.name, 'Ophiuchus');
  assert.equal(d.galactic.phrase, 'at moderate galactic latitude');
  assert.equal(d.nearEcliptic, false);
  assert.ok(d.lines[0].includes('Ophiuchus') && d.lines[1].includes('+14.1°') && d.lines.length === 3);
  assert.ok(d.label.includes('Ophiuchus') && d.label.startsWith('Map of the whole sky'));
});

test('a field on the ecliptic and in the plane gets both notes', () => {
  // Walk along the galactic plane to where it comes closest to the ecliptic (near RA 6h, Dec +23).
  let best = null;
  for (let l = 0; l < 360; l += 0.5) {
    const e = galToEq(l, 0);
    const lat = Math.abs(eqToEcl(e.ra, e.dec).lat);
    if (!best || lat < best.lat) best = { lat, ...e };
  }
  const d = describePosition(best.ra, best.dec, 240);
  assert.equal(d.galactic.crowded, true);
  assert.equal(d.nearEcliptic, true);
  assert.ok(d.lines.some((l) => l.includes('near the ecliptic, where planets and asteroids pass')));
  assert.ok(d.lines.some((l) => l.includes('so the field is crowded')));
});

test('a far-from-the-plane field gets the "far" wording and negative signs use a real minus', () => {
  const d = describePosition(63.84, -9.58, 240);
  assert.match(d.lines[1], /^Galactic latitude −38\.9°: far from the Milky Way\.$/);
});
