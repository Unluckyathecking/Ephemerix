// "Images in the blink": quick presets plus one toggle per image set, labelled from
// mission and wavelength. Calls onChange(bands, presetId|null) after a user change.

import { el } from './dom.js';
import { bandSets, PRESETS, presetBands, matchPreset } from './framesets.js';
import { setLabel } from './labels.js';

/**
 * @param {object[]} frames all manifest frames
 * @param {string[]} initial bands in the blink
 * @param {(bands: string[], preset: string|null) => void} onChange
 * @returns {{root: HTMLElement, sets: HTMLElement, set: (bands: string[]) => void}} root: the quick choices;
 *   sets: one toggle per image set (kept under "More controls")
 */
export function bandPicker(frames, initial, onChange) {
  let bands = initial;
  const sets = bandSets(frames);
  const presets = PRESETS.map((p) => ({ ...p, bands: presetBands(frames, p.id) }))
    .filter((p) => p.bands.length && !(p.id === 'spherex-all' && p.bands.length < 2));
  // Drop presets that duplicate an earlier one here (e.g. "Everything" when there is only SPHEREx).
  const shown = presets.filter((p, i) => !presets.slice(0, i).some((q) => q.bands.join() === p.bands.join()));

  const buttons = shown.map((p) => el('button', {
    type: 'button', class: 'seg', 'aria-pressed': 'false', title: p.help, 'data-preset': p.id, text: p.label,
    onClick: () => apply(p.bands, p.id),
  }));
  const boxes = sets.map((s) => el('input', { type: 'checkbox', value: s.band,
    onChange: () => {
      const next = boxes.filter((b) => b.checked).map((b) => b.value);
      if (!next.length) { sync(); return; }
      apply(next, null);
    } }));
  const chips = sets.map((s, i) => el('label', { class: `chip ${s.mission === 'SPHEREx' ? 'spx' : 'wise'}`,
    title: `${s.count} image${s.count === 1 ? '' : 's'}, object found in ${s.detections}` }, [boxes[i], ` ${setLabel(s)}`]));
  const help = el('p', { class: 'small muted preset-help', 'aria-live': 'polite' });

  function sync() {
    const on = new Set(bands);
    boxes.forEach((b) => { b.checked = on.has(b.value); });
    const current = matchPreset(frames, bands);
    buttons.forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.preset === current)));
    help.textContent = PRESETS.find((p) => p.id === current)?.help || 'A custom selection of image sets.';
  }
  function apply(next, presetId) {
    bands = next;
    sync();
    onChange(bands, presetId);
  }
  sync();

  const root = el('div', { class: 'presets-box' }, [
    el('p', { class: 'label', id: 'presets-h', text: 'Images in the blink' }),
    shown.length > 1 ? el('div', { class: 'segmented presets', role: 'group', 'aria-labelledby': 'presets-h' }, buttons) : null,
    help,
  ]);
  const setsEl = el('fieldset', { class: 'chips' }, [
    el('legend', { text: 'Image sets' }),
    el('div', { class: 'chip-row' }, chips),
  ]);
  return { root, sets: setsEl, set: (next) => { bands = next; sync(); } };
}
