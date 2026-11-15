// Where the stage looks: the one sky-to-view transform, the default zoom that keeps the whole
// path in view, and the rules for following the object. Pure.

export const MIN_ZOOM = 1;
export const MAX_ZOOM = 8;
const ZOOM_GRID = 0.05;
export const DEFAULT_MAX_ZOOM = 2;
const MARGIN_FRAC = 0.12;
const MIN_MARGIN_PX = 8;

export const clampZoom = (z) => Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, Number.isFinite(z) ? z : MIN_ZOOM));

/**
 * New view centre after zooming from z0 to z1 with the image point under canvas fraction
 * (fx, fy) (0.5, 0.5 is the middle) held still, clamped to the image.
 */
export function zoomAnchored(sizePx, z0, cx, cy, z1, fx = 0.5, fy = 0.5) {
  const w0 = sizePx / z0, w1 = sizePx / z1;
  const px = cx + (fx - 0.5) * w0, py = cy + (fy - 0.5) * w0;
  return [px - (fx - 0.5) * w1, py - (fy - 0.5) * w1];
}

/** The view of a size_px square image at a zoom, centred on (cx, cy), drawn on a canvas `canvasPx` wide. */
export function viewRect(sizePx, zoom, cx, cy, canvasPx) {
  const w = sizePx / zoom;
  return { x0: cx - w / 2, y0: cy - w / 2, w, k: canvasPx / w };
}

/** Image pixel -> canvas pixel under a view from viewRect. */
export function imageToCanvas(v, px, py) {
  return [(px - v.x0) * v.k, (py - v.y0) * v.k];
}

/** Canvas pixel -> image pixel (the inverse of imageToCanvas). */
export function canvasToImage(v, x, y) {
  return [v.x0 + x / v.k, v.y0 + y / v.k];
}

/** Keep the view inside the image: the centre stays at least half a view from each edge. */
export function clampCentre(sizePx, zoom, cx, cy) {
  const half = sizePx / zoom / 2;
  const lim = (c) => Math.min(sizePx - half, Math.max(half, c));
  return [lim(cx), lim(cy)];
}

/** Where the object is on a frame: the measured spot when there is one, else the prediction. */
export function objectPx(f) {
  return f?.centroid_px || f?.predicted_px || null;
}

/** True when some frame gives a position to follow. */
export function canFollow(frames) {
  return frames.some((f) => objectPx(f));
}

/**
 * Whether the point is outside the view (with an inset), and the direction to it from the
 * view's centre as a unit vector in image axes.
 * @returns {{dx: number, dy: number}|null} null when the point is in view
 */
export function offscreenDirection(v, px, py, inset = 0) {
  const x1 = v.x0 + v.w, y1 = v.y0 + v.w;
  const inside = px >= v.x0 + inset && px <= x1 - inset && py >= v.y0 + inset && py <= y1 - inset;
  if (inside) return null;
  const dx = px - (v.x0 + v.w / 2), dy = py - (v.y0 + v.w / 2);
  const n = Math.hypot(dx, dy) || 1;
  return { dx: dx / n, dy: dy / n };
}

/**
 * The zoom and centre that put every frame's position (measured or predicted) in view with a
 * margin: the largest zoom (in steps of 0.05) at which that holds, 1 if none does.
 * @returns {{zoom: number, fitZoom: number, cx: number, cy: number}} `zoom` is capped at
 *   `maxZoom`; `fitZoom` is the largest zoom at which the whole path fits (the auto-follow threshold).
 */
export function defaultFraming(m, { maxZoom = DEFAULT_MAX_ZOOM } = {}) {
  const size = m.size_px;
  const pts = [];
  for (const f of m.frames) {
    if (f.predicted_px) pts.push(f.predicted_px);
    if (f.centroid_px) pts.push(f.centroid_px);
  }
  if (!pts.length) return { zoom: 1, fitZoom: 1, cx: size / 2, cy: size / 2 };
  const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
  const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const extent = Math.max(x1 - x0, y1 - y0);
  const margin = Math.max(MIN_MARGIN_PX, extent * MARGIN_FRAC);
  const bx = (x0 + x1) / 2, by = (y0 + y1) / 2;
  const fits = (z) => {
    // The centre is clamped to the image; the path must still sit inside after that shift.
    const [cx, cy] = clampCentre(size, z, bx, by);
    const half = size / z / 2 - margin;
    return x0 >= cx - half && x1 <= cx + half && y0 >= cy - half && y1 <= cy + half;
  };
  let fitZoom = MIN_ZOOM;
  for (let z = MAX_ZOOM; z > MIN_ZOOM; z -= ZOOM_GRID) {
    if (fits(z)) { fitZoom = Math.round(z / ZOOM_GRID) * ZOOM_GRID; break; }
  }
  const zoom = Math.min(fitZoom, maxZoom);
  const [cx, cy] = clampCentre(size, zoom, bx, by);
  return { zoom, fitZoom, cx, cy };
}

/** Zooming in past the level at which the whole path fits switches Follow on. */
export function shouldAutoFollow(zoom, fitZoom, followable) {
  return followable && zoom > fitZoom;
}
