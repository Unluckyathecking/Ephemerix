// After a control under the image changes what the image shows, bring the image back on screen
// if its top edge or most of it has scrolled away, so the result can be watched.

import { prefersReducedMotion } from './dom.js';

const MIN_VISIBLE = 0.6; // share of the image that must be on screen to leave the page alone

/**
 * Does an element spanning [top, bottom] (viewport px) need scrolling to be watched?
 * @param {number} top
 * @param {number} bottom
 * @param {number} viewH viewport height
 * @returns {boolean}
 */
export function needsScroll(top, bottom, viewH) {
  const h = bottom - top;
  if (h <= 0) return false;
  if (top < 0) return true; // the date and the set name are written along the top edge
  const seen = Math.min(bottom, viewH) - Math.max(top, 0);
  return seen / Math.min(h, viewH) < MIN_VISIBLE;
}

/** Scroll `node` (the stage) into view when needs be: instant under reduced motion. */
export function keepInView(node) {
  const r = node.getBoundingClientRect();
  if (!needsScroll(r.top, r.bottom, window.innerHeight)) return;
  node.scrollIntoView({ block: r.top < 0 ? 'start' : 'end', behavior: prefersReducedMotion() ? 'auto' : 'smooth' });
}
