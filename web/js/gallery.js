// Landing page: what the tool does and the box to try it, the featured blink, the scoreboard
// strip, three views to start with, and the gallery as a ledger of results.

import { el } from './dom.js';
import { pickHero } from './hero.js';
import { noTypeWhy } from './notes.js';
import { notBrownDwarf } from './matchtext.js';
import { searchForm } from './search.js';
import { heroVisual, heroCaption } from './herovisual.js';
import { scoreTiles, cardMarks, validationFor, proofLine } from './scoreboard.js';
import { SITE } from './site.js';
import { pickMover } from './simplelook.js';
import { archiveStrip, archiveNote } from './archivestatus.js';

export { heroCaption };

/**
 * Gallery targets in groups, groups whose name mentions the brief first, then in index order.
 * @returns {{group: string|null, targets: object[]}[]}
 */
export function groupTargets(targets) {
  const order = [];
  const map = new Map();
  for (const t of targets) {
    const g = t.group || null;
    if (!map.has(g)) { map.set(g, []); order.push(g); }
    map.get(g).push(t);
  }
  // Solar System bodies last: they demonstrate the method; the brief's targets lead.
  const rank = (g) => (g === 'solar-system' ? 3 : g == null ? 2 : /brief/i.test(g) ? 0 : 1);
  return order.map((g, i) => ({ g, i })).sort((a, b) => rank(a.g) - rank(b.g) || a.i - b.i)
    .map(({ g }) => ({ group: g, targets: map.get(g) }));
}

const GROUP_HEADINGS = {
  brief: 'From the challenge brief',
  'backyard-worlds': 'Backyard Worlds discoveries',
  benchmark: 'Brown dwarfs with published spectral types',
  'solar-system': 'Solar System objects',
};

/** Readable heading for an index `group` value; unknown values keep their text with a capital first letter. */
export function groupHeading(group) {
  if (!group) return null;
  return GROUP_HEADINGS[group] || group.charAt(0).toUpperCase() + group.slice(1);
}

const toolWords = (t) => (/^(star|not|uncertain)/i.test(t) ? t : `about ${t}`);
const WHY_WORDS = { saturated: 'the star saturates SPHEREx' };

/** What the tool says for a card: a type, a blended pair, or the reason there is none. */
export function toolResult(t, m) {
  if (m?.solar_system) return { text: m.solar_system.reflectance.some((r) => r.band_depths.some((d) => d.detected)) ? 'sees ice bands' : 'sees no ice band', why: false };
  if (m?.match?.pair?.types?.length === 2) return { text: `${m.match.pair.types.join(' + ')} blend`, why: false };
  if (m?.match && notBrownDwarf(m.match)) return { text: 'not a brown dwarf', why: false };
  if (m?.match && t.tool_type) return { text: toolWords(t.tool_type), why: false };
  if (m && !m.match) {
    const why = noTypeWhy(m.warnings, m.spectra.length > 0);
    return { text: `no type: ${WHY_WORDS[why] || why}`, why: true };
  }
  if (t.tool_type) return { text: toolWords(t.tool_type), why: false };
  return null; // manifest not loaded yet and no type in the index: say nothing rather than guess
}

const viewHref = (slug) => `?target=${encodeURIComponent(slug)}`;

function thumbFor(t, indexUrl, cls, size) {
  const thumb = t.thumb
    ? el('img', { src: new URL(t.thumb, indexUrl).href, alt: '', width: String(size), height: String(size), loading: 'lazy', class: cls })
    : el('div', { class: `${cls} empty`, 'aria-hidden': 'true' });
  thumb.addEventListener?.('error', () => thumb.classList.add('empty'));
  return thumb;
}

const marksRow = (marks) => marks.map((k) => el('span', { class: `vtag v-${k.tone}`, text: k.text }));

/** One row of the ledger. `fill(manifest, validation)` adds what is known once the data arrives. */
function card(t, indexUrl) {
  const types = el('p', { class: 'types' });
  const marks = el('div', { class: 'card-marks' });
  const fill = (m, v) => {
    const r = toolResult(t, m);
    types.replaceChildren(...[
      t.known_type ? el('span', {}, ['Published ', el('b', { text: t.known_type })]) : null,
      r ? el('span', {}, [`${SITE.name} `, el('b', { class: r.why ? 'none' : '', text: r.text })]) : null,
    ].filter(Boolean));
    types.hidden = !types.childNodes.length;
    marks.replaceChildren(...marksRow(cardMarks(v)));
  };
  fill(null, null);
  const node = el('li', {}, [el('a', { class: 'target-card', href: viewHref(t.slug) }, [
    thumbFor(t, indexUrl, 'thumb', 112),
    el('div', { class: 'target-body' }, [el('h3', {}, [t.name]), t.blurb ? el('p', { text: t.blurb }) : null]),
    types,
    marks,
  ])]);
  return { node, fill };
}

