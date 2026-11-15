// The full view for one manifest, in the order a reader needs it: the verdict strip, the
// blink, the motion, the spectrum and its answer, then everything that lets you check the data.

import { el, isTypingTarget, prefersReducedMotion } from './dom.js';
import { formatRa, formatDec } from './coords.js';
import { resolveBands, activeFrames } from './framesets.js';
import { setLabel, nameBands } from './labels.js';
import { BlinkPlayer } from './player.js';
import { Stage } from './stage.js';
import { defaultFraming, shouldAutoFollow, canFollow, objectPx, clampZoom, MIN_ZOOM, MAX_ZOOM } from './framing.js';
import { findGaps, gapCue } from './gaps.js';
import { summariseNotes } from './notes.js';
import { notesBar } from './notesview.js';
import { Timeline } from './timeline.js';
import { COLORS } from './overlays.js';
import { HATCH_LEGEND } from './gaphatch.js';
import { renderSpectrum } from './spectrum.js';
import { motionPanel, degradedNotice, frameDetails, honestyPanel, creditsBlock, embedDialog, linkOutBlock, rejectedPanel } from './panels.js';
import { vettingSummary, motionSignificant } from './summary.js';
import { bandPicker } from './bandpicker.js';
import { bandStrip } from './bandstrip.js';
import { compareMode } from './compareview.js';
import { frameChip } from './flags.js';
import { locatorPanel } from './locator.js';
import { icon } from './icons.js';
import { bodyPanel, bodySection } from './bodymode.js';
import { viewHeader, verdictStrip, talkButton, fieldBanner } from './viewhead.js';
import { linkOuts } from './links.js';
import { variabilityBlock } from './variability.js';
import { factsSection } from './facts.js';
import { fieldMoversSection } from './fieldmovers.js';
import { keepInView } from './keepinview.js';
import { isBrownDwarf } from './striptext.js';

const LAYERS = [
  ['gaps', 'No usable data (hatched)', COLORS.ink, 'A faint hatch over pixels with no usable data: saturated by a bright source, or not covered.'],
  ['track', 'Predicted track', COLORS.predicted, 'Where the catalogue motion says the object should be, one tick per year.'],
  ['predicted', 'Predicted spot now', COLORS.predicted, 'Dashed ring: the predicted position on this frame’s date.'],
  ['centroids', 'Measured positions', COLORS.measured, 'Where the object was found in the images, with its error circle.'],
  ['gaia', 'Gaia stars', COLORS.gaia, 'Gaia catalogue stars, moved to this frame’s date.'],
  ['catwise', 'CatWISE sources', COLORS.catwise, 'CatWISE catalogue sources, moved to this frame’s date.'],
  ['scale', 'Scale and compass', COLORS.ink, 'Scale bar and north/east arrows.'],
];
// The catalogue overlays the brief names, also offered beside "Follow the object".
const QUICK_LAYERS = ['gaia', 'catwise'];

function skyText(s) {
  return s ? `RA ${formatRa(s.ra)}  Dec ${formatDec(s.dec)}   (${s.ra.toFixed(5)}°, ${s.dec.toFixed(5)}°)` : 'Point at the image to read RA and Dec.';
}

/** Under the blink of a body: what the frames are and how to see it move. */
function blinkNote(m) {
  const fs = m.frames, d0 = fs[0]?.date.slice(0, 10), d1 = fs.at(-1)?.date.slice(0, 10);
  const span = d0 && d1 && d0 !== d1 ? ` from ${d0} to ${d1}` : d0 ? ` on ${d0}` : '';
  return `${fs.length} short stacks of single exposures${span}. The view follows ${m.target.name || 'the body'} (dashed ring) and the stars slide past; untick Follow to hold the sky still and watch it walk along the line, one tick per exposure stack.`;
}

