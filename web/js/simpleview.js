// The simple view: the little video of one patch of sky, big, with the answer in plain sentences.
// Everything else (tables, the spectrum plot, flags, overlays) is one click away in the full view.

import { el, isTypingTarget, prefersReducedMotion } from './dom.js';
import { defaultBands, presetBands, activeFrames } from './framesets.js';
import { defaultFraming, canFollow } from './framing.js';
import { BlinkPlayer } from './player.js';
import { Stage } from './stage.js';
import { fieldHeadline } from './fieldnote.js';
import { icon } from './icons.js';
import { formatRa, formatDec } from './coords.js';
import { talkButton, copyLinkButton } from './viewhead.js';
import { vettingSummary } from './summary.js';
import { loadVariability } from './variability.js';
import { VARIABLE_SLUGS, summarySentences } from './variabilitytext.js';
import { motionSentence, whatSentence, partialSentence, frameCaption } from './simpletext.js';
import { motionPill, lookFor, scaleLine, spherexLabel, videoLine } from './simplelook.js';
import { archiveNote } from './archivestatus.js';

// One disclosure, not three: a newcomer's questions in one place.
const EXPLAIN = [
  'Each picture is the same small patch of sky, taken on a different date. Played in order they make a little video. Distant stars stay put; something nearby drifts across them.',
  'WISE and SPHEREx are NASA space telescopes that see infrared light. WISE mapped the whole sky from 2010; SPHEREx began in 2025 and splits light into many colours, which helps tell what an object is.',
  'An arcsecond is a tiny angle on the sky: one degree is 3,600 arcseconds, and the full Moon is about 1,800 arcseconds across.',
];

/** For the two variable stars, the brightness finding leads the answer (it arrives with its data). */
function brightnessLead(m) {
  if (!VARIABLE_SLUGS.has(m.target.slug)) return null;
  const node = el('p', { class: 'simple-bright', hidden: true });
  loadVariability().then((d) => {
    const s = d && summarySentences(m.target.slug, d)[0];
    if (s) { node.textContent = s; node.hidden = false; }
  });
  return node;
}

/** The answer card: the plain sentences, measured against catalogue, the partial note, the share row, one explainer. */
function answerCard(m, knownType, share) {
  const partial = partialSentence(m);
  const pill = motionPill(m);
  const lead = fieldHeadline(m);
  return el('section', { class: 'card simple-answer', 'aria-labelledby': 'answer-h' }, [
    el('h2', { id: 'answer-h', class: 'label', text: 'What we found' }),
    lead ? el('p', { class: 'simple-field', text: lead }) : null,
    brightnessLead(m),
    el('p', { class: 'simple-motion', text: motionSentence(m, { withCatalogue: !pill }) }),
    pill ? el('p', { class: `simple-pill${pill.agree ? ' agree' : ''}`, text: pill.text }) : null,
    el('p', { class: 'simple-what', text: whatSentence(m, { knownType }) }),
    partial ? el('p', { class: 'simple-partial small', text: partial }) : null,
    partial && !new URLSearchParams(window.location.search).get('target') ? archiveNote() : null, // live views only (js/archivestatus.js)
    share,
    el('details', { class: 'explain' }, [el('summary', { text: 'What am I looking at?' }), ...EXPLAIN.map((t) => el('p', { class: 'small', text: t }))]),
  ]);
}

/** "WISE and SPHEREx" / "SPHEREx only: 23 images, 2025 to 2026": which images the video plays. */
function missionChoice(m, onPick) {
  const both = defaultBands(m.frames);
  const spx = presetBands(m.frames, 'spherex');
  const spxFrames = activeFrames(m.frames, spx);
  const hasWise = activeFrames(m.frames, both).some((f) => f.mission === 'WISE');
  if (!hasWise) return { root: null, both };
  const segs = {};
  const set = (k) => { for (const [key, b] of Object.entries(segs)) b.setAttribute('aria-pressed', String(key === k)); };
  segs.both = el('button', { type: 'button', class: 'seg', 'aria-pressed': 'true', text: 'WISE and SPHEREx', onClick: () => { set('both'); onPick(both); } });
  segs.spx = el('button', { type: 'button', class: 'seg', 'aria-pressed': 'false', disabled: spxFrames.length < 2,
    text: spherexLabel(spxFrames), title: spxFrames.length < 2 ? 'SPHEREx has fewer than two images of this spot at one wavelength.' : '',
    onClick: () => { set('spx'); onPick(spx); } });
  return { both, root: el('div', { class: 'simple-choice' }, [
    el('span', { class: 'label', id: 'simple-choice-l', text: 'Play' }),
    el('div', { class: 'segmented simple-missions', role: 'group', 'aria-labelledby': 'simple-choice-l' }, [segs.both, segs.spx]),
  ]) };
}

