// Blink state: which frames take part, which one is showing, play/pause and speed.
// No drawing here; the view listens to onChange and redraws.

import { nearestIndex } from './framesets.js';

export class BlinkPlayer {
  /**
   * @param {{onChange: (reason: string) => void, fps?: number}} opts
   */
  constructor({ onChange, fps = 2 }) {
    this.onChange = onChange;
    this.frames = [];
    this.index = 0;
    this.fps = fps;
    this.playing = false;
    this.timer = null;
  }

  get current() { return this.frames[this.index] || null; }

  /** Replace the active frame list, keeping the nearest frame in time. */
  setFrames(frames) {
    const keep = this.current;
    this.frames = frames;
    this.index = keep && frames.length ? nearestIndex(frames, keep.mjd) : 0;
    if (frames.length < 2) this.pause(false);
    this.onChange('frames');
  }

  seekId(id) {
    const i = this.frames.findIndex((f) => f.id === id);
    if (i >= 0) this.seekIndex(i);
    return i >= 0;
  }

  seekIndex(i) {
    if (!this.frames.length) return;
    const next = Math.max(0, Math.min(this.frames.length - 1, i));
    if (next === this.index) return;
    this.index = next;
    this.onChange('seek');
  }

  /** Choose the first frame shown, before playing; out-of-range values are ignored. No URL change. */
  startAt(i) {
    if (!Number.isInteger(i) || i < 0 || i >= this.frames.length || i === this.index) return;
    this.index = i;
    this.onChange('frames');
  }

  step(delta) {
    if (!this.frames.length) return;
    this.pause(false);
    this.index = (this.index + delta + this.frames.length) % this.frames.length;
    this.onChange('step');
  }

  setFps(fps) {
    this.fps = Math.max(0.25, Math.min(12, fps));
    if (this.playing) this.schedule();
  }

  play() {
    if (this.playing || this.frames.length < 2) return;
    this.playing = true;
    this.schedule();
    this.onChange('play');
  }

  pause(notify = true) {
    clearTimeout(this.timer);
    this.timer = null;
    if (!this.playing) return;
    this.playing = false;
    if (notify) this.onChange('pause');
  }

  toggle() { if (this.playing) this.pause(); else this.play(); }

  schedule() {
    clearTimeout(this.timer);
    this.timer = setTimeout(() => {
      if (!this.playing) return;
      this.index = (this.index + 1) % this.frames.length;
      this.onChange('tick');
      this.schedule();
    }, 1000 / this.fps);
  }

  destroy() { this.pause(false); this.onChange = () => {}; }
}

/**
 * Load every frame image before the blink starts, so it never flickers.
 * @returns {Promise<Map<string, HTMLImageElement|null>>} null for images that failed
 */
export async function preloadImages(frames, baseUrl, onProgress = () => {}) {
  let done = 0;
  const entries = await Promise.all(frames.map(async (f) => {
    const img = new Image();
    img.decoding = 'async';
    // Lets the compare mode read pixels of live-API images (served with CORS headers).
    img.crossOrigin = 'anonymous';
    img.src = new URL(f.image, baseUrl).href;
    let ok = null;
    try {
      await img.decode();
      ok = img;
    } catch {
      ok = null;
    }
    done += 1;
    onProgress(done, frames.length);
    return [f.id, ok];
  }));
  return new Map(entries);
}
