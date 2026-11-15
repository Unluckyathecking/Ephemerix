// Simple or Advanced, for the whole site: the switch in the header rail, the stored choice, the
// URL (mode=simple; mode=advanced or mode=full force Advanced), and the one-time hint. Advanced is
// the default. Pages listen for the 'ephemerix:mode' event; text pages get their sections opened here.

import { el, prefersReducedMotion } from './dom.js';

const KEY = 'ephemerix-mode';
const HINT_KEY = 'ephemerix-mode-hint';
export const MODE_EVENT = 'ephemerix:mode';
// Pages whose detail sits in closed <details class="card"> sections: Advanced opens them.
const TEXT_PAGES = new Set(['planetx', 'search', 'validation']);
const HINT_DELAY_MS = 1500;
const HINT_LIFE_MS = 6000;

/** 'simple' | 'advanced' | null; 'full' is the older name for Advanced. */
export function normaliseMode(v) {
  if (v === 'simple') return 'simple';
  return v === 'advanced' || v === 'full' ? 'advanced' : null;
}

/** The URL wins, then the stored choice, then Advanced. */
export function resolveMode(urlValue, stored) {
  return normaliseMode(urlValue) || normaliseMode(stored) || 'advanced';
}

/** The query string with mode=simple for Simple and no mode for Advanced, other parameters kept. */
export function searchWithMode(search, mode) {
  const q = new URLSearchParams(search);
  q.delete('mode');
  if (mode === 'simple') q.set('mode', 'simple');
  const s = q.toString().replace(/%2C/g, ',');
  return s ? `?${s}` : '';
}

/** First page view of someone who has not chosen a mode, and not already in Simple. */
export function shouldHint({ stored, hinted, mode = 'advanced' }) {
  return !normaliseMode(stored) && !hinted && mode !== 'simple';
}

/** The choice a URL makes (mode=simple, mode=advanced or mode=full), to remember like a click on the switch; else null. */
export function urlChoice(search) {
  return normaliseMode(new URLSearchParams(search).get('mode'));
}

function storage(key, value) {
  try {
    if (value === undefined) return window.localStorage.getItem(key);
    window.localStorage.setItem(key, value);
  } catch { /* storage blocked: the choice lasts for this page only */ }
  return null;
}

/** The mode for this page view: the URL, else the stored choice, else Advanced. */
export function currentMode() {
  return resolveMode(new URLSearchParams(window.location.search).get('mode'), storage(KEY));
}

/** Text pages: Advanced opens every section, Simple closes the ones it opened; later sections too. */
function applySections(mode) {
  if (!TEXT_PAGES.has(document.body.dataset.page)) return;
  for (const d of document.querySelectorAll('main details.card')) {
    if (mode === 'advanced' && !d.open) { d.open = true; d.dataset.modeOpened = '1'; }
    if (mode === 'simple' && d.dataset.modeOpened) { d.open = false; delete d.dataset.modeOpened; }
  }
}

function reflect(mode) {
  document.body.classList.toggle('mode-simple', mode === 'simple');
  document.body.classList.toggle('mode-advanced', mode === 'advanced');
  for (const b of document.querySelectorAll('.mode-switch button')) b.setAttribute('aria-pressed', String(b.dataset.mode === mode));
  applySections(mode);
}

/**
 * Change mode: store it, push a history entry (so Back returns), and tell the page.
 * @param {'simple'|'advanced'} mode
 */
export function setMode(mode) {
  const from = currentMode();
  if (mode === from) return;
  storage(KEY, mode);
  storage(HINT_KEY, '1');
  try {
    window.history.replaceState({ ...(window.history.state || {}), mode: from }, '');
    window.history.pushState({ ...(window.history.state || {}), mode }, '', searchWithMode(window.location.search, mode) || window.location.pathname);
  } catch { /* history unavailable: the page still changes */ }
  announce(mode);
}

function announce(mode) {
  reflect(mode);
  window.dispatchEvent(new CustomEvent(MODE_EVENT, { detail: { mode } }));
}

/** The one-time pointer to the switch: polite, small, gone on any use or after a few seconds. */
function hint(wrap) {
  if (!shouldHint({ stored: storage(KEY), hinted: !!storage(HINT_KEY), mode: currentMode() })) return;
  storage(HINT_KEY, '1');
  const away = (e) => { if (!node.contains(e.target)) close(); };
  const close = () => {
    node.remove();
    document.removeEventListener('pointerdown', away, true);
  };
  const node = el('p', { class: 'mode-hint', role: 'status', 'aria-live': 'polite', hidden: true }, [
    el('button', { type: 'button', class: 'mode-hint-text', text: 'Too much detail? Switch to Simple', onClick: () => { close(); setMode('simple'); } }),
    el('button', { type: 'button', class: 'mode-hint-x', 'aria-label': 'Dismiss this hint', text: '×', onClick: close }),
  ]);
  wrap.append(node);
  setTimeout(() => { node.hidden = false; if (!prefersReducedMotion()) node.classList.add('in'); }, HINT_DELAY_MS);
  setTimeout(close, HINT_DELAY_MS + HINT_LIFE_MS);
  wrap.addEventListener('click', close, { once: true });
  // A tap anywhere else also sends it away, so it never sits over what you reach for.
  document.addEventListener('pointerdown', away, true);
}

/** The switch for the header rail; call once per page (chrome.js does). */
export function modeSwitch() {
  // A mode in the URL is the visitor's choice, kept for later pages exactly as the switch keeps it.
  const chosen = urlChoice(window.location.search);
  if (chosen) { storage(KEY, chosen); storage(HINT_KEY, '1'); }
  const mode = currentMode();
  const btn = (m, label) => el('button', { type: 'button', 'data-mode': m, 'aria-pressed': String(m === mode), text: label, onClick: () => setMode(m) });
  const wrap = el('div', { class: 'mode-switch', role: 'group', 'aria-label': 'Level of detail' }, [btn('simple', 'Simple'), btn('advanced', 'Advanced')]);
  queueMicrotask(() => {
    reflect(mode);
    // Sections can render after load: open them as they appear.
    if (TEXT_PAGES.has(document.body.dataset.page)) new MutationObserver(() => applySections(currentMode())).observe(document.querySelector('main') || document.body, { childList: true, subtree: true });
    hint(wrap);
  });
  window.addEventListener('popstate', (e) => {
    const m = normaliseMode(e.state?.mode) || currentMode();
    storage(KEY, m);
    announce(m);
  });
  return wrap;
}
