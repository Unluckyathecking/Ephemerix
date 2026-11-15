// Entry point: read the URL, load the right data, and render landing or view.
// Every failure ends in a readable message, never a blank page.

import { API_BASE, LIVE_TIMEOUT_MS } from './config.js';
import { el, $ } from './dom.js';
import { parseState, serializeState, viewKind, viewMode, apiQuery, bodyQuery } from './urlstate.js';
import { validateManifest, validateIndex, ManifestError } from './manifest.js';
import { preloadImages } from './player.js';
import { GAP_KEY } from './gaphatch.js';
import { factsSection } from './facts.js';
import { fieldMoversLine } from './fieldmovers.js';
import { renderLanding } from './gallery.js';
import { renderView } from './view.js';
import { renderSimple } from './simpleview.js';
import { MODE_EVENT, setMode, currentMode } from './mode.js';
import { runLive, describe, LiveError } from './live.js';
import { mountChrome } from './chrome.js';
import { variabilityBlock } from './variability.js';
import { pageTitle } from './site.js';
import { nameToSearch } from './nameopen.js';
import { loadNameIndex } from './suggest.js';

const main = $('#main');
const INDEX_URL = new URL('gallery/index.json', document.baseURI);
let state = parseState(window.location.search);

class LoadError extends Error {}

// Extra blocks for the simple view, each (manifest) => node or null, shown under the answer.
// The mount point for one more panel about an object (for example brightness over time).
const SIMPLE_EXTRAS = [(m) => variabilityBlock(m?.target?.slug), (m) => factsSection(m), (m) => fieldMoversLine(m)];

async function fetchJson(url, { signal } = {}) {
  let res;
  try {
    res = await fetch(url, { signal, headers: { Accept: 'application/json' } });
  } catch (err) {
    if (err.name === 'AbortError') throw err;
    throw new LoadError('The server could not be reached. Check your connection and try again.');
  }
  if (res.status === 404) throw new LoadError('That view was not found.');
  if (!res.ok) throw new LoadError(`The server answered with an error (HTTP ${res.status}).`);
  let body;
  try {
    body = await res.json();
  } catch {
    throw new LoadError('The server sent data that is not valid JSON.');
  }
  return { body, url: new URL(res.url || url, document.baseURI) };
}

async function loadManifest(url, opts) {
  const { body, url: finalUrl } = await fetchJson(url, opts);
  return { ...validateManifest(body), url: finalUrl };
}

async function loadIndex() {
  try {
    const { body } = await fetchJson(INDEX_URL);
    return { targets: validateIndex(body), error: null };
  } catch (err) {
    return { targets: null, error: err.message };
  }
}

function status(title, detail, extra = []) {
  const detailNode = el('p', { class: 'muted', text: detail });
  main.replaceChildren(el('section', { class: 'status card', role: 'status', 'aria-live': 'polite' }, [
    el('div', { class: 'spinner', 'aria-hidden': 'true' }), el('h1', { text: title }), detailNode, ...extra,
  ]));
  return detailNode;
}

function showError(title, message) {
  document.title = pageTitle(title);
  main.replaceChildren(el('section', { class: 'status card error', role: 'alert' }, [
    el('h1', { text: title }),
    el('p', { text: message }),
    el('p', {}, [el('a', { class: 'btn primary', href: './', text: 'Back to the gallery' })]),
  ]));
}

// Browsers rate-limit history updates, so writes are coalesced.
let urlTimer = null;
function setUrl(patch) {
  state = { ...state, ...patch };
  clearTimeout(urlTimer);
  urlTimer = setTimeout(() => {
    try {
      window.history.replaceState(window.history.state, '', serializeState(state) || window.location.pathname);
    } catch { /* throttled; the next write catches up */ }
  }, 250);
}

function href(patch) {
  const u = new URL(window.location.pathname, window.location.origin);
  u.search = serializeState({ ...state, ...patch });
  return u.href;
}

