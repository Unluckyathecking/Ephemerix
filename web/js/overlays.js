// Canvas overlay drawing. Every function takes the view transform
// v = {x0, y0, k, u}: canvas = (imagePx - x0) * k, u = device pixels per CSS px.

import { sourcePxAt } from './sky.js';

export const COLORS = {
  predicted: '#ffb547',
  measured: '#56d8ec',
  gaia: '#c8a2ff',
  catwise: '#8be28f',
  mover: '#ff8bd1',
  ink: '#f2f4f8',
  shadow: 'rgba(5, 8, 14, 0.85)',
  wise: '#56d8ec',
  spherex: '#ffb547',
};

// The page's own faces (styles.css); canvas text falls back to the system face until they load.
const SANS = '"IBM Plex Sans", ui-sans-serif, system-ui, sans-serif';
const MONO = '"IBM Plex Mono", ui-monospace, Menlo, monospace';

const toC = (v, p) => [(p[0] - v.x0) * v.k, (p[1] - v.y0) * v.k];

function outlined(ctx, v, draw, color, width = 1.5) {
  ctx.lineWidth = (width + 2) * v.u;
  ctx.strokeStyle = COLORS.shadow;
  draw();
  ctx.stroke();
  ctx.lineWidth = width * v.u;
  ctx.strokeStyle = color;
  draw();
  ctx.stroke();
}

function text(ctx, v, s, x, y, color, align = 'left', size = 11, face = SANS, weight = 600) {
  ctx.font = `${weight} ${size * v.u}px ${face}`;
  ctx.textAlign = align;
  ctx.textBaseline = 'middle';
  ctx.lineWidth = 3 * v.u;
  ctx.strokeStyle = COLORS.shadow;
  ctx.strokeText(s, x, y);
  ctx.fillStyle = color;
  ctx.fillText(s, x, y);
}

/**
 * Which ticks of a track carry their year: the first, the last and the one nearest the middle,
 * so the labels never run into each other or sit on the object. Pure.
 * @param {number} n number of ticks
 * @returns {Set<number>}
 */
export function labelledTicks(n) {
  if (n <= 0) return new Set();
  return new Set([0, Math.round((n - 1) / 2), n - 1]);
}

/**
 * The yearly track up to the newest image: a manifest's track runs to the start of the next year,
 * and a "2027" label beside images that end in 2026 would claim a date we have no image for. Pure.
 * @param {{year: number}[]} track
 * @param {number|null} lastYear decimal year of the newest frame
 */
export function trackUntil(track, lastYear) {
  return Number.isFinite(lastYear) ? track.filter((t) => t.year <= lastYear + 1e-6) : track;
}

/** Predicted path with a tick at each year; the first, middle and last carry their year. */
export function drawTrack(ctx, v, track, avoid = null) {
  if (track.length < 2) return;
  const pts = track.map((t) => toC(v, t.px));
  ctx.setLineDash([]);
  outlined(ctx, v, () => {
    ctx.beginPath();
    pts.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
  }, COLORS.predicted, 1.25);
  const span = Math.hypot(pts.at(-1)[0] - pts[0][0], pts.at(-1)[1] - pts[0][1]);
  // Labels only where the three of them have room; a short track keeps its ends.
  const marks = span > 110 * v.u ? labelledTicks(track.length) : new Set([0, track.length - 1]);
  const [dx, dy] = [pts.at(-1)[0] - pts[0][0], pts.at(-1)[1] - pts[0][1]];
  const len = Math.hypot(dx, dy) || 1;
  const [nx, ny] = [-dy / len, dx / len]; // normal to the track for label offset
  let lastLabel = null; // a track inside one year (a Solar System body) would repeat its year at every tick
  track.forEach((t, i) => {
    const [x, y] = pts[i];
    ctx.fillStyle = COLORS.predicted;
    ctx.beginPath();
    ctx.arc(x, y, 2.2 * v.u, 0, Math.PI * 2);
    ctx.fill();
    const label = String(Math.floor(t.year + 1e-6)); // the calendar year (yearly tracks sit on whole years)
    // A label that would sit on the object's ring is left out.
    const onRing = avoid && Math.hypot(x - avoid[0], y - avoid[1]) < 26 * v.u;
    if (marks.has(i) && label !== lastLabel && !onRing) {
      text(ctx, v, label, x + nx * 14 * v.u, y + ny * 14 * v.u, COLORS.predicted, 'center', 10, MONO, 500);
      lastLabel = label;
    }
  });
}