/** Where "Use this motion" goes: the same position with the measured motion, as a live view. */
function useMotionLink(m, state, href, apiBase) {
  const mm = m.measured_motion;
  if (m.track.length || !motionSignificant(mm)) return { href: null, reason: '' };
  if (!apiBase) return { href: null, reason: 'Rebuilding the view with this motion needs the live server, which this copy of the site does not have.' };
  const t = m.target;
  return { href: href({ target: null, ra: +t.ra.toFixed(7), dec: +t.dec.toFixed(7), epoch: t.epoch ?? state.epoch,
    pmra: Math.round(mm.pmra_masyr * 10) / 10, pmdec: Math.round(mm.pmdec_masyr * 10) / 10, fov: state.fov ?? m.fov_arcsec,
    frame: null, bands: null, preset: null, spec: null, cmp: null, a: null, b: null, zoom: null, follow: null, fc: false, embed: false }), reason: '' };
}

function flagBadge(frames) {
  const tip = el('span', { class: 'flag-tip', role: 'tooltip', id: 'flag-tip' });
  const short = el('span');
  const node = el('span', { class: 'flag-badge', tabindex: '0', 'aria-describedby': 'flag-tip', hidden: true }, [short, tip]);
  return { node, show: (f) => {
    const chip = f && frameChip(f);
    node.hidden = !chip;
    if (chip) { short.textContent = `⚠︎ ${chip.short}`; tip.textContent = nameBands(chip.long, frames); }
  } };
}

/** Zoom slider with its readout and "Fit track" (under More controls), plus the Follow toggle and its note. */
function viewControls({ stage, followable, onFollow, onZoomInput, onFit }) {
  const readout = el('output', { class: 'zoom-out mono', for: 'zoom' });
  const slider = el('input', { type: 'range', id: 'zoom', min: String(MIN_ZOOM), max: String(MAX_ZOOM), step: '0.05', value: '1',
    'aria-label': 'Zoom', onInput: (e) => onZoomInput(Number(e.target.value)) });
  const follow = el('input', { type: 'checkbox', id: 'follow', disabled: !followable, onChange: (e) => onFollow(e.target.checked, false) });
  const note = el('p', { class: 'small muted follow-note', 'aria-live': 'polite' });
  const recentre = el('button', { type: 'button', class: 'btn recentre', hidden: true, text: 'Re-centre on the object', onClick: () => stage.recentre() });
  const zoomRow = el('div', { class: 'view-controls' }, [
    el('label', { class: 'ctl' }, ['Zoom ', slider, readout]),
    el('button', { type: 'button', class: 'btn', text: 'Fit track', onClick: onFit, title: 'Back to the view that shows the whole path' }),
    note,
  ]);
  const followLabel = el('label', { class: 'check', title: followable ? 'Keep the object at the centre while the background slides past.' : 'Nothing to follow: no motion was given and the object was not found.' },
    [follow, ' Follow the object']);
  const syncZoom = (z) => {
    slider.value = String(z);
    readout.textContent = `${(Math.round(z * 10) / 10).toFixed(1)}×`;
    slider.setAttribute('aria-valuetext', `${(Math.round(z * 10) / 10).toFixed(1)} times`);
  };
  const setNote = (on, auto) => {
    note.textContent = !followable ? 'Nothing to follow: no motion was given and the object was not found.'
      : on ? (auto ? 'Following the object; switch to Fixed sky to see it move.' : 'Following the object: the view moves with it and the stars slide past.')
        : 'Fixed sky: the view stays put and the object walks across.';
  };
  return { zoomRow, followLabel, syncZoom, setNote, follow, recentre };
}

/** After the spectrum: take the result somewhere. Null for a body (no brown-dwarf summary). */
function afterSpectrum(m, share) {
  if (m.solar_system) return null;
  const status = el('span', { class: 'small', 'aria-live': 'polite' });
  const wiseview = linkOuts(m.target.ra, m.target.dec, m.fov_arcsec).find((l) => /wiseview/i.test(l.label));
  return el('div', { class: 'spec-after chrome' }, [
    talkButton(share, status),
    wiseview ? el('a', { class: 'btn', href: wiseview.href, target: '_blank', rel: 'noopener noreferrer', text: 'Open in WiseView ↗' }) : null,
    el('p', { class: 'small muted' }, ['Share the measurements and a link to these images on Backyard Worlds Talk. ', status]),
  ]);
}

