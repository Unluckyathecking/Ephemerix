// Date timeline: the full span with a tick per frame, the WISE -> SPHEREx
// handover, and a draggable cursor. Acts as an ARIA slider over active frames.

import { el, shortDate } from './dom.js';
import { decimalYear } from './sky.js';
import { handoverYear, nearestIndex } from './framesets.js';
import { setLabel } from './labels.js';
import { findGaps, gapLabel } from './gaps.js';
import { frameMatters } from './flags.js';

export class Timeline {
  /**
   * @param {HTMLElement} host
   * @param {object[]} frames all frames in the manifest
   * @param {(index: number) => void} onSeek index into the active list
   */
  constructor(host, frames, onSeek) {
    this.frames = frames;
    this.onSeek = onSeek;
    this.active = [];
    const years = frames.map((f) => decimalYear(f.mjd));
    this.y0 = Math.floor(Math.min(...years));
    this.y1 = Math.max(this.y0 + 1, Math.ceil(Math.max(...years) + 0.01));
    this.track = el('div', { class: 'tl-track' });
    this.root = el('div', {
      class: 'timeline', role: 'slider', tabindex: '0', 'aria-label': 'Frame date. Use arrow keys to step.',
    }, [this.track]);
    this.ticks = new Map();
    this.build();
    host.replaceChildren(this.root);
    this.bindPointer();
  }

  pos(year) { return ((year - this.y0) / (this.y1 - this.y0)) * 100; }

  build() {
    const span = this.y1 - this.y0;
    const stepYears = span > 12 ? 2 : 1;
    for (let y = this.y0; y <= this.y1; y += stepYears) {
      this.track.append(el('span', { class: 'tl-year', style: `left:${this.pos(y)}%`, text: String(y), 'aria-hidden': 'true' }));
    }
    const h = handoverYear(this.frames);
    if (h != null) {
      this.track.append(el('span', { class: 'tl-handover', style: `left:${this.pos(h)}%`, 'aria-hidden': 'true' },
        [el('span', { text: 'WISE → SPHEREx' })]));
    }
    for (const f of this.frames) {
      const tick = el('span', {
        class: `tl-tick ${f.mission === 'SPHEREx' ? 'spx' : 'wise'}${frameMatters(f).length ? ' warn' : ''}`,
        style: `left:${this.pos(decimalYear(f.mjd))}%`,
        title: `${shortDate(f.date)} · ${setLabel(f)}${frameMatters(f).length ? ` · ⚠ ${frameMatters(f).join(', ')}` : ''}`,
      });
      this.ticks.set(f.id, tick);
      this.track.append(tick);
    }
    this.cursor = el('span', { class: 'tl-cursor', 'aria-hidden': 'true' });
    this.track.append(this.cursor);
  }

  /** Shade every stretch with no images among the selected sets. */
  renderGaps(active) {
    for (const g of this.gapEls || []) g.remove();
    this.gapEls = findGaps(active).map((g) => el('span', {
      class: 'tl-gap', style: `left:${this.pos(g.ya)}%;width:${this.pos(g.yb) - this.pos(g.ya)}%`,
      title: `${gapLabel(g)} in the selected image sets, so one step of the blink spans ${g.years.toFixed(0)} years.`,
    }, [el('span', { text: gapLabel(g) })]));
    this.track.prepend(...this.gapEls);
  }

  update(active, current) {
    if (active !== this.active) this.renderGaps(active);
    this.active = active;
    const on = new Set(active.map((f) => f.id));
    for (const [id, t] of this.ticks) {
      t.classList.toggle('on', on.has(id));
      t.classList.toggle('now', current?.id === id);
    }
    if (!current) return;
    this.cursor.style.left = `${this.pos(decimalYear(current.mjd))}%`;
    const i = active.indexOf(current);
    this.root.setAttribute('aria-valuemin', '0');
    this.root.setAttribute('aria-valuemax', String(Math.max(0, active.length - 1)));
    this.root.setAttribute('aria-valuenow', String(Math.max(0, i)));
    this.root.setAttribute('aria-valuetext', `${shortDate(current.date)}, ${setLabel(current)}`);
  }

  bindPointer() {
    const seekAt = (e) => {
      if (!this.active.length) return;
      const r = this.track.getBoundingClientRect();
      const frac = Math.min(1, Math.max(0, (e.clientX - r.left) / r.width));
      const year = this.y0 + frac * (this.y1 - this.y0);
      const mjd = 51544.5 + (year - 2000) * 365.25;
      this.onSeek(nearestIndex(this.active, mjd));
    };
    let down = false;
    this.root.addEventListener('pointerdown', (e) => {
      down = true;
      this.root.setPointerCapture(e.pointerId);
      seekAt(e);
    });
    this.root.addEventListener('pointermove', (e) => { if (down) seekAt(e); });
    const up = () => { down = false; };
    this.root.addEventListener('pointerup', up);
    this.root.addEventListener('pointercancel', up);
    this.root.addEventListener('keydown', (e) => {
      if (e.key === 'Home') { this.onSeek(0); e.preventDefault(); }
      if (e.key === 'End') { this.onSeek(this.active.length - 1); e.preventDefault(); }
    });
  }
}
