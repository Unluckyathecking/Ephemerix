// The "explore the sky" page: a draggable, zoomable star chart with our prebuilt views marked on it.
// State is just the view centre and field; every change asks for one redraw on the next frame.

import { mountChrome } from './chrome.js';
import { pageTitle } from './site.js';
import { $, prefersReducedMotion } from './dom.js';
import { constellationOf } from './constellation.js';
import { makeView, unproject, toVec, pan, zoomAt, fitFov, maxFov, angularSep } from './exploreproj.js';
import { decodeStars, hitTest, labelPosition } from './exploredata.js';
import { buildIndex, searchSky, nameResults } from './exploresearch.js';
import { parseExploreQuery, motionPath, pickMover, exploreCardParams } from './exploretext.js';
import { openingView, openingWords } from './exploreopen.js';
import { buildIndex as buildNameIndex } from './nameindex.js';
import { drawFrame, guideCurves } from './explorerender.js';
import { bindInput } from './exploreinput.js';
import { targetCard, pinCard, knownCard, targetList, knownList, resultItems } from './exploreui.js';

mountChrome('explore');
document.title = pageTitle('Explore the sky');

const canvas = $('#ex-sky');
const ctx = canvas.getContext('2d');
const card = $('#ex-card');
const tip = $('#ex-tip');
const statusLine = $('#ex-status');
const HOME = { ra: 90, dec: 5 }; // Orion near the middle: the November evening sky
const query = parseExploreQuery(location.search);

let size = { width: 0, height: 0, dpr: 1 };
let state = { ra: query.ra ?? HOME.ra, dec: query.dec ?? HOME.dec, fov: query.fov ?? Infinity };
let arrival = null; // the first status line, until the visitor moves the map
let scene = null;
let frame = { targets: [], known: [], stars: [] };
let raf = 0;
let flight = 0;
const manifests = new Map();
const drawTimes = []; // milliseconds per redraw, for the browser check

function palette() {
  const css = getComputedStyle(document.documentElement);
  const v = (name, fallback) => css.getPropertyValue(name).trim() || fallback;
  return {
    space: v('--bg', '#0b0c0e'), sky: '#07090d', outline: v('--line-strong', '#383c43'), grid: 'rgba(120,140,170,0.16)',
    galactic: 'rgba(200,162,255,0.35)', band: 'rgba(150,160,200,0.035)', ecliptic: 'rgba(255,181,71,0.32)', figure: 'rgba(130,160,200,0.30)',
    figureName: 'rgba(150,170,200,0.55)', starName: 'rgba(237,235,229,0.78)', starRing: 'rgba(237,235,229,0.22)', glow: 'rgba(220,230,255,0.22)',
    accent: v('--accent', '#ffb547'), pin: v('--wise', '#56d8ec'), known: 'rgba(86,216,236,0.75)', path: 'rgba(255,181,71,0.9)', sans: v('--sans', 'sans-serif'),
  };
}
const PALETTE = palette();

const currentView = () => makeView({ ...state, width: size.width, height: size.height });

function request() {
  if (!raf) raf = requestAnimationFrame(render);
}

function render() {
  raf = 0;
  if (!scene || !size.width) return;
  const t0 = performance.now();
  ctx.setTransform(size.dpr, 0, 0, size.dpr, 0, 0);
  frame = drawFrame(ctx, currentView(), scene, PALETTE);
  drawTimes.push(performance.now() - t0);
  if (drawTimes.length > 240) drawTimes.shift();
  canvas.dataset.ra = state.ra.toFixed(3);
  canvas.dataset.dec = state.dec.toFixed(3);
  canvas.dataset.fov = state.fov.toFixed(3);
}

function setState(next) {
  state = { ...state, ...next };
  if (size.width) state = { ...state, fov: fitFov(state.fov, size.width, size.height) };
  request();
}

function resize() {
  const r = canvas.getBoundingClientRect();
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  size = { width: r.width, height: r.height, dpr };
  canvas.width = Math.round(r.width * dpr);
  canvas.height = Math.round(r.height * dpr);
  setState({});
}

// ---- the card --------------------------------------------------------------------------

