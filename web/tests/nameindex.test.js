import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { normaliseName, shortDesignation, buildIndex, searchNames } from '../js/nameindex.js';

const raw = JSON.parse(readFileSync(new URL('../data/names.json', import.meta.url)));
const index = buildIndex(raw);
const top = (q) => searchNames(index, q)[0]?.entry;

test('the index file records its source and date', () => {
  assert.match(raw.source, /SIMBAD/);
  assert.match(raw.generated, /^\d{4}-\d{2}-\d{2}$/);
  assert.equal(raw.generator, 'tools/build_name_index.py');
  assert.ok(index.length >= 40);
});

test('names are normalised the way people type them', () => {
  assert.equal(normaliseName("NAME Barnard's Star"), 'barnards star');
  assert.equal(normaliseName('* eps Ind B'), 'eps ind b');
  assert.equal(normaliseName('Epsilon Indi B'), 'eps ind b');
  assert.equal(normaliseName('Gliese 699'), 'gj 699');
  assert.equal(normaliseName('Gl 699'), 'gj 699');
  assert.equal(normaliseName('WISE J085510.83-071442.5'), 'wise 085510.83-071442.5');
  assert.equal(normaliseName('  2MASS   J0415 '), '2mass 0415');
});

test('long designations get their short form', () => {
  assert.equal(shortDesignation('WISE J085510.83-071442.5'), 'wise 0855-0714');
  assert.equal(shortDesignation('2MASS J04151954-0935066'), '2mass 0415-0935');
  assert.equal(shortDesignation('GJ 699'), null);
});

test('the brief and common queries find the right object', () => {
  assert.equal(top('barn').slug, 'barnards-star');
  assert.equal(top('eps ind').slug, 'epsilon-indi-b');
  assert.equal(top('Epsilon Indi B').slug, 'epsilon-indi-b');
  assert.equal(top('WISE 0855').slug, 'wise-0855-0714');
  assert.equal(top('wise0855').slug, 'wise-0855-0714');
  assert.equal(top('Luhman').label, 'Luhman 16AB');
  assert.equal(top('HD 209100').label, 'Epsilon Indi A');
  assert.equal(top('Gl 699').slug, 'barnards-star');
  assert.equal(top('2MASS J0415').slug, '2mass-0415-0935');
  assert.equal(top('rw aur').slug, 'rw-aurigae');
  assert.equal(top('R Draconis').slug, 'r-draconis');
  assert.equal(top('haumea').slug, 'haumea');
  assert.equal(top('proxima').label, 'Proxima Centauri');
});

test('gallery views rank before live ones on a tie, and each object appears once', () => {
  const hits = searchNames(index, 'eps');
  assert.ok(hits.length > 1);
  assert.equal(hits[0].entry.slug, 'epsilon-indi-b');
  assert.equal(new Set(hits.map((h) => h.entry)).size, hits.length);
});

test('a hit says which name matched when it is not the label', () => {
  const h = searchNames(index, 'Gl 699')[0];
  assert.match(h.alias, /^Gl(iese)? 699$/);
  assert.equal(searchNames(index, 'barn')[0].alias, null);
});

test('short or unknown queries give nothing', () => {
  assert.deepEqual(searchNames(index, 'b'), []);
  assert.deepEqual(searchNames(index, 'zzzz qqqq'), []);
  assert.deepEqual(searchNames(index, ''), []);
});

test('bad entries are dropped, not thrown', () => {
  const built = buildIndex({ entries: [{ label: 'x' }, { label: 'Good', names: ['Good'], ra: 10, dec: 5, slug: null }, null] });
  assert.equal(built.length, 1);
  assert.deepEqual(buildIndex(null), []);
});

test('an entry opens its gallery view only when the gallery has it, else a live view with its motion', async () => {
  const { entryHref } = await import('../js/suggest.js');
  const barnard = top('barn');
  assert.equal(entryHref(barnard, new Set(['barnards-star'])), '?target=barnards-star');
  const live = entryHref(barnard, new Set());
  assert.match(live, /^\?ra=269\.45\d*&dec=4\.69\d*&pmra=-801\.551&pmdec=10362\.394&epoch=2000&fov=240&label=Barnard%27s\+Star$/);
  assert.equal(entryHref(top('haumea'), new Set()), null);
});

test("a typed position on a gallery target's 2010-2027 path finds that target", async () => {
  const { nearGallery } = await import('../js/nameindex.js');
  const slugs = new Set(['wise-0855-0714', 'barnards-star']);
  // The brief's position (WISE era) and our manifest's 2015.4 position, about 40 arcsec apart.
  for (const [ra, dec] of [[133.7951292, -7.2451472], [133.783924, -7.2443404], [133.7951, -7.2451]]) {
    const hit = nearGallery(index, ra, dec, slugs);
    assert.equal(hit?.entry.slug, 'wise-0855-0714', `${ra} ${dec}`);
    assert.ok(hit.arcsec < 10);
  }
  // Barnard's Star in 2026, after 16 years of 10 arcsec a year.
  assert.equal(nearGallery(index, 269.4463, 4.7682, slugs)?.entry.slug, 'barnards-star');
  assert.equal(nearGallery(index, 133.83, -7.245, slugs), null); // 40 arcsec off the path
  assert.equal(nearGallery(index, 133.7951, -7.2451, new Set()), null); // not built here
});

test('the input is not changed', () => {
  const copy = JSON.stringify(raw);
  searchNames(buildIndex(raw), 'barn');
  assert.equal(JSON.stringify(raw), copy);
});
