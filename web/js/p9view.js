// "A pilot search where Planet Nine is predicted": the section of the blind-search page drawn
// from data/p9-search.json. Upper limits only.

import { el } from './dom.js';
import { pilotSentence } from './searchdata.js';
import { p9Problem, p9Statement, p9Pretty, p9Stats, p9ReachRows, p9PopulationText, p9Peaks, p9PeaksText, p9PeakHead } from './p9data.js';

const DATA_URL = new URL('../data/p9-search.json', import.meta.url);
// Brown, Holman & Batygin 2024: Pan-STARRS1 is half complete at V 21.5; with ZTF and DES, 78% excluded.
const PS1_V50 = 21.5;

function table(head, rows) {
  return el('div', { class: 'table-wrap' }, [el('table', {}, [
    el('thead', {}, [el('tr', {}, head.map((h) => el('th', { scope: 'col', text: h })))]),
    el('tbody', {}, rows.map((r) => el('tr', {}, r.map((c, i) => el(i ? 'td' : 'th', { scope: i ? null : 'row', text: c }))))),
  ])]);
}

function content(d) {
  const p = d.pooled;
  const peaks = p9Peaks(d);
  const population = p9PopulationText(d);
  const shallower = (PS1_V50 - p.vmag50).toFixed(1);
  return [
    el('p', { class: 'p9-plain', text: pilotSentence(d) }),
    el('dl', { class: 'stat-grid' }, p9Stats(d).map((s) => el('div', { class: 'stat' }, [
      el('dt', { text: s.label }), el('dd', {}, [el('span', { class: 'stat-v', text: s.value }), el('span', { class: 'small muted', text: s.sub })]),
    ]))),
    el('h3', { text: 'Against earlier searches' }),
    el('p', {}, [`Pan-STARRS1 is half complete at V ${PS1_V50} and, with ZTF and DES, rules out 78% of the predicted orbits (Brown, Holman & Batygin 2024). This pilot is about ${shallower} magnitudes shallower over a far smaller area, so it adds nothing to that result. The WISE search of Meisner et al. (2018) tests planets that glow in their own heat at 3.4 µm; this search is in reflected light at 1 to 2 µm and does not test them. What the pilot shows is that the search gives calibrated upper limits, field by field, where the planet is predicted. `,
      el('a', { href: 'planetx.html', text: 'How far each survey reaches' }), '.']),
    el('details', { class: 'p9-more' }, [
      el('summary', { text: 'The full result, against the predicted brightness, how the fields were chosen, and the peaks we examined' }),
      el('p', { class: 'p9-statement', text: p9Statement(d) }),
      el('p', { class: 'small muted', text: 'The fields were drawn by a fixed, seeded rule from the densest part of the Brown & Batygin (2021) reference population away from the Galactic plane. A limit counts a planted body only if it comes out above the highest peak of that field’s mirrored search, because only real peaks above that bar were examined one by one. That is stricter than the S/N 7 cut used on the fields above.' }),
      el('h3', { text: 'Against the predicted brightness' }),
      el('p', { text: 'How far each hypothetical planet would be seen at these limits, from the same brightness curves as the Planet X page (dark, most likely and bright versions). The favoured range is 400 to 800 au.' }),
      table(['Planet', `At the 50% limit (${Math.round(p.flux50_ujy)} µJy)`, `At the 90% limit (${Math.round(p.flux90_ujy)} µJy)`],
        p9ReachRows(d).map((r) => [r.label, r.at50, r.at90])),
      population ? el('p', { text: population }) : null,
      el('h3', { text: 'Peaks above the null' }),
      el('p', { text: `${p9PeaksText(d)}${d.peaks?.note ? ` ${d.peaks.note}` : ''}` }),
      ...peaks.unexplained.map((u) => el('div', { class: 'p9-peak' }, [
        el('p', {}, [el('span', { class: 'vtag v-not_applicable', text: 'Unexplained peak' }), ' ', el('span', { class: 'mono small', text: p9PeakHead(u) })]),
        el('p', { text: p9Pretty(u.assessment?.why) }),
      ])),
    ]),
  ];
}

/**
 * Fill the section; on any failure it says so in place and the rest of the page is unaffected.
 * @param {HTMLElement} host
 */
export async function renderP9(host) {
  try {
    const res = await fetch(DATA_URL, { headers: { Accept: 'application/json' } });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const d = await res.json();
    const problem = p9Problem(d);
    if (problem) throw new Error(problem);
    host.replaceChildren(...content(d).filter(Boolean));
  } catch (err) {
    host.replaceChildren(el('p', { class: 'small muted', text: `The pilot-search results could not be shown (${err.message}).` }));
  }
}
