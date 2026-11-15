import { test } from 'node:test';
import assert from 'node:assert/strict';
import { normaliseMode, resolveMode, searchWithMode, shouldHint } from '../js/mode.js';

test('mode names: simple, advanced, and full as an alias of advanced', () => {
  assert.equal(normaliseMode('simple'), 'simple');
  assert.equal(normaliseMode('advanced'), 'advanced');
  assert.equal(normaliseMode('full'), 'advanced');
  assert.equal(normaliseMode('nonsense'), null);
  assert.equal(normaliseMode(null), null);
});

test('Advanced is the default; the URL beats the stored choice', () => {
  assert.equal(resolveMode(null, null), 'advanced');
  assert.equal(resolveMode(null, 'simple'), 'simple');
  assert.equal(resolveMode('full', 'simple'), 'advanced');
  assert.equal(resolveMode('advanced', 'simple'), 'advanced');
  assert.equal(resolveMode('simple', 'advanced'), 'simple');
  assert.equal(resolveMode('junk', 'junk'), 'advanced');
});

test('the URL carries mode=simple only, and keeps every other parameter', () => {
  assert.equal(searchWithMode('?target=x&frame=a', 'simple'), '?target=x&frame=a&mode=simple');
  assert.equal(searchWithMode('?target=x&mode=simple', 'advanced'), '?target=x');
  assert.equal(searchWithMode('?mode=full&target=x', 'advanced'), '?target=x');
  assert.equal(searchWithMode('', 'simple'), '?mode=simple');
  assert.equal(searchWithMode('?mode=simple', 'advanced'), '');
});

test('the hint shows once, to someone who has not chosen', () => {
  assert.equal(shouldHint({ stored: null, hinted: false }), true);
  assert.equal(shouldHint({ stored: 'simple', hinted: false }), false);
  assert.equal(shouldHint({ stored: 'advanced', hinted: false }), false);
  assert.equal(shouldHint({ stored: null, hinted: true }), false);
});