async function show(loaded, targets = null) {
  const { manifest: raw, problems, url } = loaded;
  // A position reached from a name shows that name (display only; the label is plain text).
  const manifest = state.label && !raw.target.name ? { ...raw, target: { ...raw.target, name: state.label } } : raw;
  const d = status('Loading images…', `0 of ${manifest.frames.length} images ready.`);
  const images = await preloadImages(manifest.frames, url, (n, total) => { d.textContent = `${n} of ${total} images ready.`; });
  // The no-data masks (docs/api.md `gaps_image`) ride in the same map; a missing one only loses its hatch.
  const masks = manifest.frames.filter((f) => f.gaps_image).map((f) => ({ id: GAP_KEY(f.id), image: f.gaps_image }));
  for (const [k, img] of await preloadImages(masks, url)) images.set(k, img);
  const missing = manifest.frames.filter((f) => !images.get(f.id)).length;
  const extra = missing ? [`${missing} image(s) could not be loaded and show as “Image missing”.`] : [];
  document.title = pageTitle(manifest.target.name || 'Sky position');
  const knownType = state.target ? (await Promise.resolve(targets).catch(() => null))?.find((t) => t.slug === state.target)?.known_type || null : null;
  let current = null;
  const render = (mode) => {
    current?.abort.abort();
    current?.player?.destroy();
    const abort = new AbortController();
    setUrl({ mode });
    const kind = manifest.solar_system ? 'Solar System body' : state.target ? 'Gallery target' : 'Position search';
    const shown = mode === 'simple'
      ? renderSimple(main, manifest, images, { knownType, kind, onFull: () => setMode('advanced'), link: () => href({ embed: false }), fullLink: () => href({ embed: false, mode: 'full' }), extras: SIMPLE_EXTRAS, signal: abort.signal, frame: state.frame })
      : renderView(main, manifest, images, { state, problems: [...problems, ...extra], setUrl, href, apiBase: API_BASE, targets, baseUrl: url, signal: abort.signal });
    current = { abort, player: shown?.player };
    backToMap(main.querySelector('.view-head'));
  };
  // The header switch (js/mode.js) changes the view in place and keeps the picture in view.
  window.addEventListener(MODE_EVENT, (e) => {
    render(e.detail.mode === 'simple' ? 'simple' : 'full');
    main.querySelector('canvas.stage')?.scrollIntoView({ block: 'nearest' });
  });
  render(viewMode(state, currentMode()));
}

async function openGallery(slug) {
  status('Opening view…', 'Reading the gallery.');
  const { targets } = await loadIndex();
  const entry = targets?.find((t) => t.slug === slug);
  const url = entry ? new URL(entry.manifest, INDEX_URL) : new URL(`gallery/${slug}/manifest.json`, document.baseURI);
  try {
    await show(await loadManifest(url), Promise.resolve(targets));
  } catch (err) {
    if (err instanceof ManifestError) showError('This view has a problem', `${err.message} The data for “${slug}” could not be shown.`);
    else showError('Could not open this view', `${err.message} (target “${slug}”)`);
  }
}

const LIVE_NOTES = {
  position: 'The server fetches WISE and SPHEREx images for this spot, measures the object and fits its spectrum. This usually takes one to two minutes; a view someone has already built opens at once.',
  body: 'The server asks JPL Horizons where the body was, finds every SPHEREx exposure that caught it, and measures it in each one. This can take several minutes; a body someone has already looked up today opens at once.',
};

function liveStatus(cancel, kind) {
  const elapsed = status('Building this view…', '', [
    el('p', { class: 'small muted', text: LIVE_NOTES[kind] || LIVE_NOTES.position }),
    cancel,
  ]);
  const stage = el('p', { class: 'live-stage', text: 'Contacting the live server…' });
  const bar = el('progress', { class: 'live-progress', max: '1', value: '0', 'aria-label': 'Build progress', style: 'width: 100%' });
  elapsed.before(stage, bar);
  return { elapsed, stage, bar };
}

