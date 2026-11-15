// Live-server client: ask /api/view for a position, then poll the build job until the
// manifest is ready. Pure apart from the injected fetch and sleep, so it is unit-tested.

export class LiveError extends Error {
  /** @param {string} message  safe to show  @param {number|null} [retryAfter]  seconds */
  constructor(message, retryAfter = null) {
    super(message);
    this.name = 'LiveError';
    this.retryAfter = retryAfter;
  }
}

const UNREACHABLE = 'The live server could not be reached. Check your connection, or try again later.';

/** Sleep that rejects with an AbortError when `signal` aborts. */
export function abortableSleep(ms, signal) {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(new DOMException('Aborted', 'AbortError'));
    const t = setTimeout(resolve, ms);
    signal?.addEventListener('abort', () => { clearTimeout(t); reject(new DOMException('Aborted', 'AbortError')); }, { once: true });
  });
}

async function body(res) {
  try { return await res.json(); } catch { return null; }
}

function retryAfter(res, b) {
  const h = Number(res.headers?.get?.('Retry-After'));
  if (Number.isFinite(h) && h > 0) return Math.ceil(h);
  const s = Number(b?.retry_after_s);
  return Number.isFinite(s) && s > 0 ? Math.ceil(s) : null;
}

async function request(fetchImpl, url, signal) {
  try {
    return await fetchImpl(url, { signal, headers: { Accept: 'application/json' } });
  } catch (err) {
    if (err?.name === 'AbortError') throw err;
    return null;
  }
}

/** Turn a non-2xx answer into a readable LiveError. */
async function failure(res) {
  const b = await body(res);
  const wait = retryAfter(res, b);
  if (res.status === 429 || res.status === 503) {
    const base = typeof b?.error === 'string' ? b.error : 'The live server is busy.';
    return new LiveError(wait ? `${base} Try again in about ${wait} s.` : base, wait);
  }
  if (typeof b?.error === 'string') return new LiveError(b.error);
  // A visitor never sees an HTTP code: no /api here means a copy without the live server.
  if ([404, 405, 501].includes(res.status)) return new LiveError('This copy of the site shows the built views only, so it cannot build a view of a new position. Try one of the gallery objects below.');
  return new LiveError('The live server is not answering right now. Try again in a minute, or open one of the gallery objects below.');
}

/**
 * Run one live lookup.
 * @param {{viewUrl: URL, fetchImpl?: Function, sleep?: Function, onUpdate?: Function,
 *          signal?: AbortSignal, pollMs?: number, maxPollFailures?: number}} opts
 * @returns {Promise<{manifest: object, url: URL} | {manifestUrl: URL}>}
 *   the manifest itself when the view was cached, else the URL of the finished manifest.
 */
export async function runLive({ viewUrl, fetchImpl = fetch, sleep = abortableSleep, onUpdate = () => {},
  signal, pollMs = 1000, maxPollFailures = 3 }) {
  const res = await request(fetchImpl, viewUrl, signal);
  if (!res) throw new LiveError(UNREACHABLE);
  const url = new URL(res.url || viewUrl);
  if (res.status === 200) {
    const manifest = await body(res);
    if (!manifest) throw new LiveError('The live server sent data that is not valid JSON.');
    return { manifest, url };
  }
  if (res.status !== 202) throw await failure(res);
  const job = await body(res);
  if (typeof job?.status_url !== 'string') throw new LiveError('The live server sent an unexpected answer.');
  const statusUrl = new URL(job.status_url, url);
  onUpdate({ state: 'queued', stage: 'Waiting for a free worker', progress: 0, queue_position: null });
  return poll({ statusUrl, fetchImpl, sleep, onUpdate, signal, pollMs, maxPollFailures });
}

async function poll({ statusUrl, fetchImpl, sleep, onUpdate, signal, pollMs, maxPollFailures }) {
  let failures = 0;
  for (;;) {
    await sleep(pollMs, signal);
    const res = await request(fetchImpl, statusUrl, signal);
    const status = res && res.ok ? await body(res) : null;
    if (res && res.status === 404) throw await failure(res);
    if (!status) {
      failures += 1;
      if (failures >= maxPollFailures) throw new LiveError(UNREACHABLE);
      continue;
    }
    failures = 0;
    if (status.state === 'done' && typeof status.manifest_url === 'string') {
      return { manifestUrl: new URL(status.manifest_url, statusUrl) };
    }
    if (status.state === 'error') throw new LiveError(status.error || 'The view could not be built.');
    onUpdate(status);
  }
}

/** One line for the user from a job status. */
export function describe(status) {
  if (status.state === 'queued' && status.queue_position) {
    return `Waiting for a free worker (number ${status.queue_position} in line).`;
  }
  return status.stage || 'Working…';
}