/** Dotted arrow across a long gap in time: where the object was, to where it is now. */
export function drawGapPath(ctx, v, from, to) {
  const [x0, y0] = toC(v, from), [x1, y1] = toC(v, to);
  ctx.setLineDash([2 * v.u, 5 * v.u]);
  outlined(ctx, v, () => { ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x1, y1); }, COLORS.ink, 1.5);
  ctx.setLineDash([]);
  const a = Math.atan2(y1 - y0, x1 - x0), L = 9 * v.u;
  outlined(ctx, v, () => {
    ctx.beginPath();
    ctx.moveTo(x1 + Math.cos(a + 2.7) * L, y1 + Math.sin(a + 2.7) * L);
    ctx.lineTo(x1, y1);
    ctx.lineTo(x1 + Math.cos(a - 2.7) * L, y1 + Math.sin(a - 2.7) * L);
  }, COLORS.ink, 1.5);
}

/** Dashed ring where the catalogue motion puts the target at this frame's date. */
export function drawPredicted(ctx, v, px) {
  if (!px) return;
  const [x, y] = toC(v, px);
  const r = Math.max(9 * v.u, 2.5 * v.k);
  ctx.setLineDash([4 * v.u, 3 * v.u]);
  outlined(ctx, v, () => { ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); }, COLORS.predicted, 1.6);
  ctx.setLineDash([]);
}

/** A solid ring around a field mover (fieldmovers.js) at its fitted place on this frame's date. */
export function drawMoverRing(ctx, v, px) {
  if (!px) return;
  const [x, y] = toC(v, px);
  outlined(ctx, v, () => { ctx.beginPath(); ctx.arc(x, y, Math.max(11 * v.u, 3 * v.k), 0, Math.PI * 2); }, COLORS.mover, 1.6);
}

/** All measured centroids as small dots; the current frame's with its error circle. */
export function drawCentroids(ctx, v, frames, current, scale) {
  for (const f of frames) {
    if (!f.centroid_px || f === current) continue;
    const [x, y] = toC(v, f.centroid_px);
    ctx.fillStyle = 'rgba(86, 216, 236, 0.55)';
    ctx.beginPath();
    ctx.arc(x, y, 1.8 * v.u, 0, Math.PI * 2);
    ctx.fill();
  }
  if (!current?.centroid_px) return;
  const [x, y] = toC(v, current.centroid_px);
  const errPx = Number.isFinite(current.centroid_err_arcsec) ? current.centroid_err_arcsec / scale : 0;
  const r = Math.max(errPx * v.k, 3 * v.u);
  outlined(ctx, v, () => { ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); }, COLORS.measured, 1.6);
  const arm = r + 5 * v.u;
  outlined(ctx, v, () => {
    ctx.beginPath();
    ctx.moveTo(x - arm, y); ctx.lineTo(x - r - 1.5 * v.u, y);
    ctx.moveTo(x + r + 1.5 * v.u, y); ctx.lineTo(x + arm, y);
  }, COLORS.measured, 1.6);
}

/** Catalogue sources moved to `year` with their proper motions. shape: 'circle' | 'square'. */
export function drawSources(ctx, v, grid, list, year, color, shape) {
  const r = Math.max(5 * v.u, 1.6 * v.k);
  for (const s of list) {
    const p = sourcePxAt(grid, s, year);
    if (!p) continue;
    const [x, y] = toC(v, p);
    outlined(ctx, v, () => {
      ctx.beginPath();
      if (shape === 'square') ctx.rect(x - r, y - r, 2 * r, 2 * r);
      else ctx.arc(x, y, r, 0, Math.PI * 2);
    }, color, 1.1);
  }
}

const NICE = [0.5, 1, 2, 5, 10, 15, 20, 30, 60, 120, 300, 600];