function closeCard() {
  card.hidden = true;
  card.replaceChildren();
  if (scene) { scene = { ...scene, pin: null, selected: null }; request(); writeUrl(); }
}

/** The map's own address: centre, zoom and the open card, so Back and "Back to the sky map" restore it. */
function writeUrl() {
  if (!Number.isFinite(state.fov)) return;
  const zoom = Math.round((360 / state.fov) * 100) / 100;
  const q = new URLSearchParams({ ra: state.ra.toFixed(3), dec: state.dec.toFixed(3), zoom: String(zoom), ...exploreCardParams(scene) });
  try { history.replaceState(null, '', `?${q.toString().replace(/%2C/g, ',')}`); } catch { /* throttled; the next write catches up */ }
}

const MAP_RETURN_KEY = 'ephemerix-map-return';

/** Leaving for a view: remember the map as it is, and mark the view as reached from the map. */
document.addEventListener('click', (e) => {
  const a = e.target.closest?.('main a[href^="index.html?"]');
  if (!a) return;
  writeUrl();
  try { sessionStorage.setItem(MAP_RETURN_KEY, `explore.html${location.search}`); } catch { /* the way back falls to the home view */ }
  if (!/[?&]from=map\b/.test(a.getAttribute('href'))) a.setAttribute('href', `${a.getAttribute('href')}&from=map`);
}, true);

async function openTarget(t) {
  scene = { ...scene, selected: t, pin: null };
  card.replaceChildren(...targetCard(t, manifests.get(t.slug) || null, closeCard));
  card.hidden = false;
  request();
  writeUrl();
  if (manifests.has(t.slug) || !t.manifest) return;
  try {
    const res = await fetch(`gallery/${t.manifest}`);
    if (!res.ok) return;
    manifests.set(t.slug, await res.json());
    if (scene.selected === t) card.replaceChildren(...targetCard(t, manifests.get(t.slug), closeCard));
  } catch { /* the card already shows the blurb; the measured motion is a bonus */ }
}

function openKnown(k) {
  scene = { ...scene, selected: k, pin: null };
  card.replaceChildren(...knownCard(k, scene.nameEpoch, closeCard));
  card.hidden = false;
  request();
  writeUrl();
}

function openPin(pos, star = null) {
  scene = { ...scene, selected: null, pin: pos };
  card.replaceChildren(...pinCard(pos, star, closeCard));
  card.hidden = false;
  request();
  writeUrl();
}

// ---- moving the view ------------------------------------------------------------------

/** Canvas edges covered by the search box, buttons and caption, in canvas pixels. */
function controlInsets() {
  const stage = $('.ex-stage').getBoundingClientRect();
  const top = $('.ex-top').getBoundingClientRect(), controls = $('.ex-controls').getBoundingClientRect();
  const stacked = getComputedStyle($('.ex-top')).display === 'flex';
  return stacked
    ? { top: top.bottom - stage.top + 12, bottom: stage.bottom - controls.top + 8, side: 16 }
    : { top: 8, bottom: 8, side: 8 };
}

function settle() {
  if (arrival) { statusLine.textContent = arrival; arrival = null; return; }
  const c = constellationOf(state.ra, state.dec);
  const inView = frame.targets.filter((p) => p && p.x >= 0 && p.y >= 0 && p.x <= size.width && p.y <= size.height).length;
  const across = state.fov >= maxFov(size.width, size.height) - 1 ? 'the whole sky' : `about ${Math.round(state.fov)} degrees across`;
  statusLine.textContent = `Looking towards ${c.name}, ${across}. ${inView === 1 ? 'One marked object' : `${inView || 'No'} marked objects`} in view.`
    + (state.fov < 8 ? ' This chart stops at stars you could see by eye; SPHEREx images show far fainter ones.' : '');
  writeUrl();
}

/** The home view: the whole sky on a wide screen, the busiest region on a phone (arrival by the nav, and Reset view). */
function homeView() {
  return openingView(scene.targets, size.width, size.height, controlInsets(), HOME);
}

