// The blink canvas: crisp pixels, zoom and pan, overlays and a crosshair readout.

import { gridOf, pxToSky, decimalYear } from './sky.js';
import * as O from './overlays.js';
import { GAP_KEY, hatchCanvas } from './gaphatch.js';
import { moverPx } from './fieldmovers.js';
import { shortDate, prefersReducedMotion } from './dom.js';
import { setLabel } from './labels.js';
import { viewRect, canvasToImage, clampCentre, clampZoom, zoomAnchored, objectPx, offscreenDirection } from './framing.js';

const PAN_MS = 160;

export class Stage {
  /**
   * @param {HTMLCanvasElement} canvas
   * @param {object} manifest validated manifest
   * @param {Map<string, HTMLImageElement|null>} images
   * @param {{onHover?: (sky: {ra:number, dec:number}|null) => void, compact?: boolean,
   *   onZoom?: (zoom: number) => void, onOffscreen?: (off: boolean) => void}} opts
   */
  constructor(canvas, manifest, images, { onHover = () => {}, compact = false, onZoom = () => {}, onOffscreen = () => {} } = {}) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.m = manifest;
    this.grid = gridOf(manifest);
    this.lastYear = manifest.frames.length ? decimalYear(Math.max(...manifest.frames.map((f) => f.mjd))) : null;
    this.images = images;
    this.onHover = onHover;
    this.compact = compact;
    this.onZoom = onZoom;
    this.onOffscreen = onOffscreen;
    this.follow = false;
    this.offscreen = false;
    this.tween = null;
    this.gapPath = null;
    this.zoom = 1;
    this.cx = manifest.size_px / 2;
    this.cy = manifest.size_px / 2;
    this.layers = { gaps: true, track: true, predicted: true, centroids: true, gaia: false, catwise: false, scale: true };
    this.movers = new Set(); // indexes into manifest.field_movers.movers ringed on the blink (fieldmovers.js)
    this.hatches = new Map(); // frame id -> hatch canvas (gaphatch.js), built on first use
    this.frame = null;
    this.active = [];
    this.override = null; // {canvas, frame, lines, active}: a computed image shown instead of the frame
    this.hover = null;
    this.ro = new ResizeObserver(() => this.resize());
    this.ro.observe(canvas);
    if (!compact) this.bindPointer();
    this.resize();
  }

  resize() {
    const css = this.canvas.clientWidth || this.m.size_px;
    const dpr = window.devicePixelRatio || 1;
    const px = Math.max(1, Math.round(css * dpr));
    if (this.canvas.width !== px) {
      this.canvas.width = px;
      this.canvas.height = px;
    }
    this.draw();
  }

  /** Zoom to z (clamped), keeping the image point at canvas fraction (fx, fy) where it is. */
  setZoom(z, fx = 0.5, fy = 0.5) {
    const z1 = clampZoom(z);
    [this.cx, this.cy] = zoomAnchored(this.m.size_px, this.zoom, this.cx, this.cy, z1, fx, fy);
    this.zoom = z1;
    this.settle();
    this.onZoom(z1);
    this.draw();
  }

  /** Set zoom and centre outright (default framing, "Fit track"). */
  setView(zoom, cx, cy) {
    this.zoom = clampZoom(zoom);
    this.cx = cx;
    this.cy = cy;
    this.settle();
    this.onZoom(this.zoom);
    this.draw();
  }

  clampPan() {
    [this.cx, this.cy] = clampCentre(this.m.size_px, this.zoom, this.cx, this.cy);
  }

  /** Follow mode keeps the object centred (the edge of the image may then show as empty sky). */
  setFollow(on) {
    this.follow = on;
    this.settle();
    this.draw();
  }

  /** After a change of zoom or mode: re-centre on the object when following, else keep inside the image. */
  settle() {
    const p = this.follow && objectPx(this.frame);
    if (p) { this.cx = p[0]; this.cy = p[1]; } else if (!this.follow) this.clampPan();
  }

  /** Pan so the current frame's object is at the centre of the view. */
  recentre() {
    const p = objectPx(this.frame);
    if (!p) return;
    this.cx = p[0];
    this.cy = p[1];
    this.clampPan();
    this.draw();
  }

  view() {
    const v = viewRect(this.m.size_px, this.zoom, this.cx, this.cy, this.canvas.width);
    return { ...v, u: window.devicePixelRatio || 1 };
  }

  /** Glide the view to the object over a moment (instantly with reduced motion). */
  panTo(tx, ty) {
    if (this.tween) cancelAnimationFrame(this.tween.id);
    if (prefersReducedMotion() || this.compact) { this.cx = tx; this.cy = ty; this.tween = null; return; }
    const from = [this.cx, this.cy], t0 = performance.now();
    const step = (now) => {
      const t = Math.min(1, (now - t0) / PAN_MS);
      this.cx = from[0] + (tx - from[0]) * t;
      this.cy = from[1] + (ty - from[1]) * t;
      this.draw();
      this.tween = t < 1 ? { id: requestAnimationFrame(step) } : null;
    };
    this.tween = { id: requestAnimationFrame(step) };
  }

  show(frame, active) {
    this.frame = frame;
    this.active = active;
    const p = this.follow && !this.override && objectPx(frame);
    if (p) this.panTo(p[0], p[1]);
    this.draw();
  }

  /** The straight predicted path across a long gap in time ({from, to} in image pixels), or null. */
  setGapPath(g) {
    this.gapPath = g;
    this.draw();
  }

  /** Show a computed image (difference or sum) in place of the frame; null restores the blink. */
  setOverride(o) {
    this.override = o;
    this.draw();
  }

  draw() {
    const { ctx, canvas } = this;
    const W = canvas.width, H = canvas.height;
    const v = this.view();
    ctx.imageSmoothingEnabled = false;
    ctx.fillStyle = '#05070c';
    ctx.fillRect(0, 0, W, H);
    const o = this.override;
    const f = o ? o.frame : this.frame;
    if (!f) return;
    const img = o ? o.canvas : this.images.get(f.id);
    if (img) {
      const sx = (img.naturalWidth || img.width) / this.m.size_px;
      ctx.drawImage(img, v.x0 * sx, v.y0 * sx, v.w * sx, v.w * sx, 0, 0, W, H);
      const hatch = !o && this.layers.gaps ? this.hatchFor(f) : null;
      if (hatch) {
        const hx = hatch.width / this.m.size_px;
        ctx.drawImage(hatch, v.x0 * hx, v.y0 * hx, v.w * hx, v.w * hx, 0, 0, W, H);
      }
    } else {
      ctx.fillStyle = '#c5ccd8';
      ctx.font = `${13 * v.u}px "IBM Plex Sans", ui-sans-serif, system-ui, sans-serif`;
      ctx.textAlign = 'center';
      ctx.fillText('Image missing for this frame', W / 2, H / 2);
    }
    const L = this.layers;
    const year = decimalYear(f.mjd);
    if (L.gaia) O.drawSources(ctx, v, this.grid, this.m.overlays.gaia, year, O.COLORS.gaia, 'circle');
    if (L.catwise) O.drawSources(ctx, v, this.grid, this.m.overlays.catwise, year, O.COLORS.catwise, 'square');
    const ring = L.predicted && f.predicted_px ? [(f.predicted_px[0] - v.x0) * v.k, (f.predicted_px[1] - v.y0) * v.k] : null;
    if (L.track) O.drawTrack(ctx, v, O.trackUntil(this.m.track, this.lastYear), ring);
    if (this.gapPath && !this.follow && !o) O.drawGapPath(ctx, v, this.gapPath.from, this.gapPath.to);
    if (L.centroids) O.drawCentroids(ctx, v, o ? o.active : this.active, f, this.grid.scale);
    if (L.predicted) O.drawPredicted(ctx, v, f.predicted_px);
    for (const i of this.movers) {
      const mv = this.m.field_movers?.movers[i];
      if (mv) O.drawMoverRing(ctx, v, moverPx(mv, year, this.grid.scale));
    }
    if (L.scale) {
      O.drawScaleBar(ctx, v, this.grid.scale, W, H);
      O.drawCompass(ctx, v, W);
    }
    const lines = o ? o.lines : this.compact
      ? [String(new Date(f.date).getUTCFullYear()), setLabel(f)]
      : [shortDate(f.date), setLabel(f)];
    O.drawLabel(ctx, v, lines, null, o ? null : f.mission);
    if (!this.compact) this.publishView(v, o ? null : objectPx(f));
    this.drawEdgeArrow(ctx, v, o ? null : objectPx(f), W, H);
    if (this.hover) O.drawCrosshair(ctx, v, this.hover[0], this.hover[1], W, H);
  }

  /** The hatch over a frame's no-data pixels, or null when it has none (or its mask did not load). */
  hatchFor(f) {
    if (!f.gaps_image) return null;
    if (!this.hatches.has(f.id)) {
      const mask = this.images.get(GAP_KEY(f.id));
      this.hatches.set(f.id, mask ? hatchCanvas(mask) : null);
    }
    return this.hatches.get(f.id);
  }

  /** Plain data attributes for the page's own checks: the zoom and where the object sits in the view (0 to 1). */
  publishView(v, p) {
    this.canvas.dataset.zoom = this.zoom.toFixed(2);
    this.canvas.dataset.object = p ? `${((p[0] - v.x0) / v.w).toFixed(3)},${((p[1] - v.y0) / v.w).toFixed(3)}` : '';
  }

  /** In fixed-sky view, an arrow at the edge pointing to an object that has left the view. */
  drawEdgeArrow(ctx, v, p, W, H) {
    const dir = !this.follow && !this.compact && p ? offscreenDirection(v, p[0], p[1]) : null;
    if (dir) O.drawEdgeArrow(ctx, v, dir, W, H);
    if (!!dir !== this.offscreen) {
      this.offscreen = !!dir;
      this.onOffscreen(this.offscreen);
    }
  }

  bindPointer() {
    const c = this.canvas;
    const pointers = new Map(); // active touch pointers -> canvas position
    let drag = null;
    let pinch = null;
    const toCanvas = (e) => {
      const r = c.getBoundingClientRect();
      return [((e.clientX - r.left) / r.width) * c.width, ((e.clientY - r.top) / r.height) * c.height];
    };
    const frac = ([x, y]) => [x / c.width, y / c.height];
    const pinchState = () => {
      const [a, b] = [...pointers.values()];
      return { d: Math.hypot(a[0] - b[0], a[1] - b[1]) || 1, mid: [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2] };
    };
    c.addEventListener('pointermove', (e) => {
      const pos = toCanvas(e);
      if (pointers.has(e.pointerId)) {
        pointers.set(e.pointerId, pos);
        if (pinch && pointers.size === 2) {
          const now = pinchState();
          const [fx, fy] = frac(now.mid);
          this.setZoom(pinch.zoom * (now.d / pinch.d), fx, fy);
          return;
        }
      }
      const v = this.view();
      if (drag && !this.follow) {
        this.cx = drag.cx - (pos[0] - drag.x) / v.k;
        this.cy = drag.cy - (pos[1] - drag.y) / v.k;
        this.clampPan();
      }
      this.hover = e.pointerType === 'touch' ? null : pos;
      const [ix, iy] = canvasToImage(v, pos[0], pos[1]);
      this.onHover(pxToSky(this.grid, ix, iy));
      this.draw();
    });
    c.addEventListener('pointerdown', (e) => {
      const pos = toCanvas(e);
      if (e.pointerType === 'touch') {
        // One finger scrolls the page; two fingers pinch the image.
        pointers.set(e.pointerId, pos);
        if (pointers.size === 2) {
          pinch = { ...pinchState(), zoom: this.zoom };
          c.setPointerCapture(e.pointerId);
        }
        return;
      }
      if (this.zoom <= 1) return;
      drag = { x: pos[0], y: pos[1], cx: this.cx, cy: this.cy };
      c.setPointerCapture(e.pointerId);
    });
    const end = (e) => {
      pointers.delete(e.pointerId);
      if (pointers.size < 2) pinch = null;
      drag = null;
    };
    c.addEventListener('pointerup', end);
    c.addEventListener('pointercancel', end);
    c.addEventListener('pointerleave', () => {
      drag = null;
      this.hover = null;
      this.onHover(null);
      this.draw();
    });
    // Wheel zooms only with Ctrl/Cmd (a trackpad pinch arrives that way) or while the image has
    // focus, so an ordinary scroll over the image still scrolls the page.
    c.addEventListener('wheel', (e) => {
      if (!(e.ctrlKey || e.metaKey || document.activeElement === c)) return;
      e.preventDefault();
      const [fx, fy] = frac(toCanvas(e));
      this.setZoom(this.zoom * Math.exp(-e.deltaY * (e.ctrlKey ? 0.01 : 0.002)), fx, fy);
    }, { passive: false });
    c.addEventListener('keydown', (e) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === '+' || e.key === '=') this.setZoom(this.zoom * 1.25);
      else if (e.key === '-' || e.key === '_') this.setZoom(this.zoom / 1.25);
      else return;
      e.preventDefault();
    });
  }

  destroy() { this.ro.disconnect(); }
}
