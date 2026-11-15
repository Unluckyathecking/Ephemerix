// The marks on top of the star chart: our built views (orange rings), the objects from the name
// index we can build live (quiet cyan diamonds), the 2010-2026 path of fast movers, the pin, and
// label placement that drops a label rather than let it overlap another.

import { project, toVec } from './exploreproj.js';

const TAU = Math.PI * 2;
const onScreen = (p, view, pad) => p.x > -pad && p.y > -pad && p.x < view.width + pad && p.y < view.height + pad;

/** Text with a dark halo so it reads over stars and lines. */
export function label(ctx, text, x, y, colour, align = 'left') {
  ctx.textAlign = align;
  ctx.lineWidth = 3;
  ctx.strokeStyle = 'rgba(5,6,8,0.85)';
  ctx.strokeText(text, x, y);
  ctx.fillStyle = colour;
  ctx.fillText(text, x, y);
}

const overlaps = (a, list) => list.some((o) => a.x < o.x + o.w && o.x < a.x + a.w && a.y < o.y + o.h && o.y < a.y + a.h);

/** Draw a label unless it would overlap one already placed this frame. Returns whether it was drawn. */
export function place(ctx, placed, text, x, y, colour, align = 'left') {
  const w = ctx.measureText(text).width;
  const box = { x: align === 'center' ? x - w / 2 : x, y: y - 10, w, h: 13 };
  if (overlaps(box, placed)) return false;
  placed.push(box);
  label(ctx, text, x, y, colour, align);
  return true;
}

/** Orange rings for the built views, labelled wherever there is room (the whole sky included). */
export function drawTargets(ctx, view, targets, selected, palette, placed) {
  const pts = targets.map((t) => {
    const p = project(view, t.vec);
    return onScreen(p, view, 20) ? p : null;
  });
  targets.forEach((t, i) => {
    const p = pts[i];
    if (!p) return;
    const sel = t === selected;
    ctx.beginPath(); ctx.arc(p.x, p.y, sel ? 11 : 8, 0, TAU);
    ctx.lineWidth = sel ? 2.5 : 1.75; ctx.strokeStyle = palette.accent; ctx.stroke();
    ctx.beginPath(); ctx.arc(p.x, p.y, 2.6, 0, TAU);
    ctx.fillStyle = palette.accent; ctx.fill();
  });
  // The selected one first, so its name always shows; the rest only where they fit.
  const order = targets.map((t, i) => i).sort((a, b) => (targets[b] === selected) - (targets[a] === selected));
  for (const i of order) {
    const p = pts[i];
    if (!p) continue;
    ctx.font = `600 ${view.fov > 120 ? 11 : 12}px ${palette.sans}`;
    place(ctx, placed, targets[i].name, p.x + 12, p.y + 4, palette.accent);
  }
  return pts;
}

/** Small cyan diamonds for objects we can build live; their labels are returned for later placing. */
export function drawKnown(ctx, view, known, selected, palette) {
  const pts = [];
  const labels = [];
  ctx.lineWidth = 1.5;
  ctx.strokeStyle = palette.known;
  for (const k of known) {
    const p = project(view, k.vec);
    if (!onScreen(p, view, 12)) { pts.push(null); continue; }
    pts.push(p);
    const r = k === selected ? 7 : 5;
    ctx.beginPath();
    ctx.moveTo(p.x, p.y - r); ctx.lineTo(p.x + r, p.y); ctx.lineTo(p.x, p.y + r); ctx.lineTo(p.x - r, p.y); ctx.closePath();
    ctx.stroke();
    if (view.fov <= 90 || k === selected) labels.push({ text: k.label, x: p.x + 9, y: p.y + 4 });
  }
  ctx.font = `500 11px ${palette.sans}`;
  return { pts, labels };
}

/**
 * The 2010 to 2026 path of a built view with a catalogue proper motion, drawn only once it is long
 * enough to see (a few degrees across): a hint of the motion before the tap.
 */
export function drawPaths(ctx, view, targets, palette) {
  let drawn = 0;
  if (view.fov > 12) return drawn;
  ctx.font = `500 10px ${palette.sans}`;
  for (const t of targets) {
    if (!t.path) continue;
    const a = project(view, t.path[0]), b = project(view, t.path[1]);
    const len = Math.hypot(b.x - a.x, b.y - a.y);
    if (len < 6 || (!onScreen(a, view, 0) && !onScreen(b, view, 0))) continue;
    drawn += 1;
    ctx.strokeStyle = palette.path; ctx.fillStyle = palette.path; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
    const ux = (b.x - a.x) / len, uy = (b.y - a.y) / len, h = Math.min(8, len / 2);
    ctx.beginPath();
    ctx.moveTo(b.x, b.y);
    ctx.lineTo(b.x - ux * h - uy * h * 0.6, b.y - uy * h + ux * h * 0.6);
    ctx.lineTo(b.x - ux * h + uy * h * 0.6, b.y - uy * h - ux * h * 0.6);
    ctx.closePath(); ctx.fill();
    if (len > 28) {
      label(ctx, '2010', a.x - ux * 6, a.y - uy * 6 + 4, palette.path, ux > 0 ? 'right' : 'left');
      label(ctx, '2026', b.x + ux * 6, b.y + uy * 6 + 4, palette.path, ux > 0 ? 'left' : 'right');
    }
  }
  return drawn;
}

/** The dropped pin: a cyan ring with four ticks. */
export function drawPin(ctx, view, pin, palette) {
  if (!pin) return;
  const p = project(view, toVec(pin.ra, pin.dec));
  if (Math.abs(p.lon) > 175) return;
  ctx.strokeStyle = palette.pin; ctx.lineWidth = 2;
  ctx.beginPath(); ctx.arc(p.x, p.y, 9, 0, TAU); ctx.stroke();
  ctx.beginPath();
  for (const [dx, dy] of [[0, -1], [0, 1], [-1, 0], [1, 0]]) { ctx.moveTo(p.x + dx * 13, p.y + dy * 13); ctx.lineTo(p.x + dx * 18, p.y + dy * 18); }
  ctx.stroke();
}
