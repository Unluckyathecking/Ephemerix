import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { apiBaseFor } from '../js/config.js';

const ROOT = new URL('..', import.meta.url).pathname;

test('production hosts always use the same-origin API', () => {
  assert.equal(apiBaseFor('example.org'), '/');
  assert.equal(apiBaseFor('example.org', '?api=https://evil.example'), '/');
  assert.equal(apiBaseFor('localhost.evil.com', '?api=http://localhost:8000'), '/');
});

test('?api= overrides only on localhost, only for http(s) origins', () => {
  assert.equal(apiBaseFor('localhost', '?api=http://localhost:8000/x'), 'http://localhost:8000');
  assert.equal(apiBaseFor('127.0.0.1', '?api=https://api.example.org'), 'https://api.example.org');
  assert.equal(apiBaseFor('localhost', '?api=javascript:alert(1)'), '/');
  assert.equal(apiBaseFor('localhost', '?api=nonsense'), '/');
  assert.equal(apiBaseFor('localhost', ''), '/');
});

function files(dir) {
  return readdirSync(dir).flatMap((n) => {
    const p = join(dir, n);
    if (n === 'node_modules') return [];
    return statSync(p).isDirectory() ? files(p) : [p];
  });
}

test('the Modal host appears nowhere under web/, vercel.json included', () => {
  const all = files(ROOT);
  assert.ok(all.some((p) => p.endsWith('/vercel.json')) && all.some((p) => p.endsWith('/middleware.js')));
  const bad = all
    .filter((p) => !/\.(png|jpe?g|webp|woff2?)$/.test(p))
    .filter((p) => readFileSync(p, 'utf8').includes(['modal', 'run'].join('.')));
  assert.deepEqual(bad, []);
});

test('no page CSP names an external origin', () => {
  for (const f of ['index.html', 'validation.html', 'search.html', 'planetx.html']) {
    const csp = readFileSync(join(ROOT, f), 'utf8').match(/Content-Security-Policy" content="([^"]*)"/)[1];
    assert.doesNotMatch(csp, /https?:\/\//, f);
  }
});