/** Glide to a centre and field; jumps straight there when reduced motion is preferred. */
function flyTo(ra, dec, fov, done = () => {}) {
  cancelAnimationFrame(flight);
  const to = { ra, dec, fov: fitFov(fov, size.width, size.height) };
  if (prefersReducedMotion()) { setState(to); settle(); done(); return; }
  const from = { ...state };
  const dRa = ((to.ra - from.ra + 540) % 360) - 180;
  const sep = angularSep(from.ra, from.dec, to.ra, to.dec);
  const bump = Math.max(0, Math.log((sep * 1.4) / Math.max(from.fov, to.fov)));
  const t0 = performance.now(), ms = 700 + Math.min(600, sep * 4);
  const step = (now) => {
    const t = Math.min(1, (now - t0) / ms);
    const e = t < 0.5 ? 4 * t ** 3 : 1 - (-2 * t + 2) ** 3 / 2;
    const logFov = Math.log(from.fov) + (Math.log(to.fov) - Math.log(from.fov)) * e + bump * Math.sin(Math.PI * t);
    setState({ ra: (from.ra + dRa * e + 360) % 360, dec: from.dec + (to.dec - from.dec) * e, fov: Math.exp(logFov) });
    if (t < 1) flight = requestAnimationFrame(step); else { settle(); done(); }
  };
  flight = requestAnimationFrame(step);
}

/** Centre that puts a position in view; on a phone the card covers the lower half, so aim higher. */
function aimAt(ra, dec, fov) {
  const f = fitFov(fov, size.width, size.height);
  if (size.width >= 760) return { ra, dec, fov: f };
  return pan(makeView({ ra, dec, fov: f, width: size.width, height: size.height }), 0, -size.height * 0.22);
}

const showKnown = (k) => {
  const a = aimAt(k.ra, k.dec, Math.min(state.fov, 30));
  flyTo(a.ra, a.dec, a.fov);
  openKnown(k);
  $('.ex-stage').scrollIntoView({ block: 'nearest', behavior: prefersReducedMotion() ? 'auto' : 'smooth' });
  canvas.focus({ preventScroll: true });
};

const showTarget = (t) => {
  const a = aimAt(t.ra, t.dec, Math.min(state.fov, 30));
  flyTo(a.ra, a.dec, a.fov);
  openTarget(t);
  $('.ex-stage').scrollIntoView({ block: 'nearest', behavior: prefersReducedMotion() ? 'auto' : 'smooth' });
  canvas.focus({ preventScroll: true });
};

// ---- input -----------------------------------------------------------------------------

const touchRadius = () => (matchMedia('(pointer: coarse)').matches ? 24 : 14);

function tap(x, y) {
  tip.hidden = true;
  const ti = hitTest(frame.targets, x, y, touchRadius());
  if (ti >= 0) { openTarget(scene.targets[ti]); return; }
  const ki = hitTest(frame.known, x, y, touchRadius() - 2);
  if (ki >= 0) { openKnown(scene.known[ki]); return; }
  const si = hitTest(frame.stars, x, y, touchRadius() - 4);
  if (si >= 0) { const s = frame.stars[si]; openPin({ ra: s.ra, dec: s.dec }, s); return; }
  const pos = unproject(currentView(), x, y);
  if (pos) openPin(pos); else closeCard();
}

function hover(x, y) {
  const ti = hitTest(frame.targets, x, y, 14);
  const ki = ti < 0 ? hitTest(frame.known, x, y, 12) : -1;
  const si = ti < 0 && ki < 0 ? hitTest(frame.stars, x, y, 10) : -1;
  const name = ti >= 0 ? scene.targets[ti].name : ki >= 0 ? `${scene.known[ki].label} (we can build this)` : si >= 0 ? frame.stars[si].name : null;
  canvas.classList.toggle('is-pointing', ti >= 0 || ki >= 0);
  tip.hidden = !name;
  if (name) { tip.textContent = name; tip.style.transform = `translate(${Math.round(x + 14)}px, ${Math.round(y + 14)}px)`; }
}

