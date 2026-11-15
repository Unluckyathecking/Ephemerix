// The archive uptime indicator: a compact row by the Check form that opens a small panel on hover,
// focus or tap, and a sentence added to partial or failed live lookups. /api/archives is the saved
// checks of a small scheduled job, cached by the CDN (web/api/archives.js), so asking for it never
// starts the lookup service. Fetched once per page, only where the row or a note is shown; every
// node starts hidden and fills only if the answer arrives and makes sense. Checks older than 30
// minutes mean the status is unknown. Simple shows only a sentence, and only when something is
// failing; CSS on body.mode-* picks the variant (styles.css). The full picture is status.html.

import { API_BASE } from './config.js';
import { el } from './dom.js';
import { cleanStatus, troubleSentence, phrase, formatTime, isStale, lookupUses, stripItems, countLine } from './archivetext.js';

const TIMEOUT_MS = 20000;
export const STATUS_HREF = 'status.html';
let pending = null;

/** The cleaned status, or null on any failure. One request per page however often it is asked. */
export function loadArchives(fetchImpl = fetch) {
  if (!API_BASE) return Promise.resolve(null);
  pending ||= (async () => {
    try {
      const url = new URL(`${API_BASE.replace(/\/+$/, '')}/api/archives`, document.baseURI);
      const res = await fetchImpl(url, { headers: { Accept: 'application/json' }, signal: AbortSignal.timeout(TIMEOUT_MS) });
      return res.ok ? cleanStatus(await res.json()) : null;
    } catch {
      return null;
    }
  })();
  return pending;
}

export const fresh = (data) => !!data && !isStale(data.checkedAt, Date.now());

/** A coloured mark whose shape also carries the state (round: answering, diamond: slow, cross: down). */
export function dot(status) {
  return el('span', { class: `arch-dot arch-${status}`, 'aria-hidden': 'true' });
}

const statusLink = (text = 'Archive uptime') => el('a', { class: 'arch-link', href: STATUS_HREF, text });

function panel(data, id) {
  return el('div', { class: 'arch-panel', id, role: 'region', 'aria-label': 'Archive status', hidden: true }, [
    el('p', { class: 'small muted', text: `Checked at ${formatTime(data.checkedAt)}.` }),
    el('ul', { class: 'arch-panel-list small' }, data.archives.map((a) => el('li', {}, [
      dot(a.status), el('b', { text: a.name }), `: ${phrase(a.status)}. `,
      el('span', { class: 'muted', text: `Used for ${a.usedFor}.` }),
    ]))),
    statusLink('Learn more'),
  ]);
}

/** Hover, focus and tap open the panel; leaving, Escape or a tap elsewhere closes it. */
function wire(box, button, pop) {
  const set = (open) => {
    pop.hidden = !open;
    button.setAttribute('aria-expanded', String(open));
    if (!open) return;
    // Open upward when it would run past the bottom and there is more room above.
    pop.classList.remove('arch-up');
    const r = box.getBoundingClientRect();
    pop.classList.toggle('arch-up', r.bottom + pop.offsetHeight + 4 > window.innerHeight && r.top > window.innerHeight - r.bottom);
  };
  box.addEventListener('mouseenter', () => set(true));
  box.addEventListener('mouseleave', () => set(false));
  box.addEventListener('focusin', () => set(true));
  box.addEventListener('focusout', (e) => { if (!box.contains(e.relatedTarget)) set(false); });
  button.addEventListener('click', () => set(pop.hidden));
  box.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !pop.hidden) { set(false); button.focus(); } });
  document.addEventListener('pointerdown', (e) => { if (!box.contains(e.target)) set(false); });
}

function compact(data) {
  const items = stripItems(data);
  const button = el('button', { type: 'button', class: 'arch-row', 'aria-expanded': 'false', 'aria-controls': 'arch-panel' }, [
    el('span', { class: 'sr-only', text: 'Archive status: ' }),
    ...items.map((i) => el('span', { class: `arch-item arch-${i.status}` }, [dot(i.status),
      el('span', { class: 'arch-name', text: i.short }), i.word ? el('span', { class: 'arch-word', text: ` ${i.word}` }) : null])),
    el('span', { class: 'arch-count', text: countLine(items) }),
  ]);
  const pop = panel(data, 'arch-panel');
  const box = el('div', { class: 'archives-adv arch-box' }, [button, pop]);
  wire(box, button, pop);
  return box;
}

function sentence(text, data) {
  return [`${text} Checked at ${formatTime(data.checkedAt)}. `, statusLink()];
}

/** The row's small heading; Simple shows it only over its sentence (CSS hides .archives-adv there). */
const heading = (inSimple) => el('p', { class: `label archives-h${inSimple ? '' : ' archives-adv'}`, text: 'Archive uptime' });

/** The row by the Check form: hidden until the saved checks arrive. */
export function archiveStrip() {
  const node = el('div', { class: 'archives', hidden: true });
  loadArchives().then((data) => {
    if (!data) return;
    if (!fresh(data)) {
      const at = formatTime(data.checkedAt);
      node.replaceChildren(heading(false), el('p', { class: 'archives-adv small muted' }, [at ? `Archive checks last ran at ${at}. ` : 'No archive checks yet. ', statusLink()]));
    } else {
      const trouble = troubleSentence(data);
      node.replaceChildren(heading(!!trouble), trouble ? el('p', { class: 'archives-simple small', role: 'status' }, sentence(trouble, data)) : '', compact(data));
    }
    node.hidden = false;
  });
  return node;
}

/** A sentence for a partial or failed live lookup, naming only failing archives that lookup uses. */
export function archiveNote() {
  const node = el('p', { class: 'archive-note small', hidden: true });
  const uses = lookupUses(window.location.search);
  loadArchives().then((data) => {
    const text = fresh(data) && troubleSentence(data, { recent: true, uses });
    if (text) { node.replaceChildren(...sentence(text, data)); node.hidden = false; }
  });
  return node;
}
