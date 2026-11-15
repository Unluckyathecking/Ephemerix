import { test } from 'node:test';
import assert from 'node:assert/strict';
import { runLive, LiveError, describe } from '../js/live.js';

const VIEW = new URL('https://api.example.org/api/view?ra=1&dec=2');

function res(status, body, { url = '', headers = {} } = {}) {
  return { status, ok: status >= 200 && status < 300, url,
    headers: { get: (k) => headers[k] ?? null },
    json: async () => { if (body === undefined) throw new SyntaxError('bad'); return body; } };
}

/** fetch that answers from a queue of responses (or throws Errors), recording URLs. */
function scripted(answers) {
  const calls = [];
  const impl = async (url) => {
    calls.push(String(url));
    const next = answers.shift();
    if (next instanceof Error) throw next;
    return next;
  };
  return { impl, calls };
}

const noSleep = async () => {};

test('cached view: 200 returns the manifest and the response URL', async () => {
  const m = { schema: 1 };
  const { impl } = scripted([res(200, m, { url: VIEW.href })]);
  const out = await runLive({ viewUrl: VIEW, fetchImpl: impl, sleep: noSleep });
  assert.deepEqual(out.manifest, m);
  assert.equal(out.url.href, VIEW.href);
});

test('202 polls the job against the API origin until done', async () => {
  const updates = [];
  const { impl, calls } = scripted([
    res(202, { job: 'abc', status_url: '/api/jobs/abc' }, { url: VIEW.href }),
    res(200, { state: 'queued', stage: 'Waiting for a free worker', progress: 0, queue_position: 2 }),
    res(200, { state: 'running', stage: 'Searching WISE frames', progress: 0.35 }),
    res(200, { state: 'done', progress: 1, manifest_url: '/api/views/k/manifest.json' }),
  ]);
  const out = await runLive({ viewUrl: VIEW, fetchImpl: impl, sleep: noSleep, onUpdate: (s) => updates.push(s) });
  assert.equal(out.manifestUrl.href, 'https://api.example.org/api/views/k/manifest.json');
  assert.deepEqual(calls.slice(1), Array(3).fill('https://api.example.org/api/jobs/abc'));
  assert.deepEqual(updates.map((u) => u.stage).slice(1), ['Waiting for a free worker', 'Searching WISE frames']);
  assert.equal(describe(updates[1]), 'Waiting for a free worker (number 2 in line).');
  assert.equal(describe(updates[2]), 'Searching WISE frames');
});

test('a failed job reports the server message', async () => {
  const { impl } = scripted([
    res(202, { job: 'a', status_url: '/api/jobs/a' }),
    res(200, { state: 'error', error: 'No WISE or SPHEREx images could be found for this position.' }),
  ]);
  await assert.rejects(runLive({ viewUrl: VIEW, fetchImpl: impl, sleep: noSleep }),
    (e) => e instanceof LiveError && e.message.startsWith('No WISE or SPHEREx images'));
});

test('429 and 503 carry the wait time from Retry-After', async () => {
  for (const status of [429, 503]) {
    const { impl } = scripted([res(status, { error: 'Busy.', retry_after_s: 99 }, { headers: { 'Retry-After': '42' } })]);
    await assert.rejects(runLive({ viewUrl: VIEW, fetchImpl: impl, sleep: noSleep }),
      (e) => e instanceof LiveError && e.retryAfter === 42 && e.message === 'Busy. Try again in about 42 s.');
  }
  const { impl } = scripted([res(503, { error: 'Busy.', retry_after_s: 30 })]);
  await assert.rejects(runLive({ viewUrl: VIEW, fetchImpl: impl, sleep: noSleep }), (e) => e.retryAfter === 30);
});

test('no live server, or a failing one, is said in words, never as an HTTP code', async () => {
  for (const [status, want] of [[404, /^This copy of the site shows the built views only/], [500, /^The live server is not answering right now/]]) {
    const { impl } = scripted([res(status, null)]);
    await assert.rejects(runLive({ viewUrl: VIEW, fetchImpl: impl, sleep: noSleep }),
      (e) => e instanceof LiveError && want.test(e.message) && !/HTTP/.test(e.message));
  }
});

test('422 shows the validation message', async () => {
  const { impl } = scripted([res(422, { error: "'dec' must be between -90 and 90 degrees; got -91." })]);
  await assert.rejects(runLive({ viewUrl: VIEW, fetchImpl: impl, sleep: noSleep }), /'dec' must be between/);
});

test('transient poll failures are tolerated, persistent ones give up', async () => {
  const ok = scripted([
    res(202, { job: 'a', status_url: '/api/jobs/a' }),
    new TypeError('network'), res(502, undefined),
    res(200, { state: 'done', manifest_url: '/api/views/k/manifest.json' }),
  ]);
  assert.ok((await runLive({ viewUrl: VIEW, fetchImpl: ok.impl, sleep: noSleep })).manifestUrl);
  const bad = scripted([res(202, { job: 'a', status_url: '/api/jobs/a' }), new TypeError('x'), new TypeError('x'), new TypeError('x')]);
  await assert.rejects(runLive({ viewUrl: VIEW, fetchImpl: bad.impl, sleep: noSleep }), /could not be reached/);
});

test('an unknown job (server restarted) stops polling with its message', async () => {
  const { impl } = scripted([res(202, { job: 'a', status_url: '/api/jobs/a' }), res(404, { error: 'That job is not known.' })]);
  await assert.rejects(runLive({ viewUrl: VIEW, fetchImpl: impl, sleep: noSleep }), /not known/);
});

test('unreachable server and cancel', async () => {
  const down = scripted([new TypeError('Failed to fetch')]);
  await assert.rejects(runLive({ viewUrl: VIEW, fetchImpl: down.impl, sleep: noSleep }), /could not be reached/);
  const ctrl = new AbortController();
  const { impl } = scripted([res(202, { job: 'a', status_url: '/api/jobs/a' })]);
  const sleep = async () => { ctrl.abort(); throw new DOMException('Aborted', 'AbortError'); };
  await assert.rejects(runLive({ viewUrl: VIEW, fetchImpl: impl, sleep, signal: ctrl.signal }), (e) => e.name === 'AbortError');
});