/**
 * @param {HTMLElement} host
 * @param {object} m validated manifest
 * @param {Map<string, HTMLImageElement|null>} images
 * @param {{state: object, problems: string[], setUrl: (patch: object) => void, href: (patch: object) => string, apiBase: string,
 *   targets?: Promise<Array<object>|null>|null, baseUrl?: URL, signal?: AbortSignal}} ctx  baseUrl: the manifest's URL
 *   (body-mode images); signal: removes the keyboard listener when the view is replaced
 */
export function renderView(host, m, images, { state, problems, setUrl, href, apiBase, targets = null, baseUrl = document.baseURI, signal }) {
  const body = m.solar_system; // a Solar System body (docs/api.md): follow it, show reflectance
  // Links carry the frame on screen when paused, and no frame while blinking.
  const linkTo = (embed) => href({ embed, frame: player.playing ? null : player.current?.id ?? null });
  const share = { link: () => linkTo(false), summary: () => vettingSummary(m, linkTo(false)), embed: null };
  share.embed = embedDialog(() => linkTo(true), m.target.name || 'Sky view');
  // The published type of a gallery target, from the index; null for a position search.
  const published = Promise.resolve(targets).then((ts) => ts?.find((t) => t.slug === state.target)?.known_type || null, () => null);

  const canvas = el('canvas', { class: 'stage', role: 'img', tabindex: '0' });
  const readout = el('p', { class: 'mono small readout', text: skyText(null) });
  const frameLive = el('p', { class: 'sr-only', 'aria-live': 'polite' });
  const stage = new Stage(canvas, m, images, {
    onHover: (s) => { readout.textContent = skyText(s); },
    onZoom: (z) => { controls?.syncZoom(z); if (started) { setUrl({ zoom: z }); strip?.update(player.current, stage.view()); } },
    onOffscreen: (off) => { if (controls) controls.recentre.hidden = !off; },
  });
  let controls = null, strip = null, started = false, ready = false;
  const framing = defaultFraming(m);
  const followable = canFollow(m.frames);
  const cueEl = el('p', { class: 'gap-cue', 'aria-hidden': 'true', hidden: true });
  let cueTimer = null, prevFrame = null, gapCache = { frames: null, gaps: [] };
  const details = el('div', { class: 'frame-card' });
  const updateDetails = frameDetails(details, body ? 'measured at its JPL Horizons position' : undefined, m.frames);
  const badge = flagBadge(m.frames);
  const stageWrap = el('div', { class: 'stage-wrap' }, [canvas, badge.node, cueEl]);
  // One short legend line under the image while the frame on screen has hatched gaps.
  const hatchLegend = el('p', { class: 'small muted hatch-legend', text: HATCH_LEGEND, hidden: true });
  const hatchNote = (f) => { hatchLegend.hidden = !(f?.gaps_image && stage.layers.gaps); };

  let bands = resolveBands(state.bands, m.frames, state.preset);
  // A link to one frame whose set is not in the default blink opens that set.
  const linked = m.frames.find((f) => f.id === state.frame);
  if (linked && !bands.includes(linked.band) && !state.bands && !state.preset) bands = [linked.band];
  const timelineHost = el('div', { class: 'timeline-host' });
  const playBtn = el('button', { type: 'button', class: 'btn icon primary', id: 'play', 'aria-label': 'Play' });
  const player = new BlinkPlayer({ onChange: (why) => onChange(why) });
  const timeline = new Timeline(timelineHost, m.frames, (i) => { player.pause(); player.seekIndex(i); });
  /** Show one frame, paused, blinking its own set (band strip and "what was rejected"). */
  function pickFrame(f) {
    compare.stop();
    bands = [f.band];
    picker.set(bands);
    player.pause();
    player.setFrames(activeFrames(m.frames, bands));
    player.seekId(f.id);
    setUrl({ bands, preset: null, frame: f.id });
  }
  strip = bandStrip({ m, images, onPick: pickFrame, fc: state.fc, onFc: (on) => setUrl({ fc: on }), brownDwarf: isBrownDwarf(null, m.match?.class) });
  published.then((p) => { if (p) strip.setBrownDwarf(isBrownDwarf(p, m.match?.class)); });
  const compare = compareMode({ m, images, stage, current: () => player.current, playing: () => player.frames, initial: state,
    onChange: (c) => { setUrl(c); if (ready && c.cmp) keepInView(stageWrap); },
    onToggle: (on) => { if (on) player.pause(); badge.show(on ? null : player.current); if (!on) onChange('frames'); } });

  /** A brief "15 years later" on the image when the blink jumps across a long gap in time. */
  function showGapCue(why, f) {
    const prev = prevFrame;
    prevFrame = f;
    if (gapCache.frames !== player.frames) gapCache = { frames: player.frames, gaps: findGaps(player.frames) };
    const cue = ['tick', 'step', 'seek'].includes(why) ? gapCue(prev, f, gapCache.gaps) : null;
    clearTimeout(cueTimer);
    stage.setGapPath(null);
    cueEl.hidden = !cue;
    if (!cue) return;
    cueEl.textContent = cue;
    frameLive.textContent = `${cue}: ${f.date.slice(0, 10)}`;
    const from = objectPx({ centroid_px: null, predicted_px: prev.predicted_px }) || objectPx(prev);
    const to = f.predicted_px || objectPx(f);
    if (from && to) stage.setGapPath({ from, to });
    cueTimer = setTimeout(() => { cueEl.hidden = true; stage.setGapPath(null); }, 2600);
  }

  function onChange(why) {
    const f = player.current;
    stage.show(f, player.frames);
    timeline.update(player.frames, f);
    updateDetails(f, stage.grid.scale);
    strip.update(f, stage.view());
    if (!compare.active()) badge.show(f);
    hatchNote(f);
    showGapCue(why, f);
    playBtn.replaceChildren(icon(player.playing ? 'pause' : 'play'));
    playBtn.setAttribute('aria-label', player.playing ? 'Pause' : 'Play');
    canvas.setAttribute('aria-label', f ? `${setLabel(f)} image from ${f.date.slice(0, 10)}${f.centroid_px || body ? '' : ', object not detected'}` : 'No frame');
    if (why !== 'tick' && f) frameLive.textContent = `${f.date.slice(0, 10)}, ${setLabel(f)}`;
    if (['pause', 'step', 'seek'].includes(why) && f) setUrl({ frame: f.id });
    if (why === 'play') { compare.stop(); setUrl({ frame: null }); }
  }
  playBtn.addEventListener('click', () => player.toggle());

  const speed = el('input', { type: 'range', min: '0.5', max: '8', step: '0.5', value: '2', id: 'speed', 'aria-label': 'Blink speed, frames per second',
    onInput: (e) => player.setFps(Number(e.target.value)) });
  let optedOut = state.follow === false;
  function setFollow(on, auto) {
    if (on && !followable) return;
    if (!auto) optedOut = !on;
    stage.setFollow(on);
    controls.follow.checked = on;
    controls.setNote(on, auto);
    setUrl({ follow: on });
  }
  controls = viewControls({
    stage, followable,
    onFollow: setFollow,
    onZoomInput: (z) => {
      stage.setZoom(z);
      if (!stage.follow && !optedOut && shouldAutoFollow(stage.zoom, framing.fitZoom, followable)) setFollow(true, true);
    },
    onFit: () => { stage.setFollow(false); controls.follow.checked = false; controls.setNote(false, false); stage.setView(framing.zoom, framing.cx, framing.cy); setUrl({ follow: null, zoom: null }); },
  });
  const startZoom = clampZoom(state.zoom ?? framing.zoom);
  stage.setView(startZoom, framing.cx, framing.cy);
  controls.setNote(false, false);
  // A body is followed by default: it stays centred and the stars slide past.
  if (state.follow === true || (state.follow == null && (body || shouldAutoFollow(startZoom, framing.fitZoom, followable)))) {
    stage.follow = followable; controls.follow.checked = followable; controls.setNote(followable, state.follow !== true);
  }
  started = true;

  const picker = bandPicker(m.frames, bands, (next, presetId) => {
    compare.stop();
    bands = next;
    player.setFrames(activeFrames(m.frames, bands));
    setUrl(presetId ? { preset: presetId, bands: null } : { bands, preset: null });
    keepInView(stageWrap);
  });

  // Every overlay toggle drawn for a layer (the full list, and the quick pair by Follow), kept in step.
  const toggles = new Map();
  const setLayer = (key, on) => {
    stage.layers[key] = on; stage.draw();
    for (const b of toggles.get(key)) b.checked = on;
    if (key === 'gaps') hatchNote(player.current);
  };
  const layerToggle = ([key, label, color, help], cls) => {
    const disabled = (key === 'gaps' && !m.frames.some((f) => f.gaps_image)) || (key === 'track' && !m.track.length) || (key === 'predicted' && !m.frames.some((f) => f.predicted_px))
      || (key === 'gaia' && !m.overlays.gaia.length) || (key === 'catwise' && !m.overlays.catwise.length);
    const box = el('input', { type: 'checkbox', checked: stage.layers[key] && !disabled, disabled, 'data-layer': key,
      onChange: (e) => setLayer(key, e.target.checked) });
    toggles.set(key, [...(toggles.get(key) || []), box]);
    return el('label', { class: cls, title: help }, [box, el('span', { class: 'swatch', style: `background:${color}` }), ` ${label}${disabled ? ' (none)' : ''}`]);
  };
  const layerBoxes = LAYERS.map((l) => layerToggle(l, 'check'));
  const quickLayers = el('span', { class: 'quick-layers', role: 'group', 'aria-label': 'Catalogue overlays' },
    LAYERS.filter(([key]) => QUICK_LAYERS.includes(key)).map((l) => layerToggle(l, 'check')));

  const hasWise = m.frames.some((f) => f.mission === 'WISE');
  const blink = el('section', { class: 'card blink', id: 'blink', 'aria-labelledby': 'blink-h' }, [
    el('h2', { id: 'blink-h', text: body ? `SPHEREx follows ${m.target.name || 'the body'} through one pass` : hasWise ? 'Is it moving? WISE from 2010, then SPHEREx' : 'Is it moving? SPHEREx images over time' }),
    body ? el('p', { class: 'small muted', text: blinkNote(m) }) : null,
    stageWrap,
    el('div', { class: 'controls' }, [
      el('button', { type: 'button', class: 'btn icon', id: 'prev-frame', 'aria-label': 'Previous frame', title: 'Previous frame', onClick: () => { compare.stop(); player.step(-1); } }, [icon('prev')]),
      playBtn,
      el('button', { type: 'button', class: 'btn icon', id: 'next-frame', 'aria-label': 'Next frame', title: 'Next frame', onClick: () => { compare.stop(); player.step(1); } }, [icon('next')]),
      el('label', { class: 'ctl' }, ['Speed ', speed]),
      el('span', { class: 'spacer' }),
      controls.followLabel,
      quickLayers,
      controls.recentre,
    ]),
    timelineHost,
    hatchLegend,
    readout, frameLive,
    picker.root,
    compare.root,
    strip.root,
    el('div', { class: 'this-frame' }, [el('p', { class: 'label', text: 'The image on screen' }), details]),
    el('details', { class: 'more-controls' }, [
      el('summary', { text: 'More controls: zoom, image sets, overlays, keys' }),
      el('div', { class: 'more-body' }, [
        controls.zoomRow,
        picker.sets,
        el('fieldset', { class: 'layers' }, [el('legend', { text: 'Overlays' }), ...layerBoxes]),
        el('p', { class: 'small muted keys', text: 'Keys: space plays or pauses, ← → step (not while comparing). With the image focused, + and − zoom. Ctrl or Cmd with the wheel, or a two-finger pinch, also zooms; drag the image to pan.' }),
      ]),
    ]),
  ]);

  const specHost = el('div');
  const pubLine = el('p', { class: 'verdict-published', hidden: true });
  published.then((p) => { if (p && !body) { pubLine.replaceChildren('Published type: ', el('b', { text: p })); pubLine.hidden = false; } });
  const specSection = body ? bodySection(m, { spec: state.spec, onSpecChange: (id) => setUrl({ spec: id }), baseUrl }) : el('section', { class: 'card spectrum', id: 'spectrum', 'aria-labelledby': 'spec-h' }, [
    el('h2', { id: 'spec-h', text: 'What is it? The SPHEREx spectrum' }), specHost, afterSpectrum(m, share),
  ]);

  const hrefFor = (slug) => href({ target: slug, ra: null, dec: null, pmra: null, pmdec: null, epoch: null, fov: null,
    frame: null, bands: null, preset: null, spec: null, cmp: null, a: null, b: null, zoom: null, follow: null, fc: false });

  // A position search is a live view; a gallery target is a stored one, so retrying it changes nothing.
  const live = !!apiBase && !state.target;
  const degraded = degradedNotice(m, { live, onRetry: () => window.location.reload() });
  const notes = notesBar(summariseNotes([...m.warnings, ...problems], { degraded: m.degraded, live: live, hasMatch: !!m.match }));
  const rejected = rejectedPanel(m, (f) => { pickFrame(f); canvas.scrollIntoView({ block: 'nearest' }); });
  host.replaceChildren(el('div', { class: 'view' }, [
    degraded,
    ...viewHeader(m, state, share),
    fieldBanner(m),
    verdictStrip(m, published, state.target),
    el('div', { class: 'view-grid' }, [blink, el('div', { class: 'side' }, [
      body ? bodyPanel(m) : motionPanel(m, useMotionLink(m, state, href, apiBase)),
      specSection,
    ])]),
    fieldMoversSection(m, (on) => { stage.movers = on; stage.draw(); }),
    factsSection(m),
    variabilityBlock(state.target),
    el('section', { class: 'trust', id: 'data', 'aria-labelledby': 'data-h' }, [
      el('h2', { id: 'data-h', text: 'Check the data' }),
      el('div', { class: 'trust-grid' }, [
        el('div', { class: 'trust-col' }, [notes, rejected, notes || rejected ? null : el('p', { class: 'card small muted', text: 'All frames were retained. There are no quality warnings for this view.' })]),
        locatorPanel({ ra: m.center.ra, dec: m.center.dec, fovArcsec: m.fov_arcsec, currentSlug: state.target, targets, hrefFor }),
        linkOutBlock(m.target, m.fov_arcsec),
      ]),
      el('div', { class: 'chrome' }, [honestyPanel()]),
      creditsBlock(m),
    ]),
    state.embed ? el('p', { class: 'embed-link' }, [el('a', { href: href({ embed: false }), target: '_blank', rel: 'noopener', text: 'Open the full view ↗' })]) : null,
  ]));

  if (!body) renderSpectrum(specHost, m, { spec: state.spec, onSpecChange: (id) => setUrl({ spec: id }), published: pubLine });
  player.setFrames(activeFrames(m.frames, bands));
  const deepLinked = state.frame && player.seekId(state.frame);
  compare.start();
  ready = true;
  // Open on the newest SPHEREx image, so the first still is SPHEREx and the blink then runs from 2010.
  if (!deepLinked && !compare.active() && !body) player.startAt(player.frames.findLastIndex((f) => f.mission === 'SPHEREx'));
  if (!deepLinked && !compare.active() && !prefersReducedMotion()) player.play();

  document.addEventListener('keydown', (e) => {
    if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.altKey || isTypingTarget(e.target, e.key) || compare.active()) return;
    if (e.key === ' ') { player.toggle(); e.preventDefault(); }
    else if (e.key === 'ArrowRight') { player.step(1); e.preventDefault(); }
    else if (e.key === 'ArrowLeft') { player.step(-1); e.preventDefault(); }
  }, { signal });
  return { player, stage };
}
