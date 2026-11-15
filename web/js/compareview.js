// Compare mode: "B minus A" or "A plus B" of two frames of one image set, computed in the
// browser from the decoded PNG pixels and shown on the stage in place of the blink.

import { el, shortDate } from './dom.js';
import { bandSets } from './framesets.js';
import { setLabel } from './labels.js';
import { MODES, compareAllowed, defaultPair, playingPair, pairCaption, combinePixels } from './compare.js';

const NOTE = 'A display difference of stretched images, not photometry: the brightness here is not calibrated flux. '
  + 'In "B minus A" fixed stars cancel to grey, and a moving object shows as a dark spot where it was (A) and a bright spot where it went (B).';

function pixelsOf(img, size) {
  const c = document.createElement('canvas');
  c.width = size; c.height = size;
  const g = c.getContext('2d', { willReadFrequently: true });
  g.imageSmoothingEnabled = false;
  g.drawImage(img, 0, 0, size, size);
  return g.getImageData(0, 0, size, size);
}

/** Combined image as a canvas, or throws Error with a message for the user. */
function compute(ia, ib, mode) {
  if (!ia || !ib) throw new Error('One of the two images could not be loaded.');
  const size = Math.max(ia.naturalWidth, ib.naturalWidth);
  let a, b;
  try {
    a = pixelsOf(ia, size); b = pixelsOf(ib, size);
  } catch {
    throw new Error('The browser is not allowed to read these images’ pixels (they come from another server without permission), so the comparison cannot be computed here.');
  }
  const out = document.createElement('canvas');
  out.width = size; out.height = size;
  out.getContext('2d').putImageData(new ImageData(combinePixels(a.data, b.data, mode), size, size), 0, 0);
  return out;
}

/**
 * playing: the frames in the blink, whose set's first and last date open the comparison.
 * @param {{m: object, images: Map, stage: object, current: () => object|null, playing?: () => object[],
 *          onChange: (s: {cmp: string|null, a: string|null, b: string|null}) => void,
 *          onToggle: (on: boolean) => void, initial: {cmp: string|null, a: string|null, b: string|null}}} o
 */
export function compareMode({ m, images, stage, current, playing = () => [], onChange, onToggle, initial }) {
  const byId = new Map(m.frames.map((f) => [f.id, f]));
  let on = false, mode = 'diff', fa = null, fb = null;
  const cache = new Map();

  const select = (id, label) => el('select', { id, 'aria-label': label },
    bandSets(m.frames).map((s) => el('optgroup', { label: setLabel(s) },
      m.frames.filter((f) => f.band === s.band).map((f) => el('option', { value: f.id, text: `${shortDate(f.date)} · ${setLabel(f)}` })))));
  const selA = select('cmp-a', 'Frame A'), selB = select('cmp-b', 'Frame B');
  const modeBtns = Object.entries(MODES).map(([k, label]) => el('button', { type: 'button', class: 'seg', 'aria-pressed': 'false', 'data-mode': k, text: label,
    onClick: () => { mode = k; refresh(); } }));
  const msg = el('p', { class: 'cmp-msg', role: 'status', 'aria-live': 'polite' });
  const toggle = el('button', { type: 'button', class: 'btn', 'aria-pressed': 'false', text: 'Compare two dates', onClick: () => (on ? disable() : enable()) });
  const panel = el('div', { class: 'cmp-panel', hidden: true }, [
    el('div', { class: 'segmented', role: 'group', 'aria-label': 'Combine' }, modeBtns),
    el('div', { class: 'cmp-pick' }, [el('label', { for: 'cmp-a', text: 'A' }), selA, el('label', { for: 'cmp-b', text: 'B' }), selB]),
    msg,
    el('p', { class: 'small muted', text: NOTE }),
  ]);
  selA.addEventListener('change', () => { fa = byId.get(selA.value); refresh(); });
  selB.addEventListener('change', () => { fb = byId.get(selB.value); refresh(); });

  function refresh() {
    modeBtns.forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.mode === mode)));
    selA.value = fa?.id ?? ''; selB.value = fb?.id ?? '';
    onChange({ cmp: mode, a: fa?.id ?? null, b: fb?.id ?? null });
    const ok = compareAllowed(fa, fb);
    if (!ok.ok) { msg.textContent = ok.reason; msg.classList.add('warn'); stage.setOverride(null); return; }
    msg.classList.remove('warn');
    const key = `${mode}|${fa.id}|${fb.id}`;
    try {
      if (!cache.has(key)) cache.set(key, compute(images.get(fa.id), images.get(fb.id), mode));
    } catch (err) {
      msg.textContent = err.message; msg.classList.add('warn'); stage.setOverride(null); return;
    }
    const word = mode === 'diff' ? 'B − A' : 'A + B (mean)';
    msg.textContent = pairCaption(fa, fb, mode, setLabel(fa), shortDate);
    stage.setOverride({ canvas: cache.get(key), frame: fb, active: [fa, fb],
      lines: [`${word}  ${shortDate(fa.date)} → ${shortDate(fb.date)}`, `${setLabel(fb)} · display only, not photometry`] });
  }

  function enable(init = null) {
    const pair = playingPair(playing()) || defaultPair(m.frames, current()?.band) || defaultPair(m.frames, bandSets(m.frames).find((s) => s.count >= 2)?.band);
    fa = (init?.a && byId.get(init.a)) || pair?.[0] || null;
    fb = (init?.b && byId.get(init.b)) || pair?.[1] || null;
    if (init?.cmp) mode = init.cmp;
    on = true;
    panel.hidden = false;
    toggle.setAttribute('aria-pressed', 'true');
    toggle.textContent = 'Back to the blink';
    onToggle(true);
    refresh();
  }

  function disable() {
    on = false;
    panel.hidden = true;
    toggle.setAttribute('aria-pressed', 'false');
    toggle.textContent = 'Compare two dates';
    stage.setOverride(null);
    onChange({ cmp: null, a: null, b: null });
    onToggle(false);
  }

  const root = el('section', { class: 'compare-box', 'aria-label': 'Compare two dates' }, [toggle, panel]);
  return { root, active: () => on, start: () => { if (initial?.cmp) enable(initial); }, stop: () => { if (on) disable(); } };
}