/** Previous, play, next; returns the row and a sync() for the play icon. */
function playControls(player) {
  const play = el('button', { type: 'button', class: 'btn icon primary', id: 'simple-play', 'aria-label': 'Play', onClick: () => player.toggle() });
  const row = el('div', { class: 'controls simple-controls' }, [
    el('button', { type: 'button', class: 'btn icon', 'aria-label': 'Previous image', onClick: () => player.step(-1) }, [icon('prev')]),
    play,
    el('button', { type: 'button', class: 'btn icon', 'aria-label': 'Next image', onClick: () => player.step(1) }, [icon('next')]),
  ]);
  const sync = () => {
    play.replaceChildren(icon(player.playing ? 'pause' : 'play'));
    play.setAttribute('aria-label', player.playing ? 'Pause' : 'Play');
  };
  return { row, sync };
}

/** Space plays or pauses, the arrows step; removed with the view. */
function bindKeys(player, signal) {
  document.addEventListener('keydown', (e) => {
    if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.altKey || isTypingTarget(e.target, e.key)) return;
    if (e.key === ' ') player.toggle();
    else if (e.key === 'ArrowRight') player.step(1);
    else if (e.key === 'ArrowLeft') player.step(-1);
    else return;
    e.preventDefault();
  }, { signal });
}

/** What to watch for, said on the image; the variable stars' line arrives with their data. */
function lookLine(m) {
  const node = el('p', { class: 'simple-look', text: lookFor(m) });
  if (VARIABLE_SLUGS.has(m.target.slug)) loadVariability().then((variability) => { if (variability) node.textContent = lookFor(m, { variability }); });
  return node;
}

/** The blink: the canvas with one marker, what to look for, the date on screen, and the controls. */
function blinkBlock(m, images, signal) {
  const canvas = el('canvas', { class: 'stage', role: 'img', tabindex: '0' });
  const stage = new Stage(canvas, m, images, { compact: true });
  const detected = m.frames.some((f) => f.centroid_px);
  stage.layers = { ...stage.layers, gaps: false, track: false, gaia: false, catwise: false, scale: false, centroids: detected, predicted: !detected || !!m.solar_system };
  const date = el('p', { class: 'simple-date', text: '' });
  const count = el('p', { class: 'small muted simple-count' });
  const live = el('p', { class: 'sr-only', 'aria-live': 'polite' });
  const player = new BlinkPlayer({ onChange: (why) => {
    const f = player.current;
    stage.show(f, player.frames);
    date.textContent = frameCaption(f);
    date.dataset.mission = f?.mission || '';
    count.textContent = f ? `Image ${player.index + 1} of ${player.frames.length}` : '';
    canvas.setAttribute('aria-label', f ? `${frameCaption(f)}, the patch of sky around ${m.target.name || 'this position'}` : 'No image');
    if (why !== 'tick' && f) live.textContent = frameCaption(f);
    controls.sync();
  } });
  const controls = playControls(player);
  const missions = el('p', { class: 'small muted simple-missions-line' });
  const scale = el('p', { class: 'small muted simple-scale' });
  const setFrames = (bands) => {
    const frames = activeFrames(m.frames, bands);
    missions.textContent = videoLine(frames, m.frames);
    const fr = defaultFraming({ ...m, frames });
    stage.setView(fr.zoom, fr.cx, fr.cy);
    scale.textContent = scaleLine(m.fov_arcsec, fr.zoom);
    if (m.solar_system && canFollow(frames)) stage.setFollow(true);
    player.setFrames(frames);
  };
  const choice = missionChoice(m, setFrames);
  bindKeys(player, signal);
  const root = el('section', { class: 'card simple-blink', 'aria-labelledby': 'simple-blink-h' }, [
    el('h2', { id: 'simple-blink-h', class: 'sr-only', text: 'The images, played in order' }),
    lookLine(m),
    el('div', { class: 'stage-wrap' }, [canvas]),
    el('div', { class: 'simple-row' }, [controls.row, choice.root]),
    el('div', { class: 'simple-now' }, [date, count]),
    missions,
    scale,
    live,
  ]);
  return { root, player, start: (bands = choice.both) => setFrames(bands) };
}