// The three views a newcomer should open first, by gallery slug; any that are missing are skipped.
const STARTERS = [
  { slug: '2mass-0415-0935', kicker: 'A brown dwarf in motion', action: 'Watch the brown dwarf' },
  // The spectrum lives in the full view, so this one opens there.
  { slug: 'wise-0855-0714', kicker: 'Overlapping starlight', action: 'Inspect the spectrum', full: true },
  { slug: 'haumea', kicker: 'Ice on a dwarf planet', action: 'Follow Haumea' },
];

/** The sentence on a starter card, from the manifest and the validation entry. */
export function starterLine(t, m, v) {
  const r = toolResult(t, m);
  if (m?.solar_system) return `Follow the orbit across ${m.frames.length} stacked images. SPHEREx ${r.text} in the sunlight reflected from the surface.`;
  const motion = { pass: 'The motion matches the catalogue measurement.', fail: 'The measured motion differs from the catalogue value.' }[v?.motion?.verdict] || '';
  if (!r) return motion;
  if (r.why && r.text.includes('a neighbouring star shares the pixel')) {
    return [motion, 'A nearby star falls within one SPHEREx pixel of the target. Its light makes the spectrum hard to interpret.'].filter(Boolean).join(' ');
  }
  const spec = r.why ? `No reliable spectral type (${r.text.replace(/^no type: /, '')}).`
    : `The spectrum most closely matches ${r.text.replace(/^about /, '')}.${t.known_type ? ` Astronomers classify this object as ${t.known_type}.` : ''}`;
  return [motion, spec].filter(Boolean).join(' ');
}

function starters(targets, indexUrl) {
  const picks = STARTERS.map((s) => ({ ...s, t: targets.find((x) => x.slug === s.slug) })).filter((s) => s.t);
  if (picks.length < 2) return { node: null, fill: () => {} };
  const lines = new Map();
  const node = el('section', { class: 'start', 'aria-labelledby': 'start-h' }, [
    el('h2', { id: 'start-h', text: 'Start with these three' }),
    el('ul', { class: 'starters' }, picks.map(({ t, kicker, action, full }) => {
      const line = el('p', { text: t.blurb || '' });
      lines.set(t.slug, line);
      return el('li', {}, [el('a', { class: 'starter', href: `${viewHref(t.slug)}${full ? '&mode=full' : ''}` }, [
        thumbFor(t, indexUrl, 'starter-thumb', 112),
        el('div', {}, [
          el('p', { class: 'label starter-kicker', text: kicker }),
          el('h3', { text: t.name }),
          line,
          el('span', { class: 'go', text: action }),
        ]),
      ])]);
    })),
  ]);
  const fill = (t, m, v) => { const p = lines.get(t.slug); const s = p && starterLine(t, m, v); if (s) p.textContent = s; };
  return { node, fill };
}

/** The one-line proof by the Check form; hidden until the validation report arrives, and if it never does. */
function proofNode() {
  const node = el('p', { class: 'hero-proof small', hidden: true });
  const fill = (report) => {
    const text = proofLine(report?.summary);
    if (!text) return;
    node.replaceChildren(el('a', { href: 'validation.html', text }));
    node.hidden = false;
  };
  return { node, fill };
}

/** The scoreboard strip; empty and hidden until the validation report arrives. */
function scoreStrip() {
  const node = el('section', { class: 'scorestrip', 'aria-labelledby': 'score-h', hidden: true });
  const fill = (report) => {
    if (!report?.summary) return;
    const s = report.summary;
    node.replaceChildren(
      el('div', {}, [
        el('h2', { id: 'score-h', text: `Tested on ${s.targets} known objects` }),
        el('p', {}, ['Compare our measurements with the published values. ', el('a', { href: 'validation.html', text: 'See every result' }), '.']),
      ]),
      el('dl', { class: 'score-tiles' }, scoreTiles(s).map((c) => el('div', { class: 'score' }, [
        el('dt', { text: c.label }),
        el('dd', {}, [
          el('span', { class: 'score-value' }, [c.value, c.of ? el('small', { text: ` ${c.of}` }) : null]),
          el('span', { class: 'score-sub' }, [c.sub, c.fail ? ', ' : null, c.fail ? el('span', { class: 'fail', text: c.fail }) : null,
            c.calm ? `, ${c.calm}` : null]),
        ]),
      ]))),
    );
    node.hidden = false;
  };
  return { node, fill };
}

// The landing's example chips: three of the challenge's own test targets, in the brief's order.
const EXAMPLES = ['barnards-star', 'epsilon-indi-b', 'wise-0855-0714'];

