// The shared page chrome: header (brand, tagline, navigation) and footer (credits).
// Every page calls mountChrome() once, so the four pages cannot drift apart.

import { el } from './dom.js';
import { SITE, NAV, CREDITS, DISCLAIMER, AI_NOTE } from './site.js';
import { dataStatusLine } from './datastatus.js';
import { modeSwitch } from './mode.js';
import { countVisit } from './visits.js';

const SVG = 'http://www.w3.org/2000/svg';

function svg(tag, attrs, children = []) {
  const node = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  node.append(...children);
  return node;
}

/** The mark: one object at three dates along its track, the latest ringed. */
export function brandMark() {
  return svg('svg', { class: 'brand-mark', viewBox: '0 0 24 24', 'aria-hidden': 'true', focusable: 'false' }, [
    svg('path', { d: 'M2.5 20.5 C 8 18.5, 12.5 14, 16 8', fill: 'none', stroke: 'currentColor', 'stroke-opacity': '.5', 'stroke-width': '1.2' }),
    svg('circle', { cx: '3', cy: '20.3', r: '1.7', fill: 'currentColor', 'fill-opacity': '.45' }),
    svg('circle', { cx: '10.2', cy: '15.6', r: '2.1', fill: 'currentColor', 'fill-opacity': '.7' }),
    svg('circle', { cx: '16', cy: '8', r: '3', fill: 'var(--accent)' }),
    svg('circle', { cx: '16', cy: '8', r: '6.2', fill: 'none', stroke: 'var(--accent)', 'stroke-width': '1.2', 'stroke-dasharray': '2.6 2' }),
  ]);
}

/** The name as a wordmark; a final "x" takes the accent, the nod to SPHEREx. */
export function wordmark() {
  const name = SITE.name;
  const tail = /x$/i.test(name) ? name.slice(-1) : '';
  return el('span', { class: 'wordmark' }, [tail ? name.slice(0, -1) : name, tail ? el('span', { class: 'wordmark-x', text: tail }) : null]);
}

function header(current) {
  return [
    el('a', { class: 'brand', href: './', 'aria-label': `${SITE.name}, home` }, [brandMark(), wordmark()]),
    el('p', { class: 'tagline', text: SITE.tagline }),
    el('nav', { 'aria-label': 'Site' }, NAV.map((n) => el('a', { href: n.href, 'aria-current': n.key === current ? 'page' : null, 'aria-label': n.label }, [
      el('span', { class: 'nav-full', text: n.label }), el('span', { class: 'nav-short', text: n.short }),
    ]))),
    modeSwitch(),
  ];
}

function footer() {
  return [
    el('div', { class: 'foot-brand' }, [
      el('p', { class: 'foot-name' }, [wordmark()]),
      el('p', { text: SITE.gloss }),
      el('p', { text: DISCLAIMER }),
      el('p', { text: AI_NOTE }),
      el('p', { class: 'foot-data', hidden: '' }),
    ]),
    el('div', { class: 'foot-credits' }, [
      el('h2', { text: 'Data and services' }),
      el('ul', {}, CREDITS.map((c) => el('li', { text: c }))),
      el('p', {}, [el('a', { href: 'status.html', text: 'Are the archives answering?' })]), // archive status page
    ]),
  ];
}

/**
 * Fill the page's empty <header class="site"> and <footer class="site">.
 * @param {string|null} current the NAV key of this page, marked aria-current
 */
export function mountChrome(current = null) {
  document.querySelector('header.site')?.replaceChildren(...header(current));
  document.querySelector('footer.site')?.replaceChildren(...footer());
  fillDataStatus();
  countVisit();
}

/** Add the one line on how current the SPHEREx data is; on any failure the footer stays as it was. */
async function fillDataStatus() {
  const slot = document.querySelector('footer.site .foot-data');
  if (!slot) return;
  try {
    const res = await fetch(new URL('data/data-status.json', document.baseURI), { headers: { Accept: 'application/json' } });
    const line = res.ok ? dataStatusLine(await res.json()) : '';
    if (line) { slot.textContent = line; slot.hidden = false; }
  } catch { /* no line rather than a wrong one */ }
}