function key(e) {
  const step = size.width * 0.12;
  const moves = { ArrowLeft: [step, 0], ArrowRight: [-step, 0], ArrowUp: [0, step], ArrowDown: [0, -step] };
  if (moves[e.key]) { setState(pan(currentView(), ...moves[e.key])); settle(); return true; }
  if (e.key === '+' || e.key === '=') { zoomBy(1.5); return true; }
  if (e.key === '-' || e.key === '_') { zoomBy(1 / 1.5); return true; }
  if (e.key === '0' || e.key === 'Home') { flyTo(HOME.ra, HOME.dec, Infinity); return true; }
  if (e.key === 'Escape' && !card.hidden) { closeCard(); return true; }
  if (e.key === 'Enter') {
    const i = hitTest(frame.targets, size.width / 2, size.height / 2, Math.min(size.width, size.height) / 3);
    if (i >= 0) { openTarget(scene.targets[i]); return true; }
  }
  return false;
}

function zoomBy(f) {
  setState(zoomAt(currentView(), f, size.width / 2, size.height / 2));
  settle();
}

bindInput(canvas, {
  pan: (dx, dy) => { cancelAnimationFrame(flight); setState(pan(currentView(), dx, dy)); },
  zoom: (f, x, y) => { cancelAnimationFrame(flight); setState(zoomAt(currentView(), f, x, y)); },
  tap, hover, key, settle,
  leave: () => { tip.hidden = true; },
});

$('#ex-in').addEventListener('click', () => zoomBy(2));
$('#ex-out').addEventListener('click', () => zoomBy(0.5));
$('#ex-reset').addEventListener('click', () => { closeCard(); const o = homeView(); flyTo(o.ra, o.dec, o.fov); });
$('#ex-move').addEventListener('click', (e) => {
  if (!scene) return;
  const t = pickMover(scene.targets, scene.selected?.slug ?? null, Math.random);
  if (!t) return;
  showTarget(t);
  // Once it has taken you somewhere, the same button offers the next one.
  e.currentTarget.textContent = 'Show me another';
});
$('#ex-grid').addEventListener('click', (e) => {
  const on = e.currentTarget.getAttribute('aria-pressed') !== 'true';
  e.currentTarget.setAttribute('aria-pressed', String(on));
  scene = scene && { ...scene, grid: on };
  request();
});

// ---- search ----------------------------------------------------------------------------

function bindSearch(index, nameIndex) {
  // Names from the site's index first (any alias), then stars, constellations and positions.
  const find = (q) => {
    const named = nameResults(nameIndex, q);
    const seen = new Set(named.map((r) => r.label.toLowerCase()));
    return [...named, ...searchSky(q, index).filter((r) => !seen.has(r.label.toLowerCase()))].slice(0, 7);
  };
  const input = $('#ex-q'), list = $('#ex-results');
  let results = [], active = 0;
  const show = () => {
    list.replaceChildren(...resultItems(results, active, pick));
    list.hidden = !results.length;
    input.setAttribute('aria-expanded', String(!list.hidden));
    input.setAttribute('aria-activedescendant', results.length ? `ex-opt-${active}` : '');
  };
  function pick(r) {
    results = []; show();
    input.blur();
    if (r.kind === 'target') { const t = scene.targets.find((x) => x.slug === r.slug); if (t) { showTarget(t); return; } }
    if (r.kind === 'known') { const k = scene.known.find((x) => x.entry === r.entry); if (k) { showKnown(k); return; } }
    flyTo(r.ra, r.dec, r.fov, () => {
      if (r.kind === 'position') openPin({ ra: r.ra, dec: r.dec });
      if (r.kind === 'star') openPin({ ra: r.ra, dec: r.dec }, frame.stars.find((s) => s.name === r.label) || null);
    });
  }
  input.addEventListener('input', () => { results = find(input.value); active = 0; show(); });
  input.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown' && results.length) { active = (active + 1) % results.length; show(); e.preventDefault(); }
    if (e.key === 'ArrowUp' && results.length) { active = (active - 1 + results.length) % results.length; show(); e.preventDefault(); }
    if (e.key === 'Escape') { results = []; show(); }
  });
  input.addEventListener('blur', () => setTimeout(() => { results = []; show(); }, 150));
  $('#ex-search').addEventListener('submit', (e) => {
    e.preventDefault();
    const now = results.length ? results : find(input.value);
    if (now.length) pick(now[Math.min(active, now.length - 1)]);
    else { statusLine.textContent = `We could not find “${input.value.trim()}”. Try a star name, one of the objects listed below, or RA and Dec in degrees.`; }
  });
}

