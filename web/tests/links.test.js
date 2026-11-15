import { test } from 'node:test';
import assert from 'node:assert/strict';
import { linkOuts } from '../js/links.js';

test('link-outs for WISE 0855 use the verified URL patterns', () => {
  const l = Object.fromEntries(linkOuts(133.7835555, -7.244052, 240).map((x) => [x.id, x.href]));
  assert.equal(l.aladin, 'https://aladin.cds.unistra.fr/AladinLite/?ra=133.783556&dec=-7.244052&fov=0.1333');
  assert.equal(l.wiseview, 'http://byw.tools/wiseview#ra=133.783556&dec=-7.244052&size=240');
  assert.equal(l['irsa-spherex'], 'https://irsa.ipac.caltech.edu/applications/spherex/?api=spectral-images&ra=133.783556&dec=-7.244052&spatialRegionOperation=contains_point&execute=true');
});

test('links carry only numbers built from RA/Dec', () => {
  for (const { href } of linkOuts(0, 89.5, 99999)) {
    assert.match(href, /^https?:\/\/[a-z.]+\//);
    assert.doesNotMatch(href, /[<>"' ]/);
  }
  assert.match(linkOuts(0, 0, 99999).find((x) => x.id === 'wiseview').href, /size=2000$/);
});

test('bad positions give no links', () => {
  assert.deepEqual(linkOuts(NaN, 0), []);
  assert.deepEqual(linkOuts(360, 0), []);
  assert.deepEqual(linkOuts(10, -91), []);
  assert.equal(linkOuts(10, 10, -5).length, 3);
});
