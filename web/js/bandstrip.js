// The SPHEREx bands of one pass side by side, so an object that fades at some wavelengths
// (a methane-absorbing brown dwarf) is visible at a glance. Follows the frame on screen;
// clicking a band hands that frame to the main player.

import { el, shortDate } from './dom.js';
import { passFrames } from './framesets.js';
import { shortLabel, setLabel } from './labels.js';
import { COLORS } from './overlays.js';
import { falseColourPlan, falseColourCaption } from './falsecolour.js';
import { STRIP_LEAD, stripNote } from './striptext.js';

const CELL_PX = 96;
const FC_PX = 240;

function ring(ctx, frame, view, k, dpr) {
  const p = frame.predicted_px || frame.centroid_px;
  if (!p) return;
  ctx.setLineDash([3 * dpr, 3 * dpr]);
  ctx.lineWidth = 1.2 * dpr;
  ctx.strokeStyle = COLORS.predicted;
  ctx.beginPath();
  ctx.arc((p[0] - view.x0) * k, (p[1] - view.y0) * k, Math.max(7 * dpr, 2 * k), 0, Math.PI * 2);
  ctx.stroke();
  ctx.setLineDash([]);
}

/**
 * Compose three grey band images into one RGB picture: each is tinted to its pure channel colour
 * (multiply) and the three are added (lighter). Never reads pixels back, so it works for any image.
 */
function drawFalseColour(canvas, plan, images, view, size) {
  const dpr = window.devicePixelRatio || 1;
  const px = Math.round(FC_PX * dpr);
  if (canvas.width !== px) { canvas.width = px; canvas.height = px; }
  const ctx = canvas.getContext('2d');
  ctx.globalCompositeOperation = 'source-over';
  ctx.fillStyle = '#000';
  ctx.fillRect(0, 0, px, px);
  const off = document.createElement('canvas');
  off.width = px; off.height = px;
  const o = off.getContext('2d');
  for (const c of plan.channels) {
    const img = images.get(c.frame.id);
    const s = img.naturalWidth / size;
    o.globalCompositeOperation = 'source-over';
    o.imageSmoothingEnabled = false;
    o.drawImage(img, view.x0 * s, view.y0 * s, view.w * s, view.w * s, 0, 0, px, px);
    o.globalCompositeOperation = 'multiply';
    o.fillStyle = c.color;
    o.fillRect(0, 0, px, px);
    ctx.globalCompositeOperation = 'lighter';
    ctx.drawImage(off, 0, 0);
  }
  ctx.globalCompositeOperation = 'source-over';
  ring(ctx, plan.channels[0].frame, view, px / view.w, dpr);
}

function drawCell(canvas, img, view, frame, size) {
  const dpr = window.devicePixelRatio || 1;
  const px = Math.round(CELL_PX * dpr);
  if (canvas.width !== px) { canvas.width = px; canvas.height = px; }
  const ctx = canvas.getContext('2d');
  ctx.imageSmoothingEnabled = false;
  ctx.fillStyle = '#05070c';
  ctx.fillRect(0, 0, px, px);
  if (!img) return;
  const s = img.naturalWidth / size;
  ctx.drawImage(img, view.x0 * s, view.y0 * s, view.w * s, view.w * s, 0, 0, px, px);
  ring(ctx, frame, view, px / view.w, dpr);
}

/** The "methane false colour" toggle and its picture. */
function falseColourBox(initial, onToggle) {
  const box = el('input', { type: 'checkbox', id: 'fc-toggle' });
  const label = el('label', { class: 'check fc-check' }, [box, ' Methane false colour']);
  const why = el('p', { class: 'small muted fc-why', hidden: true });
  const canvas = el('canvas', { class: 'fc-canvas', role: 'img' });
  const cap = el('figcaption', { class: 'small muted' });
  const fig = el('figure', { class: 'fc-figure', hidden: true }, [canvas, cap]);
  let on = initial;
  box.checked = on;
  box.addEventListener('change', () => { on = box.checked; onToggle(on); });
  return { nodes: [label, why, fig], box, why, fig, canvas, cap, on: () => on };
}

/**
 * @param {{m: object, images: Map, onPick: (frame: object) => void, fc?: boolean, onFc?: (on: boolean) => void, brownDwarf?: boolean}} opts
 *   fc: false colour on at start (URL); onFc: told when the viewer toggles it; brownDwarf: add the methane line
 * @returns {{root: HTMLElement|null, update: (current: object, view: object) => void, setBrownDwarf: (on: boolean) => void}}
 */
