// The top of a view: title, position, the share actions, and the verdict strip that says
// the answer (motion, spectrum, data) before anything else on the page.

import { fieldHeadline } from './fieldnote.js';
import { el, copyText, flash } from './dom.js';
import { formatRa, formatDec } from './coords.js';
import { verdictTiles } from './verdict.js';
import { loadVariability } from './variability.js';
import { VARIABLE_SLUGS, shortFinding } from './variabilitytext.js';

export const TALK_LABEL = 'Copy summary for Talk';
const TALK_HELP = 'Plain text for a Backyard Worlds Talk post: position, motion against the catalogue, colour, Gaia check, the spectrum’s answer and a link to this view.';

/** The "copy summary" button, with its own status line; used in the header and under the spectrum. */
export function talkButton(share, status) {
  return el('button', { type: 'button', class: 'btn', text: TALK_LABEL, title: TALK_HELP,
    onClick: async () => flash(status, (await copyText(share.summary())) ? 'Summary copied. Paste it into your Talk post.' : 'Copy failed; your browser blocked it.') });
}

/** The "copy link" button; used in the header and in Simple's answer card. */
export function copyLinkButton(share, status) {
  return el('button', { type: 'button', class: 'btn', text: 'Copy link',
    onClick: async () => flash(status, (await copyText(share.link())) ? 'Link copied.' : 'Copy the address bar instead.') });
}

/**
 * The title block and, apart from it, the share actions: beside the title on a wide screen,
 * below the blink on a phone (styles.css orders them).
 * @param {object} m manifest
 * @param {object} state page state
 * @param {{link: () => string, summary: () => string, embed: () => void}} share
 * @returns {HTMLElement[]} [header, actions]
 */
export function viewHeader(m, state, share) {
  const t = m.target;
  const status = el('span', { class: 'action-status', 'aria-live': 'polite' });
  const kind = m.solar_system ? 'Solar System body' : state.target ? 'Gallery target' : 'Position search';
  return [
    el('header', { class: 'view-head' }, [
      el('p', { class: 'eyebrow', text: kind }),
      el('h1', { text: t.name || `Position ${formatRa(t.ra, 1)} ${formatDec(t.dec, 0)}` }),
      el('p', { class: 'mono coords', text: `RA ${formatRa(t.ra)}  Dec ${formatDec(t.dec)}${t.epoch ? `  (epoch ${t.epoch})` : ''}` }),
      t.blurb ? el('p', { class: 'blurb', text: t.blurb }) : null,
    ]),
    el('div', { class: 'actions chrome', role: 'group', 'aria-label': 'Share this view' }, [
      copyLinkButton(share, status),
      el('button', { type: 'button', class: 'btn', text: 'Embed', onClick: () => share.embed() }),
      m.solar_system ? null : talkButton(share, status),
      status,
    ]),
  ];
}

function tileNode(t) {
  return el('a', { class: `vtile ${t.tone}`, href: t.href, 'data-tile': t.key }, [
    el('span', { class: 'vtile-label', text: t.label }),
    el('span', { class: 'vtile-value', text: t.value }),
    el('span', { class: 'vtile-sub', text: t.sub }),
  ]);
}

/**
 * The verdict strip. It is drawn at once from the manifest and redrawn when the gallery index
 * arrives with the published type, so a gallery target shows the tool's answer beside it.
 * @param {object} m manifest
 * @param {Promise<string|null>} published the published type of this target, or null
 */
/** The glare sentence as a plain banner above the verdict strip, or null (fieldnote.js). */
export function fieldBanner(m) {
  const s = fieldHeadline(m);
  return s ? el('p', { class: 'notice field-note', role: 'note', text: s }) : null;
}

export function verdictStrip(m, published, slug = null) {
  const opts = { published: null, variable: VARIABLE_SLUGS.has(slug), finding: null };
  const root = el('div', { class: 'verdict-strip', role: 'group', 'aria-label': 'The check in brief' });
  const draw = () => root.replaceChildren(...verdictTiles(m, opts).map(tileNode));
  draw();
  published.then((p) => { if (p) { opts.published = p; draw(); } }, () => {});
  // A variable star's brightness tile arrives with data/variability.json.
  if (opts.variable) loadVariability().then((d) => { const f = d && shortFinding(slug, d); if (f) { opts.finding = f; draw(); } });
  return root;
}