// ---- start -----------------------------------------------------------------------------

async function getJson(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url}: ${res.status}`);
  return res.json();
}

async function start() {
  const [starJson, lineJson, gallery, names] = await Promise.all([
    getJson('data/stars.json'), getJson('data/constellation-lines.json'), getJson('gallery/index.json'),
    getJson('data/names.json').catch(() => null), // optional: the map works without the name index
  ]);
  const nameIndex = buildNameIndex(names);
  const nameEpoch = Number.isFinite(names?.epoch) ? names.epoch : 2000;
  const bySlug = new Map(nameIndex.filter(({ entry }) => entry.slug).map(({ entry }) => [entry.slug, entry]));
  const known = nameIndex.filter(({ entry }) => !entry.slug && Number.isFinite(entry.ra) && Number.isFinite(entry.dec))
    .map(({ entry }) => ({ entry, label: entry.label, ra: entry.ra, dec: entry.dec, vec: toVec(entry.ra, entry.dec) }));
  const stars = decodeStars(starJson);
  const figures = lineJson.constellations.map((c) => {
    const p = labelPosition(stars, c.lines);
    return { ...c, labelVec: p && toVec(p.ra, p.dec), label: p };
  });
  const named = new Map(lineJson.names.map(([i, name]) => [i, name]));
  const pathOf = (slug) => {
    const e = bySlug.get(slug);
    const p = e && motionPath(e, nameEpoch);
    return p && p.map((q) => toVec(q.ra, q.dec));
  };
  const targets = gallery.targets.filter((t) => Number.isFinite(t.ra) && Number.isFinite(t.dec))
    .map((t) => ({ ...t, pmra: bySlug.get(t.slug)?.pmra, pmdec: bySlug.get(t.slug)?.pmdec, vec: toVec(t.ra, t.dec), path: pathOf(t.slug) }));
  scene = { stars, figures, named, targets, known, nameEpoch, guides: guideCurves(), pin: null, selected: null, grid: false };
  $('#ex-loading').hidden = true;
  $('#ex-list').replaceChildren(...targetList(targets, showTarget));
  $('#ex-known').replaceChildren(...knownList(known, showKnown));
  $('#ex-known-section').hidden = !known.length;
  bindSearch(buildIndex({
    targets,
    stars: lineJson.names.map(([i, name]) => ({ name, ra: stars.ra[i], dec: stars.dec[i] })),
    constellations: figures.filter((f) => f.label).map((f) => ({ name: f.name, ra: f.label.ra, dec: f.label.dec })),
  }), nameIndex);
  new ResizeObserver(resize).observe(canvas);
  resize();
  const wanted = query.target && targets.find((t) => t.slug === query.target);
  if (wanted) { if (query.ra == null) setState(aimAt(wanted.ra, wanted.dec, query.fov ?? 30)); openTarget(wanted); }
  else if (query.ra == null) {
    // Arrival with no address (the nav link): the home view, where our views are, as wide as keeps the rings tappable.
    const o = homeView();
    setState({ ra: o.ra, dec: o.dec, fov: o.fov });
    arrival = openingWords(o.shown, targets.length);
  }
  render();
  // Back, or "Back to the sky map": reopen the card that was open.
  const knownWanted = query.known && known.find((k) => k.label === query.known);
  if (knownWanted) openKnown(knownWanted);
  else if (query.pin && !wanted) {
    const star = frame.stars.find((s) => s.name && Math.abs(s.ra - query.pin.ra) < 1e-3 && Math.abs(s.dec - query.pin.dec) < 1e-3) || null;
    openPin(query.pin, star);
  }
  settle();
  window.__explore = { get state() { return { ...state }; }, get frame() { return frame; }, drawTimes };
}

start().catch(() => {
  $('#ex-loading').textContent = 'We could not load the star chart. Try reloading the page.';
});