async function openLive() {
  const ctrl = new AbortController();
  const started = Date.now();
  const cancel = el('button', { type: 'button', class: 'btn', text: 'Cancel', onClick: () => ctrl.abort() });
  const kind = viewKind(state);
  const ui = liveStatus(cancel, kind);
  const tick = () => { ui.elapsed.textContent = `Working for ${Math.round((Date.now() - started) / 1000)} s.`; };
  tick();
  const timer = setInterval(tick, 1000);
  const timeout = setTimeout(() => ctrl.abort(), LIVE_TIMEOUT_MS);
  const onUpdate = (s) => {
    ui.stage.textContent = describe(s);
    ui.bar.value = Math.max(0, Math.min(1, Number(s.progress) || 0));
  };
  try {
    const path = kind === 'body' ? `/api/body?${bodyQuery(state)}` : `/api/view?${apiQuery(state)}`;
    const viewUrl = new URL(`${API_BASE.replace(/\/+$/, '')}${path}`, document.baseURI);
    const result = await runLive({ viewUrl, onUpdate, signal: ctrl.signal });
    const loaded = result.manifestUrl
      ? await loadManifest(result.manifestUrl, { signal: ctrl.signal })
      : { ...validateManifest(result.manifest), url: result.url };
    clearInterval(timer);
    await show(loaded, loadIndex().then((r) => r.targets));
  } catch (err) {
    clearInterval(timer);
    if (err.name === 'AbortError') {
      const timedOut = Date.now() - started >= LIVE_TIMEOUT_MS - 50;
      showError(timedOut ? 'This took too long' : 'Cancelled', timedOut ? 'The server did not finish in time. Try again later, or pick a gallery target.' : 'The live view was cancelled.');
    } else if (err instanceof LiveError || err instanceof LoadError || err instanceof ManifestError) {
      await landing(/^(This copy|The live server is not)/.test(err.message) ? err.message : `This view could not be built: ${err.message}`);
    } else showError('Could not build this view', err.message);
  } finally {
    clearTimeout(timeout);
  }
}

async function landing(notice = null) {
  document.title = pageTitle();
  const { targets, error } = await loadIndex();
  const validation = fetchJson(new URL('data/validation.json', document.baseURI)).then((r) => r.body, () => null);
  renderLanding(main, { targets, indexUrl: INDEX_URL, indexError: error, notice, loadManifest, apiBase: API_BASE, validation,
    prefill: ['position', 'body'].includes(viewKind(state)) ? state : null });
  if (notice) backToMap(main.querySelector('.banner')?.parentElement);
}

async function route() {
  document.body.classList.toggle('embed', state.embed);
  const kindNow = viewKind(state);
  if (!document.querySelector('header.site .mode-switch')) mountChrome(kindNow === 'gallery' || kindNow === 'position' || kindNow === 'body' || kindNow === 'name' ? null : 'gallery');
  const kind = viewKind(state);
  if (kind === 'gallery') return openGallery(state.target);
  if (kind === 'position') {
    if (API_BASE) return openLive();
    return landing('This copy of the site has no live server, so only the gallery targets below can be opened. Your position is filled in below.');
  }
  if (kind === 'body') {
    if (API_BASE) return openLive();
    return landing('This copy of the site has no live server, so only the gallery targets below can be opened.');
  }
  if (kind === 'name') return openName(state.name);
  return landing();
}

/** ?name=: look the name up as the search box would, then become that view's URL. */
async function openName(name) {
  status(`Looking up “${name}”…`, 'Checking our list of named objects, then the name service.');
  const [index, { targets }] = await Promise.all([loadNameIndex(), loadIndex()]);
  const r = await nameToSearch(name, { index, slugs: new Set((targets || []).map((t) => t.slug)), apiBase: API_BASE, fallback: state.at });
  if (r.message) return landing(r.message);
  // Replace, not add: Back from the view goes straight to where the visitor came from (the map).
  const from = state.from;
  state = { ...parseState(r.search), from };
  window.history.replaceState(null, '', serializeState(state));
  return route();
}

const MAP_RETURN_KEY = 'ephemerix-map-return';

/** Where "Back to the sky map" goes: the map exactly as it was left, else its home view. */
function mapReturnHref() {
  try {
    const v = window.sessionStorage.getItem(MAP_RETURN_KEY);
    if (v && /^explore\.html(\?[\w.,%&=+-]*)?$/.test(v)) return v;
  } catch { /* storage blocked: the map's home view */ }
  return 'explore.html';
}

/** For a page reached from the sky map: a clear way back to it, as it was. */
function backToMap(host) {
  if (state.from !== 'map' || !host) return;
  host.prepend(el('a', { class: 'back-to-map', href: mapReturnHref(), text: '← Back to the sky map' }));
}

route().catch((err) => showError('Something went wrong', err?.message || String(err)));