/**
 * @param {HTMLElement} host
 * @param {object} m validated manifest
 * @param {Map<string, HTMLImageElement|null>} images
 * @param {{knownType?: string|null, kind: string, onFull: () => void, link: () => string,
 *   fullLink?: () => string, extras?: Array<(m: object) => HTMLElement|null>, signal?: AbortSignal}} ctx  fullLink: for the Talk summary
 *   extras: optional blocks for this object (one mount point, under the answer); each returns a node or null
 */
export function renderSimple(host, m, images, { knownType = null, kind, onFull, link, fullLink = link, extras = [], signal, frame = null }) {
  const blink = blinkBlock(m, images, signal);
  const status = el('span', { class: 'action-status', 'aria-live': 'polite' });
  const extra = extras.map((fn) => fn(m)).filter(Boolean);
  // Share from the answer: the Talk summary (not for a Solar System body) and this view's link.
  const shareStatus = el('span', { class: 'action-status', 'aria-live': 'polite' });
  const share = el('div', { class: 'simple-share', role: 'group', 'aria-label': 'Share this view' }, [
    m.solar_system ? null : talkButton({ summary: () => vettingSummary(m, fullLink()) }, shareStatus),
    copyLinkButton({ link }, shareStatus),
    shareStatus,
  ]);
  host.replaceChildren(el('div', { class: 'view simple' }, [
    el('header', { class: 'view-head' }, [
      el('p', { class: 'eyebrow', text: kind }),
      el('h1', { text: m.target.name || `Position ${formatRa(m.target.ra, 1)} ${formatDec(m.target.dec, 0)}` }),
      el('p', { class: 'mono coords', text: `RA ${formatRa(m.target.ra)}  Dec ${formatDec(m.target.dec)}` }),
      m.target.blurb ? el('p', { class: 'blurb', text: m.target.blurb }) : null,
      // The brightness chart sits below the blink; one link takes a variable star's view there.
      VARIABLE_SLUGS.has(m.target.slug) ? el('p', { class: 'small' }, [el('a', { href: '#variability', text: 'Brightness over time' })]) : null,
    ]),
    // Grid areas: the blink beside the answer on a wide screen; on a phone the answer comes first.
    el('div', { class: 'simple-grid' }, [
      answerCard(m, knownType, share),
      blink.root,
      el('div', { class: 'simple-side' }, [
        // One mount point for an extra block about this object (for example brightness over time).
        el('div', { class: 'simple-extra', hidden: !extra.length }, extra),
        // The header switch changes mode; this is one quiet way in from beside the answer.
        el('p', { class: 'small muted simple-actions' }, [
          el('button', { type: 'button', class: 'linkish', id: 'show-full', text: 'See everything: all bands, compare dates, overlays, embed', onClick: onFull }),
          status,
        ]),
      ]),
    ]),
  ]));
  // A link to one image opens on it, paused, as in Advanced (its own wavelength when the video's set lacks it).
  const linked = frame ? m.frames.find((f) => f.id === frame) : null;
  blink.start(linked && !activeFrames(m.frames, defaultBands(m.frames)).includes(linked) ? [linked.band] : undefined);
  if (linked && blink.player.seekId(linked.id)) return { player: blink.player };
  blink.player.startAt(blink.player.frames.findLastIndex((f) => f.mission === 'SPHEREx'));
  if (!prefersReducedMotion()) blink.player.play();
  return { player: blink.player };
}