/** Scale bar (bottom left) sized to roughly a fifth of the visible width. */
export function drawScaleBar(ctx, v, scale, W, H) {
  const visibleArcsec = (W / v.k) * scale;
  const target = visibleArcsec / 5;
  const len = NICE.reduce((best, n) => (Math.abs(n - target) < Math.abs(best - target) ? n : best), NICE[0]);
  const px = (len / scale) * v.k;
  const x = 12 * v.u, y = H - 14 * v.u;
  outlined(ctx, v, () => {
    ctx.beginPath();
    ctx.moveTo(x, y - 4 * v.u); ctx.lineTo(x, y); ctx.lineTo(x + px, y); ctx.lineTo(x + px, y - 4 * v.u);
  }, COLORS.ink, 1.5);
  const label = len >= 60 ? `${len / 60}′` : `${len}″`;
  text(ctx, v, label, x + px / 2, y - 10 * v.u, COLORS.ink, 'center', 11, MONO, 500);
}

/** Arrow at the view edge pointing along (dir.dx, dir.dy) to an object that has left the view. */
export function drawEdgeArrow(ctx, v, dir, W, H) {
  const pad = 22 * v.u;
  const t = Math.min((W / 2 - pad) / Math.max(Math.abs(dir.dx), 1e-6), (H / 2 - pad) / Math.max(Math.abs(dir.dy), 1e-6));
  const x = W / 2 + dir.dx * t, y = H / 2 + dir.dy * t;
  const a = Math.atan2(dir.dy, dir.dx), L = 13 * v.u;
  outlined(ctx, v, () => {
    ctx.beginPath();
    ctx.moveTo(x + Math.cos(a) * L, y + Math.sin(a) * L);
    ctx.lineTo(x + Math.cos(a + 2.5) * L, y + Math.sin(a + 2.5) * L);
    ctx.lineTo(x + Math.cos(a - 2.5) * L, y + Math.sin(a - 2.5) * L);
    ctx.closePath();
  }, COLORS.measured, 2);
}

/** North-up, east-left compass (top right). */
export function drawCompass(ctx, v, W) {
  const L = 22 * v.u, ox = W - 14 * v.u, oy = 14 * v.u + L;
  outlined(ctx, v, () => {
    ctx.beginPath();
    ctx.moveTo(ox, oy); ctx.lineTo(ox, oy - L);
    ctx.moveTo(ox, oy); ctx.lineTo(ox - L, oy);
  }, COLORS.ink, 1.5);
  text(ctx, v, 'N', ox, oy - L - 8 * v.u, COLORS.ink, 'center', 11, MONO, 500);
  text(ctx, v, 'E', ox - L - 8 * v.u, oy, COLORS.ink, 'center', 11, MONO, 500);
}

/**
 * Date, mission and band burned into the frame (top left), so screenshots carry it. The image
 * set's line takes its mission's colour (cyan WISE, amber SPHEREx, as on the timeline), so the
 * hand-over between the two shows in the image itself.
 * @param {string[]} lines the date, then the image set
 * @param {string|null} warn
 * @param {string|null} [mission] 'WISE' | 'SPHEREx' for the frame on screen
 */
export function drawLabel(ctx, v, lines, warn, mission = null) {
  const tint = mission === 'WISE' ? COLORS.wise : mission === 'SPHEREx' ? COLORS.spherex : '#c5ccd8';
  let y = 16 * v.u;
  lines.forEach((s, i) => {
    text(ctx, v, s, 10 * v.u, y, i === 0 ? COLORS.ink : tint, 'left', i === 0 ? 16 : 12, i === 0 ? SANS : MONO, i === 0 ? 600 : 500);
    y += (i === 0 ? 20 : 15) * v.u;
  });
  if (warn) text(ctx, v, `⚠\uFE0E ${warn}`, 10 * v.u, y, COLORS.predicted, 'left', 11);
}

export function drawCrosshair(ctx, v, cx, cy, W, H) {
  ctx.setLineDash([2 * v.u, 3 * v.u]);
  ctx.lineWidth = 1 * v.u;
  ctx.strokeStyle = 'rgba(242, 244, 248, 0.7)';
  ctx.beginPath();
  ctx.moveTo(0, cy); ctx.lineTo(W, cy);
  ctx.moveTo(cx, 0); ctx.lineTo(cx, H);
  ctx.stroke();
  ctx.setLineDash([]);
}
