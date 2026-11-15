// DOM pieces of the sky map page: the small card, the text list of marked objects and the search
// results. All text goes in through textContent (el()); gallery strings are treated as untrusted.

import { el } from './dom.js';
import { constellationOf } from './constellation.js';
import { pinText, buildHref, viewHref, targetLines, liveHref, knownLines, nameHref } from './exploretext.js';

// Same headings as the gallery (gallery.js GROUP_HEADINGS), kept here so this page does not load the gallery code.
const GROUP_HEADINGS = {
  brief: 'From the challenge brief',
  'backyard-worlds': 'Backyard Worlds discoveries',
  benchmark: 'Brown dwarfs with published spectral types',
  'solar-system': 'Solar System objects',
};
const groupHeading = (g) => GROUP_HEADINGS[g] || null;

const closeButton = (onClose) => el('button', { type: 'button', class: 'ex-close', 'aria-label': 'Close', onclick: onClose }, ['×']);

/** Card for a prebuilt view. `manifest` may arrive later; call again to refresh. */
export function targetCard(t, manifest, onClose) {
  const thumb = t.thumb ? el('img', { class: 'ex-thumb', src: `gallery/${t.thumb}`, alt: '', width: 72, height: 72, loading: 'lazy' }) : null;
  return [
    closeButton(onClose),
    el('div', { class: 'ex-card-head' }, [
      thumb,
      el('div', {}, [
        el('p', { class: 'ex-kicker', text: 'We have images of this' }),
        el('h2', { class: 'ex-card-title', text: t.name }),
      ]),
    ]),
    ...targetLines(t, manifest).map((line) => el('p', { class: 'ex-line', text: line })),
    el('a', { class: 'btn primary ex-go', href: viewHref(t.slug) }, ['Watch it move']),
  ];
}

/** Card for an object from the name index that we build live. */
export function knownCard(k, epoch, onClose) {
  const p = pinText(k.ra, k.dec);
  return [
    closeButton(onClose),
    el('p', { class: 'ex-kicker ex-kicker-live', text: 'We can build this' }),
    el('h2', { class: 'ex-card-title', text: k.label }),
    ...knownLines(k.entry).map((line) => el('p', { class: 'ex-line', text: line })),
    el('p', { class: 'ex-where' }, [p.where, el('span', { class: 'muted', text: ` in ${constellationOf(k.ra, k.dec).name}` })]),
    el('a', { class: 'btn primary ex-go', href: liveHref(k.entry, epoch) }, ['Build the view (about a minute)']),
  ];
}

/** Card for a pin on empty sky, or on a named star. */
export function pinCard(pos, star, onClose) {
  const p = pinText(pos.ra, pos.dec);
  const title = star ? star.name : p.title;
  const lines = star
    ? [`A star of magnitude ${star.mag.toFixed(1)} in ${constellationOf(star.ra, star.dec).name}. We have not built a view here yet.`]
    : ['We have not built a view here yet.'];
  return [
    closeButton(onClose),
    el('p', { class: 'ex-kicker', text: star ? 'Star' : 'Pin' }),
    el('h2', { class: 'ex-card-title', text: title }),
    ...lines.map((line) => el('p', { class: 'ex-line', text: line })),
    el('p', { class: 'ex-where' }, [p.where, el('span', { class: 'muted', text: ` (${p.degrees})` })]),
    // A named star opens by its name, exactly as the search box would (index.html?name=); a bare pin by position.
    el('a', { class: 'btn primary ex-go', href: star?.name ? nameHref(star.name, { ra: star.ra, dec: star.dec }) : buildHref(pos.ra, pos.dec) }, ['Build the view here (about a minute)']),
  ];
}

/** The text alternative to the canvas: every marked object, grouped as in the gallery. */
export function targetList(targets, onShow) {
  const groups = new Map();
  for (const t of targets) {
    const key = t.group || '';
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(t);
  }
  return [...groups].map(([group, list]) => el('div', { class: 'ex-group' }, [
    el('h3', { text: groupHeading(group) || 'Other views' }),
    el('ul', {}, list.map((t) => el('li', {}, [
      el('a', { href: viewHref(t.slug), text: t.name }),
      el('span', { class: 'muted small', text: ` in ${constellationOf(t.ra, t.dec).name}` }),
      el('button', { type: 'button', class: 'ex-show', onclick: () => onShow(t), 'aria-label': `Show ${t.name} on the map` }, ['Show on map']),
    ]))),
  ]));
}

/** The text list of objects we can build live. */
export function knownList(known, onShow) {
  return [el('ul', {}, known.map((k) => el('li', {}, [
    el('span', { class: 'ex-known-name', text: k.label }),
    el('span', { class: 'muted small', text: ` in ${constellationOf(k.ra, k.dec).name}` }),
    el('button', { type: 'button', class: 'ex-show', onclick: () => onShow(k), 'aria-label': `Show ${k.label} on the map` }, ['Show on map']),
  ])))];
}

const KIND_WORD = { target: 'Ready to watch', known: 'Builds in a minute', star: 'Star', constellation: 'Constellation', position: 'Position' };

/** Search result options. */
export function resultItems(results, active, onPick) {
  return results.map((r, i) => el('li', {
    role: 'option', id: `ex-opt-${i}`, class: 'ex-opt', 'aria-selected': i === active ? 'true' : 'false',
    onmousedown: (e) => { e.preventDefault(); onPick(r); },
  }, [el('span', {}, [r.label, r.alias ? el('span', { class: 'muted', text: ` (${r.alias})` }) : null]),
    el('span', { class: 'ex-kind', text: KIND_WORD[r.kind] || '' })]));
}
