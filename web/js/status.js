// status.html, "Are the archives answering?": the saved archive checks in full. For each archive:
// 30 daily blocks; select a day for its 24 hourly blocks; select an hour for its twelve checks.
// One day and one hour open at a time; selecting again or Escape closes. Simple shows the state
// and the list only; the blocks are Advanced (styles.css, .status-adv).

import { el } from './dom.js';
import { API_BASE } from './config.js';
import { mountChrome } from './chrome.js';
import { pageTitle } from './site.js';
import { loadArchives, fresh, dot } from './archivestatus.js';
import { statusLead, phrase, measuredText, CHECK } from './archivetext.js';
import { decodeChecks, dayBlocks, hourBlocks, checkWords, recordLine, longestGap, gapLine, dayLabel } from './uptimetext.js';

const TITLE = 'Are the archives answering?';
const main = document.querySelector('main');
const dayCache = new Map(); // date -> Promise of decoded checks, or null
let open = { id: null, date: null, hour: null };
let state = null; // {data, recent, today}

function fetchDay(date) {
  if (!dayCache.has(date)) {
    const url = new URL(`${API_BASE.replace(/\/+$/, '')}/api/archives?day=${date}`, document.baseURI);
    dayCache.set(date, fetch(url, { headers: { Accept: 'application/json' }, signal: AbortSignal.timeout(20000) })
      .then((r) => (r.ok ? r.json() : null)).then((b) => (b ? decodeChecks(b.checks) : null)).catch(() => null));
  }
  return dayCache.get(date);
}

/** Today's checks are all in the default answer; other days are fetched once. */
const checksFor = (date) => (date === state.today ? Promise.resolve(state.recent) : fetchDay(date));

function block(b, selected, onSelect) {
  return el('button', { type: 'button', class: `arch-block h-${b.level}`, title: b.label, 'aria-label': b.label,
    'aria-pressed': String(selected), onClick: onSelect });
}

function hourList(hour) {
  return el('ol', { class: 'arch-checks small' }, hour.checks.length ? hour.checks.map((c) => {
    const w = checkWords(c);
    return el('li', {}, [el('b', { text: w.time }), ` ${w.state}`, w.response ? ` in ${w.response}` : '', w.detail ? el('span', { class: 'muted', text: ` (${w.detail})` }) : null]);
  }) : [el('li', { class: 'muted', text: 'No checks in this hour.' })]);
}

async function dayDetail(a, host, day) {
  // A day the summary shows with no checks has nothing to fetch.
  if (day && !day.checks && open.date !== state.today) { host.replaceChildren(el('p', { class: 'small muted', text: 'No checks were made on this day.' })); return; }
  const list = await checksFor(open.date);
  if (open.id !== a.id) return;
  if (!list) { host.replaceChildren(el('p', { class: 'small muted', text: 'The checks for this day could not be loaded.' })); return; }
  const hours = hourBlocks(list[a.id] || [], open.date);
  host.replaceChildren(
    el('p', { class: 'small', text: `${dayLabel(open.date)} (UTC day), hour by hour, in your time zone:` }),
    el('div', { class: 'arch-blocks arch-hours-row', role: 'group', 'aria-label': `${a.name}, ${dayLabel(open.date)}, one block per hour` },
      hours.map((h, i) => block(h, open.hour === i, () => select(a.id, open.date, open.hour === i ? null : i)))),
    open.hour == null ? '' : hourList(hours[open.hour]),
  );
}

function archiveRow(a) {
  const { data, recent } = state;
  const days = dayBlocks(data.days, a.id, state.today);
  const mine = recent[a.id] || [];
  const record = recordLine(days, mine.length ? Math.min(...mine.map((c) => c.t)) : null);
  const gap = gapLine(longestGap(recent[a.id] || []));
  const detail = el('div', { class: 'arch-detail' });
  if (open.id === a.id && open.date) dayDetail(a, detail, days.find((d) => d.date === open.date));
  return el('li', { class: 'status-row' }, [
    el('p', {}, [fresh(data) ? dot(a.status) : null, el('b', { text: a.name }),
      fresh(data) ? ` ${phrase(a.status)}` : '', fresh(data) ? el('span', { class: 'muted status-adv', text: ` (${measuredText(a)})` }) : null]),
    el('p', { class: 'small muted', text: `Used for ${a.usedFor}.${a.backup ? ' A second copy, asked when the first does not answer.' : ''}` }),
    el('div', { class: 'status-adv' }, [
      el('p', { class: 'small', text: [record ? `${record}.` : 'No checks saved yet.', gap ? ` Last 24 hours: ${gap}.` : ''].join('') }),
      el('div', { class: 'arch-blocks', role: 'group', 'aria-label': `${a.name}, last 30 days, one block per day, oldest first` },
        days.map((d) => block(d, open.id === a.id && open.date === d.date, () => select(a.id, open.id === a.id && open.date === d.date ? null : d.date, null)))),
      detail,
    ]),
  ]);
}

function render() {
  const { data } = state;
  const archives = data?.archives || [];
  main.replaceChildren(el('div', { class: 'page status-page' }, [
    el('h1', { text: TITLE }),
    el('p', { class: 'answer', text: statusLead(data, Date.now()) }),
    archives.length ? el('section', { class: 'card', 'aria-labelledby': 'list-h' }, [
      el('h2', { id: 'list-h', text: 'The archives we use' }),
      el('p', { class: 'small muted status-adv', text: 'One block per day for the last 30 days, oldest on the left; select a day for its hours, and an hour for each check. Full height: every check answered. Half height: some failed or were slow. Low bar: none answered. Outline: no checks.' }),
      el('ul', { class: 'status-list' }, archives.map(archiveRow)),
    ]) : null,
    howWeCheck(),
  ]));
}

function select(id, date, hour) {
  const focusLabel = document.activeElement?.getAttribute?.('aria-label');
  open = date ? { id, date, hour } : { id: null, date: null, hour: null };
  render();
  if (focusLabel) [...main.querySelectorAll('.arch-block')].find((b) => b.getAttribute('aria-label') === focusLabel)?.focus();
}

function howWeCheck() {
  return el('section', { class: 'card', 'aria-labelledby': 'how-h' }, [
    el('h2', { id: 'how-h', text: 'How we check' }),
    el('p', { text: `Every ${CHECK.everyMin} minutes our server sends one light request to each archive: the smallest real question to the same service a lookup uses, with no retry. An archive that answers within ${CHECK.slowS} s is answering; one that takes longer is slow; one that cannot be reached within ${CHECK.connectS} s, gives no answer within ${CHECK.answerS} s, or answers with an error is not answering. These are our own checks from one place; they do not say how an archive works for anyone else.` }),
    el('h2', { text: 'Why it matters' }),
    el('p', { text: 'A live lookup asks these archives as it runs. When one does not answer, the view comes back partial and says what is missing; trying again later usually fills it in. The gallery views were built ahead of time and do not depend on the archives being up.' }),
  ]);
}

document.addEventListener('keydown', (e) => {
  if (e.key !== 'Escape' || !open.date) return;
  select(open.id, open.hour == null ? null : open.date, null);
});

document.title = pageTitle(TITLE);
mountChrome('status');
loadArchives().then((data) => {
  const today = data?.checkedAt ? data.checkedAt.slice(0, 10) : new Date().toISOString().slice(0, 10);
  state = { data, recent: decodeChecks(data?.checks), today };
  render();
});
