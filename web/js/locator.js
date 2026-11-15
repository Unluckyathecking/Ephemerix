// "Where on the sky is this": an all-sky inset (Hammer-Aitoff, equatorial, RA increasing to the
// left) with the Milky Way, the ecliptic and this view's position, plus a few plain lines of context.
// Everything is computed here from RA/Dec and the field size; nothing is fetched except the
// site's own gallery index, which marks the other targets.

import { el } from './dom.js';
import { galToEq } from './skymath.js';
import { toSvg, VIEW_W, VIEW_H, CENTER, HALF_W, HALF_H, galacticBandD, galacticLatitudeD, eclipticD, graticuleD } from './allskypaths.js';
import { BRIGHT_STARS } from './brightstars.js';
import { describePosition } from './locatortext.js';

const NS = 'http://www.w3.org/2000/svg';

function svgEl(tag, attrs = {}, children = []) {
  const node = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) if (v != null && v !== false) node.setAttribute(k, String(v));
  for (const c of children) if (c) node.append(c);
  return node;
}

const f1 = (n) => (Math.round(n * 10) / 10).toString();
const text = (str, x, y, cls, anchor = 'start') => {
  const t = svgEl('text', { x: f1(x), y: f1(y), class: cls, 'text-anchor': anchor });
  t.textContent = str;
  return t;
};

/** The fixed backdrop: sky, graticule with sparse labels, band, ecliptic, bright stars, Galactic Centre. */
function backdrop() {
  const g = svgEl('g', { 'aria-hidden': 'true' });
  const outline = { cx: CENTER.x, cy: CENTER.y, rx: HALF_W, ry: f1(HALF_H) };
  g.append(
    svgEl('ellipse', { ...outline, class: 'lm-sky' }),
    svgEl('path', { d: graticuleD(), class: 'lm-grid' }),
    svgEl('path', { d: galacticBandD(20), class: 'lm-band lm-band-wide' }),
    svgEl('path', { d: galacticBandD(10), class: 'lm-band' }),
    svgEl('path', { d: galacticLatitudeD(0), class: 'lm-plane' }),
    svgEl('path', { d: eclipticD(), class: 'lm-ecliptic' }),
  );
  for (const [, ra, dec, mag] of BRIGHT_STARS) {
    const p = toSvg(ra, dec);
    g.append(svgEl('circle', { cx: f1(p.x), cy: f1(p.y), r: f1(Math.min(1.7, Math.max(0.6, 1.1 - 0.25 * mag))), class: 'lm-star' }));
  }
  for (const h of [4, 8, 12, 16, 20]) {
    const p = toSvg(h * 15, 0);
    g.append(text(`${h}h`, p.x, p.y - 2.5, 'lm-label', 'middle'));
  }
  for (const dec of [60, 30, -30, -60]) {
    const p = toSvg(359.99, dec);
    g.append(text(`${dec > 0 ? '+' : '−'}${Math.abs(dec)}°`, p.x - 3, p.y + 3, 'lm-label', 'end'));
  }
  const gc = toSvg(galToEq(0, 0).ra, galToEq(0, 0).dec);
  g.append(svgEl('circle', { cx: f1(gc.x), cy: f1(gc.y), r: 2.6, class: 'lm-gc' }), text('Galactic Centre', gc.x + 5, gc.y + 11, 'lm-label lm-gc-label'));
  g.append(svgEl('ellipse', { ...outline, class: 'lm-frame' }));
  return g;
}

function viewMarker(ra, dec) {
  const p = toSvg(ra, dec);
  return svgEl('g', { class: 'lm-here', 'aria-hidden': 'true', 'data-x': f1(p.x), 'data-y': f1(p.y) }, [
    svgEl('circle', { cx: f1(p.x), cy: f1(p.y), r: 7, class: 'lm-here-ring' }),
    svgEl('circle', { cx: f1(p.x), cy: f1(p.y), r: 2.8, class: 'lm-here-dot' }),
  ]);
}

/** One small linked marker for another gallery target. */
function targetMarker(t, hrefFor) {
  const p = toSvg(t.ra, t.dec);
  const right = p.x > CENTER.x;
  return svgEl('a', { href: hrefFor(t.slug), class: 'lm-target', 'data-slug': t.slug }, [
    svgEl('title', {}, [document.createTextNode(t.name)]),
    svgEl('circle', { cx: f1(p.x), cy: f1(p.y), r: 8, class: 'lm-hit' }),
    svgEl('circle', { cx: f1(p.x), cy: f1(p.y), r: 2.2, class: 'lm-target-dot' }),
    text(t.name, p.x + (right ? -5 : 5), p.y - 5, 'lm-target-name', right ? 'end' : 'start'),
  ]);
}

const keyItem = (cls, label) => el('li', {}, [el('span', { class: `lm-swatch ${cls}`, 'aria-hidden': 'true' }), ` ${label}`]);

/**
 * @param {{ra: number, dec: number, fovArcsec: number, currentSlug?: string|null,
 *   targets?: Promise<Array<{slug: string, name: string, ra: number|null, dec: number|null}>|null>|null,
 *   hrefFor: (slug: string) => string}} o
 * @returns {HTMLElement}
 */
export function locatorPanel({ ra, dec, fovArcsec, currentSlug = null, targets = null, hrefFor }) {
  const info = describePosition(ra, dec, fovArcsec);
  const markers = svgEl('g', { class: 'lm-targets' });
  const svg = svgEl('svg', { viewBox: `0 0 ${VIEW_W} ${VIEW_H}`, class: 'locator-map', role: 'group', 'aria-label': info.label }, [
    backdrop(), markers, viewMarker(ra, dec),
  ]);
  const otherKey = keyItem('lm-key-target', 'Other gallery targets (select to open)');
  otherKey.hidden = true;
  const panel = el('section', { class: 'card locator', 'aria-labelledby': 'locator-h' }, [
    el('h2', { id: 'locator-h', text: 'Where on the sky is this?' }),
    svg,
    el('ul', { class: 'locator-key small muted' }, [
      keyItem('lm-key-here', 'This view'), keyItem('lm-key-band', 'Milky Way'), keyItem('lm-key-ecl', 'Ecliptic'), otherKey,
    ]),
    el('p', { class: 'locator-context', text: info.lines.join(' ') }),
    el('p', { class: 'small muted', text: 'All-sky map in equatorial coordinates, right ascension increasing to the left. Dots are the brightest stars.' }),
    el('p', { class: 'small' }, [el('a', { href: currentSlug ? `explore.html?target=${encodeURIComponent(currentSlug)}` : `explore.html?ra=${ra.toFixed(4)}&dec=${dec.toFixed(4)}&zoom=18`, text: 'See it on the sky map' })]),
  ]);
  Promise.resolve(targets).then((list) => {
    const others = (list || []).filter((t) => t.slug !== currentSlug && t.ra != null && t.dec != null
      && Math.hypot((t.ra - ra) * Math.cos(dec * Math.PI / 180), t.dec - dec) > 0.01);
    for (const t of others) {
      const item = targetMarker(t, hrefFor);
      markers.append(item);
    }
    otherKey.hidden = !others.length;
  }).catch(() => { /* the markers are optional */ });
  return panel;
}