export function bandStrip({ m, images, onPick, fc = false, onFc = () => {}, brownDwarf = false }) {
  const nSpx = new Set(m.frames.filter((f) => f.mission === 'SPHEREx').map((f) => f.band)).size;
  if (nSpx < 2) return { root: null, update: () => {}, setBrownDwarf: () => {} };
  const note = el('p', { class: 'small muted strip-note', text: stripNote(brownDwarf) });
  const caption = el('p', { class: 'small muted strip-caption' });
  const row = el('div', { class: 'strip-row' });
  let last = null;
  const fcBox = m.solar_system ? null : falseColourBox(fc, (on) => { onFc(on); if (last) { viewKey = ''; passKey = ''; update(...last); } });
  const root = el('section', { class: 'band-strip', 'aria-labelledby': 'strip-h' }, [
    el('h3', { id: 'strip-h', text: 'One SPHEREx pass, every band' }),
    el('p', { class: 'small muted strip-lead', text: STRIP_LEAD }),
    caption, row,
    note,
    ...(fcBox ? fcBox.nodes : []),
  ]);
  let passKey = '', viewKey = '', cells = [], plan = null;

  function syncFalseColour(pass) {
    if (!fcBox) return;
    plan = falseColourPlan(pass, (f) => !!images.get(f.id));
    fcBox.box.disabled = !plan.ok;
    fcBox.box.checked = plan.ok && fcBox.on(); // a disabled box never reads as on
    fcBox.why.hidden = plan.ok;
    fcBox.why.textContent = plan.reason;
    fcBox.fig.hidden = !(plan.ok && fcBox.on());
    if (plan.ok) {
      fcBox.cap.textContent = falseColourCaption(plan, setLabel);
      fcBox.canvas.setAttribute('aria-label', `False-colour picture of this SPHEREx pass: ${fcBox.cap.textContent}`);
    }
  }

  function build(pass, current) {
    const dates = pass.map((p) => p.frame?.date).filter(Boolean).sort();
    const span = dates.length > 1 && dates.at(-1).slice(0, 10) !== dates[0].slice(0, 10) ? ` to ${shortDate(dates.at(-1))}` : '';
    caption.textContent = dates.length ? `The SPHEREx pass nearest the image on screen, ${shortDate(dates[0])}${span}.` : '';
    cells = pass.map(({ set, frame }) => {
      // The unit is its own span, so a narrow strip can drop it and keep six equal cells (styles.css).
      const [range, unit] = shortLabel(set).split(/ (?=µm$)/);
      const label = el('span', { class: 'strip-label' }, [range, unit ? el('span', { class: 'unit', text: ` ${unit}` }) : null]);
      if (!frame) return { node: el('div', { class: 'strip-cell empty' }, [el('div', { class: 'strip-blank', text: 'no image' }), label]) };
      const canvas = el('canvas', { class: 'strip-canvas', 'aria-hidden': 'true' });
      const found = frame.centroid_px ? 'object found' : 'object not detected';
      const node = el('button', {
        type: 'button', class: 'strip-cell', 'aria-pressed': String(frame.id === current.id),
        'aria-label': `Show ${setLabel(frame)}, ${shortDate(frame.date)}, ${found}`, onClick: () => onPick(frame),
      }, [canvas, label, el('span', { class: `strip-det ${frame.centroid_px ? 'yes' : 'no'}`, text: frame.centroid_px ? 'found' : 'not found' })]);
      return { node, canvas, frame };
    });
    row.replaceChildren(...cells.map((c) => c.node));
  }

  function update(current, view) {
    if (!current) return;
    last = [current, view];
    const pass = passFrames(m.frames, current.mjd);
    const pk = pass.map((p) => p.frame?.id).join();
    const vk = [view.x0, view.y0, view.w].map((x) => x.toFixed(1)).join();
    if (pk !== passKey) { build(pass, current); syncFalseColour(pass); passKey = pk; viewKey = ''; }
    for (const c of cells) if (c.frame) c.node.setAttribute('aria-pressed', String(c.frame.id === current.id));
    if (vk !== viewKey) {
      viewKey = vk;
      for (const c of cells) if (c.frame) drawCell(c.canvas, images.get(c.frame.id), view, c.frame, m.size_px);
      if (fcBox && plan?.ok && fcBox.on()) drawFalseColour(fcBox.canvas, plan, images, view, m.size_px);
    }
  }
  return { root, update, setBrownDwarf: (on) => { note.textContent = stripNote(on); } };
}
