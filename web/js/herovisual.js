// The landing page's featured blink: the looping images, the tool's answer beside the
// published one, a one-line caption and the way in to the full view.

import { el, prefersReducedMotion } from './dom.js';
import { compassWord, describeMotion, motionBasis, motionHeadline, motionSignificant, insignificantText } from './summary.js';
import { typeRangeText, showsType, hasPair } from './matchtext.js';
import { defaultFraming } from './framing.js';
import { motionVector, decimalYear } from './sky.js';
import { defaultBands, activeFrames } from './framesets.js';
import { BlinkPlayer, preloadImages } from './player.js';
import { Stage } from './stage.js';
import { icon } from './icons.js';

/**
 * Caption for the hero, computed from the manifest's measured motion (else from the frame positions).
 * `numbers: false` leaves the measured and catalogue rates to the readout beside it.
 */
export function heroCaption(m, frames, { numbers = true } = {}) {
  const y0 = Math.floor(decimalYear(frames[0].mjd)), y1 = Math.floor(decimalYear(frames.at(-1).mjd));
  const mm = m.measured_motion;
  const meas = mm && describeMotion(mm.pmra_masyr, mm.pmdec_masyr);
  const scale = m.fov_arcsec / m.size_px;
  const pts = frames.map((f) => f.centroid_px || f.predicted_px).filter(Boolean);
  let arcsec = null, dir = null;
  if (meas && meas.arcsecPerYear >= 0.05) {
    arcsec = meas.arcsecPerYear * (mm.baseline_years ?? y1 - y0);
    dir = compassWord(meas.pa);
  } else if (pts.length >= 2) {
    const [a, b] = [pts[0], pts.at(-1)];
    arcsec = Math.hypot(b[0] - a[0], b[1] - a[1]) * scale;
    // Image x grows west and y grows south, so east = -dx and north = -dy.
    dir = compassWord(motionVector(-(b[0] - a[0]), -(b[1] - a[1])).pa);
  }
  if (arcsec == null || arcsec < 2 * scale) return `Each flash is the same patch of sky in a different year, ${y0} to ${y1}. Nothing here moves measurably.`;
  const said = meas && numbers
    ? ` Measured: ${meas.arcsecPerYear.toFixed(2)} arcseconds a year${motionBasis(mm).short ? ` ${motionBasis(mm).short}` : ''}${m.target.pmra_masyr != null ? `; the catalogue says ${describeMotion(m.target.pmra_masyr, m.target.pmdec_masyr)?.arcsecPerYear.toFixed(2)}` : ''}.`
    : '';
  return `Each image shows the same patch of sky on a different date. The dot drifting ${dir} moved ${arcsec.toFixed(0)} arcseconds between ${y0} and ${y1}.${said} Watch the dot against the more distant stars. Its steady drift is a clue that it lies nearby.`;
}

/**
 * The two answers under the hero image: measured motion against the catalogue, and the
 * spectrum's type against the published one. Pure.
 * @param {object} m manifest
 * @param {string|null} published the published type from the gallery index
 * @returns {{label: string, value: string, sub: string, ok: boolean}[]}
 */
export function heroReadout(m, published = null) {
  const out = [];
  const mm = m.measured_motion;
  const meas = mm && describeMotion(mm.pmra_masyr, mm.pmdec_masyr);
  if (meas && !motionSignificant(mm)) {
    out.push({ label: 'Motion, measured', value: 'None we can measure', sub: insignificantText(mm), ok: false });
  } else if (meas) {
    const head = motionHeadline(mm, m.target);
    const cat = describeMotion(m.target.pmra_masyr, m.target.pmdec_masyr);
    out.push({ label: 'Motion, measured', value: `${meas.arcsecPerYear.toFixed(2)}″ a year`,
      sub: cat ? `catalogue ${cat.arcsecPerYear.toFixed(2)}${head ? (head.agree ? ': agrees' : ': differs') : ''}` : 'no catalogue motion', ok: !!head?.agree });
  }
  const match = m.match;
  if (match && showsType(match) && !hasPair(match) && typeRangeText(match)) {
    out.push({ label: 'Type, from the spectrum', value: typeRangeText(match), sub: published ? `published ${published}` : `${match.confidence} confidence`, ok: false });
  }
  return out;
}

/**
 * Fill `host` with the featured blink for one gallery target.
 * @param {HTMLElement} host
 * @param {object} entry gallery index entry
 * @param {URL} manifestUrl
 * @param {object} m validated manifest
 */
export async function heroVisual(host, entry, manifestUrl, m) {
  try {
    const frames = activeFrames(m.frames, defaultBands(m.frames));
    const images = await preloadImages(frames, manifestUrl);
    const canvas = el('canvas', { class: 'stage', role: 'img', 'aria-label': `Blinking images of ${m.target.name || 'the featured target'} from ${frames[0].date.slice(0, 4)} to ${frames.at(-1).date.slice(0, 4)}` });
    const stage = new Stage(canvas, m, images, { compact: true });
    stage.layers = { ...stage.layers, centroids: false, scale: true };
    const fr = defaultFraming({ ...m, frames });
    stage.setView(fr.zoom, fr.cx, fr.cy);
    const btn = el('button', { type: 'button', class: 'btn icon primary hero-play' });
    const player = new BlinkPlayer({
      fps: 2.5,
      onChange: () => {
        stage.show(player.current, frames);
        btn.replaceChildren(icon(player.playing ? 'pause' : 'play'));
        btn.setAttribute('aria-label', player.playing ? 'Pause the blink' : 'Play the blink');
      },
    });
    btn.addEventListener('click', () => player.toggle());
    const readout = heroReadout(m, entry.known_type);
    host.replaceChildren(
      el('p', { class: 'label hero-target', text: `${entry.name}, ${frames[0].date.slice(0, 4)} to ${frames.at(-1).date.slice(0, 4)}` }),
      el('div', { class: 'hero-stage' }, [canvas, btn]),
      readout.length ? el('dl', { class: 'hero-readout' }, readout.map((r) => el('div', {}, [
        el('dt', { text: r.label }),
        el('dd', {}, [el('span', { class: 'readout-value', text: r.value }), el('span', { class: `readout-sub${r.ok ? ' ok' : ''}`, text: r.sub })]),
      ]))) : null,
      el('p', { class: 'hero-caption', text: heroCaption(m, frames, { numbers: !readout.length }) }),
      el('a', { class: 'btn primary', href: `?target=${encodeURIComponent(entry.slug)}`, 'aria-label': `See the full check for ${entry.name}`, text: 'Explore this object' }),
    );
    player.setFrames(frames);
    // Rest on the newest SPHEREx image; the blink then runs on from 2010.
    player.startAt(frames.findLastIndex((f) => f.mission === 'SPHEREx'));
    if (!prefersReducedMotion()) player.play();
  } catch (err) {
    host.replaceChildren(el('p', { class: 'muted', text: `The featured view could not be loaded (${err.message}). The gallery below still works.` }));
  }
}
