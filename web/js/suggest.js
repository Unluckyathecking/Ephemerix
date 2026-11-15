// Suggestions under the search box, from the offline name index (data/names.json), plus a plain
// line saying how a typed position was read. Fails soft: without the index the form works as before.

import { el } from './dom.js';
import { buildIndex, searchNames, nearGallery } from './nameindex.js';
import { readPosition } from './posparse.js';
import { serializeState, emptyState } from './urlstate.js';


const LIVE = 'Built live, about a minute';
const INSTANT = 'Opens instantly';
let indexPromise = null;

/** The index, fetched once per page; [] when it cannot be read. */
export function loadNameIndex() {
  indexPromise ??= fetch(new URL('data/names.json', document.baseURI), { headers: { Accept: 'application/json' } })
    .then((r) => (r.ok ? r.json() : null)).then(buildIndex, () => []);
  return indexPromise;
}

/** The address of the view an index entry opens; null when it cannot be opened here. */
export function entryHref(entry, gallerySlugs) {
  if (entry.slug && gallerySlugs.has(entry.slug)) return serializeState({ ...emptyState(), target: entry.slug });
  if (!Number.isFinite(entry.ra) || !Number.isFinite(entry.dec)) return null;
  const pm = Number.isFinite(entry.pmra) && Number.isFinite(entry.pmdec);
  return serializeState({ ...emptyState(), ra: entry.ra, dec: entry.dec, fov: 240,
    ...(pm ? { pmra: entry.pmra, pmdec: entry.pmdec, epoch: 2000 } : {}), label: entry.label });
}

function option(id, { name, also, when, instant }) {
  return el('li', { id, role: 'option', 'aria-selected': 'false' }, [
    el('span', { class: 'sg-name', text: name }),
    also ? el('span', { class: 'sg-also', text: also }) : null,
    el('span', { class: `sg-when${instant ? ' instant' : ''}`, text: when }),
  ]);
}

/** The options for what is typed: a position first when it reads as one, then index matches. */
function choices(text, index, slugs, apiBase) {
  const out = [];
  const pos = readPosition(text);
  const near = pos?.ok ? nearGallery(index, pos.ra, pos.dec, slugs) : null;
  if (near) {
    // A position on a built target's path (the brief's own coordinates, say) opens that view.
    out.push({ name: near.entry.label, also: `Your position is ${near.arcsec < 1 ? 'under 1' : near.arcsec.toFixed(0)} arcsec from its path since 2010 · a built view`,
      when: INSTANT, instant: true, href: serializeState({ ...emptyState(), target: near.entry.slug }), live: false, score: 100 });
  }
  if (pos?.ok) {
    out.push({ name: 'This position', also: pos.said, when: apiBase ? LIVE : 'Needs the live server',
      href: serializeState({ ...emptyState(), ra: +pos.ra.toFixed(7), dec: +pos.dec.toFixed(7), fov: 240 }), live: true });
  }
  for (const h of pos ? [] : searchNames(index, text)) {
    const href = entryHref(h.entry, slugs);
    if (!href) continue;
    const instant = !!h.entry.slug && slugs.has(h.entry.slug);
    const kind = h.entry.kind + (h.entry.sp_type ? `, ${h.entry.sp_type}` : '');
    out.push({ name: h.entry.label, also: h.alias ? `${h.alias} · ${kind}` : kind, when: instant ? INSTANT : apiBase ? LIVE : 'Needs the live server',
      instant, href, live: !instant, score: h.score });
  }
  const said = !pos ? '' : !pos.ok ? pos.message : near ? `${pos.said} That is ${near.entry.label}, a built view.` : pos.said;
  return { out, pos, said };
}

/**
 * Attach suggestions to the search input.
 * @param {{input: HTMLInputElement, apiBase: string, gallery: Promise<object[]|null>, active: () => boolean,
 *   onLiveOffline: () => void}} opts  active: false while the box is in Solar System body mode
 * @returns {{node: HTMLElement, understood: HTMLElement, best: () => object|null}} best: a strong match to open on submit
 */
export function attachSuggest({ input, apiBase, gallery, active, onLiveOffline }) {
  const list = el('ul', { class: 'suggest', id: 'pos-suggest', role: 'listbox', 'aria-label': 'Suggestions', hidden: true });
  const understood = el('p', { class: 'understood', 'aria-live': 'polite', hidden: true });
  input.setAttribute('role', 'combobox');
  input.setAttribute('aria-autocomplete', 'list');
  input.setAttribute('aria-controls', list.id);
  input.setAttribute('aria-expanded', 'false');
  let index = [], slugs = new Set(), items = [], cur = -1;
  loadNameIndex().then((i) => { index = i; });
  Promise.resolve(gallery).then((ts) => { slugs = new Set((ts || []).map((t) => t.slug)); }, () => {});

  // While the list is open, the lines it covers (the help line, the mode hint) step aside.
  const open = (on) => { list.hidden = !on; document.body.classList.toggle('suggest-open', on); };
  const close = () => { open(false); input.setAttribute('aria-expanded', 'false'); input.removeAttribute('aria-activedescendant'); cur = -1; };
  const go = (c) => { if (c.live && !apiBase) { close(); onLiveOffline(c); return; } window.location.search = c.href; };
  const highlight = (i) => {
    cur = i;
    [...list.children].forEach((li, k) => li.setAttribute('aria-selected', String(k === i)));
    if (i >= 0) input.setAttribute('aria-activedescendant', list.children[i].id); else input.removeAttribute('aria-activedescendant');
  };
  const update = () => {
    if (!active()) { close(); understood.hidden = true; return; }
    const { out, pos, said } = choices(input.value, index, slugs, apiBase);
    understood.hidden = !pos;
    understood.textContent = said;
    items = out;
    list.replaceChildren(...out.map((c, i) => {
      const li = option(`pos-sg-${i}`, c);
      li.addEventListener('mousedown', (e) => { e.preventDefault(); go(c); });
      return li;
    }));
    open(out.length > 0);
    input.setAttribute('aria-expanded', String(!!out.length));
    highlight(-1);
  };
  input.addEventListener('input', update);
  input.addEventListener('focus', () => { if (input.value.trim()) update(); });
  input.addEventListener('blur', () => setTimeout(close, 100));
  input.addEventListener('keydown', (e) => {
    if (list.hidden || !items.length) return;
    const n = items.length;
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') highlight(e.key === 'ArrowDown' ? (cur + 1) % n : (cur - 1 + n) % n);
    else if (e.key === 'Enter' && cur >= 0) go(items[cur]);
    else if (e.key === 'Escape') close();
    else return;
    e.preventDefault();
  });
  return { node: list, understood, best: () => bestChoice(items, apiBase), go };
}

/** The choice to open when the form is sent without picking one: a strong name match, else null. */
export function bestChoice(items, apiBase) {
  const top = items[0];
  if (!top?.score) return null; // a typed position goes through the form's own checks
  return top.score >= (top.live ? 80 : 50) && (!top.live || apiBase) ? top : null;
}