function heroText(apiBase, prefill, notice, targets, mover, proof) {
  const examples = EXAMPLES.map((s) => (targets || []).find((t) => t.slug === s)).filter(Boolean);
  return el('div', { class: 'hero-text' }, [
    el('p', { class: 'label hero-eyebrow', text: 'WISE and SPHEREx · 2010–2026' }),
    el('h1', { id: 'hero-h' }, ['Is that dot moving, and ', el('em', { text: 'what is it?' })]),
    el('p', { class: 'hero-who', text: 'For Backyard Worlds volunteers and anyone curious: blink a patch of sky, measure what moves and see what it is.' }),
    el('p', { class: 'lede', text: 'Play back 16 years of infrared images and watch for a dot that shifts against the background stars. Earlier WISE images show how far it has travelled. Its SPHEREx spectrum can help you tell what it is.' }),
    el('section', { class: 'check-form', id: 'search', 'aria-labelledby': 'search-h' }, [
      el('h2', { id: 'search-h', class: 'sr-only', text: 'Check a position' }),
      notice ? el('p', { class: 'banner', role: 'status', text: notice }) : null,
      notice && apiBase ? archiveNote() : null, // archive uptime (js/archivestatus.js)
      searchForm({ apiBase, prefill, gallery: targets, examples, lead: mover }),
      apiBase ? archiveStrip() : null, // archive uptime (js/archivestatus.js)
    ]),
    proof,
    el('p', { class: 'hero-explore' }, ['Not sure where to look? ', el('a', { href: 'explore.html', text: 'Explore the sky on a map' }), ' and tap any marked object.']),
    el('p', { class: 'small muted hero-note', text: 'Checking a candidate for Backyard Worlds? You can share the images and measurements in a Talk post.' }),
  ]);
}

/**
 * @param {HTMLElement} host
 * @param {{targets: object[]|null, indexUrl: URL, indexError: string|null, notice: string|null,
 *          loadManifest: Function, apiBase: string, prefill: object|null,
 *          validation?: Promise<object|null>}} ctx  validation: the report, or null when it cannot be read
 */
export function renderLanding(host, { targets, indexUrl, indexError, notice, loadManifest, apiBase, prefill, validation = Promise.resolve(null) }) {
  const heroHost = el('div', { class: 'hero-visual' }, [el('p', { class: 'muted', text: 'Loading the featured blink…' })]);
  const groups = targets?.length ? groupTargets(targets) : [];
  const grouped = groups.some((g) => g.group);
  const fillers = new Map();
  const list = groups.length
    ? el('div', {}, groups.map(({ group, targets: ts }) => el('div', { class: 'gallery-group' }, [
      grouped ? el('h3', { class: 'group-h' }, [el('span', { text: groupHeading(group) || 'Other targets' }), el('span', { text: `${ts.length} ${ts.length === 1 ? 'target' : 'targets'}` })]) : null,
      el('ul', { class: 'gallery' }, ts.map((t) => {
        const c = card(t, indexUrl);
        fillers.set(t.slug, c.fill);
        return c.node;
      })),
    ])))
    : el('p', { class: 'muted', text: indexError ? `The gallery could not be loaded: ${indexError}` : 'No gallery targets built yet.' });
  const strip = scoreStrip();
  const proof = proofNode();
  validation.then(proof.fill, () => {});
  const start = starters(targets || [], indexUrl);
  let manifests = Promise.resolve([]);
  // No decisions needed: one press opens a gallery target that clearly moves, in the simple view.
  const mover = targets?.length ? el('button', { type: 'button', class: 'btn', id: 'show-mover', text: 'Show me something that moves',
    onClick: async () => { const slug = pickMover(await manifests, Math.random); if (slug) window.location.search = `?target=${encodeURIComponent(slug)}`; } }) : null;
  host.replaceChildren(el('div', { class: 'landing' }, [
    el('section', { class: 'hero', 'aria-labelledby': 'hero-h' }, [heroText(apiBase, prefill, notice, targets, mover, proof.node), heroHost]),
    strip.node,
    start.node,
    el('section', { 'aria-labelledby': 'gallery-h' }, [
      el('h2', { id: 'gallery-h', text: 'Gallery' }),
      groups.length ? el('p', { class: 'section-lede', text: 'Choose an object to see its images, spectrum and published classification.' }) : null,
      list,
    ]),
  ]));
  if (notice) host.querySelector('#search')?.scrollIntoView({ block: 'center' });
  if (!targets?.length) { heroHost.replaceChildren(); return; }
  // One read of every manifest serves the hero choice, the starter cards and the result on each row.
  manifests = Promise.all(targets.map(async (entry) => {
    try {
      const url = new URL(entry.manifest, indexUrl);
      const { manifest } = await loadManifest(url);
      return { entry, manifest, url };
    } catch {
      return { entry, manifest: null, url: null };
    }
  }));
  manifests.then((cands) => {
    const pick = pickHero(cands);
    const c = cands.find((x) => x.entry === pick);
    if (c?.manifest) heroVisual(heroHost, pick, c.url, c.manifest);
    else heroHost.replaceChildren(el('p', { class: 'muted', text: 'The featured view could not be loaded. The gallery below still works.' }));
  });
  Promise.all([manifests, validation.catch(() => null)]).then(([cands, report]) => {
    strip.fill(report);
    for (const { entry, manifest } of cands) {
      const v = validationFor(report, entry.slug);
      if (manifest) fillers.get(entry.slug)?.(manifest, v);
      start.fill(entry, manifest, v);
    }
  });
}
