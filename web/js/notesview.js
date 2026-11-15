// The "Data-quality notes and flags" disclosure (the brief's "contamination flags"): collapsed, with the count showing, and only a short
// line visible for a note that changes how the view should be read.

import { el } from './dom.js';

/** @param {ReturnType<import('./notes.js').summariseNotes>} n */
export function notesBar(n) {
  if (!n.count && !n.degradedLine) return null;
  return el('section', { class: 'card notes', 'aria-label': 'Data-quality notes and flags' }, [
    n.headlines.length ? el('ul', { class: 'notes-lines' }, n.headlines.map((h) => el('li', { text: h }))) : null,
    el('details', { class: 'notes-more' }, [
      el('summary', { text: `Data-quality notes and flags (${n.count})` }),
      n.degradedLine ? el('p', { class: 'small muted notes-degraded', text: n.degradedLine }) : null,
      el('ul', { class: 'small' }, n.all.map((w) => el('li', { text: w }))),
    ]),
  ]);
}
