// Solar System body mode: the side panel on how the body moves, and the section that replaces the
// brown-dwarf spectrum for a manifest with `solar_system`: a pass selector, the reflectance
// spectrum with its ice-band windows (drawn by spectrum.js), measured band depths, the
// body-centred images of the pass and a note on Planet X. Wording lives in bodytext.js.

import { el } from './dom.js';
import { renderSpectrum } from './spectrum.js';
import { ALL, pretty, reflSpectra, reflYRange, bodyFrames, depthText, readingText, iceSentence, planetXNote, bodyFacts, detectionNote, compositionIceNote } from './bodytext.js';

const um = (w) => (w.length === 2 ? `${w[0]}–${w[1]} µm` : '');

/** Side card: distances and on-sky rate from JPL Horizons, in place of the proper-motion panel. */
export function bodyPanel(m) {
  const ss = m.solar_system;
  const f = bodyFacts(ss);
  const fact = (k, v) => (v == null ? [] : [el('dt', { text: k }), el('dd', { text: v })]);
  return el('section', { class: 'card motion', id: 'motion', 'aria-labelledby': 'body-h' }, [
    el('h2', { id: 'body-h', text: 'How it moves' }),
    el('dl', { class: 'facts' }, [
      ...fact('Type', ss.type),
      ...fact('From the Sun', f.r_au != null ? `${f.r_au.toFixed(1)} au` : null),
      ...fact('From SPHEREx', f.delta_au != null ? `${f.delta_au.toFixed(1)} au` : null),
      ...fact('On the sky', f.rate != null ? `${f.rate.toFixed(1)} arcsec an hour` : null),
      ...fact('In the blink', f.track != null ? `${Math.round(f.track)} arcsec from its first exposure to its last` : null),
      ...fact('Visual magnitude', f.vmag != null ? f.vmag.toFixed(1) : null),
    ]),
    el('p', { class: 'small muted', text: 'Positions come from JPL Horizons as seen from SPHEREx. A Solar System body moves in hours what a nearby star moves in years, so it is measured at its predicted position in every single exposure rather than in stacks taken years apart.' }),
  ]);
}

function howTo() {
  return el('details', { class: 'howto' }, [
    el('summary', { text: 'How to read this plot' }),
    el('p', { text: 'Each dot is the body’s brightness at one wavelength divided by the Sun’s, so a grey surface would sit on a flat line at 1 (the average over 0.75–1.3 µm). Bars are 1-sigma uncertainties.' }),
    el('p', { text: 'Shaded strips are windows where ices can absorb, labelled by wavelength in µm. In general water ice has bands near 1.5, 2.0 and 3.0, methane ice near 2.3, and both near 1.7 and 3.3; which ice this body has is said under the band-depth table. Ice swallows light there, so the dots dip.' }),
    el('p', { text: 'A point below zero is noise around a band that returns almost no light; the table reports such a band as a lower limit on its depth. Points measured at less than 3 sigma are drawn faint and without bars.' }),
    el('p', { text: 'The scale is set by the points short of 3.8 µm. Beyond that the body is faint and some points scatter off the plot; double-click the plot to see them all.' }),
  ]);
}

/** "2.3 um (CH4)" as the band's wavelength and, apart, the ice its window is sensitive to. */
function bandParts(label) {
  const m = /^(.*?)\s*\((.*)\)\s*$/.exec(label || '');
  const ices = (m ? m[2] : '').replace(/CH4/g, 'methane ice').replace(/H2O/g, 'water ice');
  return { band: pretty(m ? m[1] : label), ices: pretty(ices) || '—' };
}

function depthTable(refl) {
  const rows = (refl?.band_depths || []).map((d) => el('tr', {}, [
    el('td', { text: bandParts(d.label).band }),
    el('td', { text: bandParts(d.label).ices }),
    el('td', { text: um(d.wl_um) }),
    el('td', { class: d.detected ? 'num strong' : 'num', text: depthText(d) }),
  ]));
  return el('div', { class: 'table-wrap depth-table' }, [el('table', {}, [
    el('caption', { class: 'sr-only', text: 'Measured band depths' }),
    el('thead', {}, [el('tr', {}, ['Band', 'Ices with a band near here (in general)', 'Window', 'Depth below the continuum'].map((h) => el('th', { scope: 'col', text: h })))]),
    el('tbody', {}, rows),
  ])]);
}

function bodyImages(m, id, baseUrl) {
  const ss = m.solar_system;
  const frames = bodyFrames(ss, id);
  if (!frames.length) return el('p', { class: 'small muted', text: 'No body-centred images for this pass.' });
  return el('div', { class: 'strip-row' }, frames.map((f) => el('figure', { class: 'strip-cell body-cell' }, [
    el('img', { class: 'strip-canvas', src: new URL(f.image, baseUrl).href, width: '84', height: '84', loading: 'lazy',
      alt: `${m.target.name || 'The body'} at ${um(f.wavelength_um)}, ${f.n_exposures ?? 'several'} exposures centred on it` }),
    el('figcaption', { class: 'strip-label', text: um(f.wavelength_um) }),
  ])));
}

/**
 * The body-mode section. The pass buttons are the spectrum's own segmented control; choosing one
 * redraws the plot and updates the sentence, the depths and the images here.
 * @param {object} m validated manifest with `solar_system`
 * @param {{spec: string|null, onSpecChange: (id: string) => void, baseUrl: URL|string}} opts
 */
export function bodySection(m, { spec, onSpecChange, baseUrl }) {
  const ss = m.solar_system;
  const name = m.target.name || 'this body';
  const spectra = reflSpectra(ss);
  const line = el('p', { class: 'verdict-line' });
  const sub = el('p', { class: 'muted small' });
  const verdict = el('div', { class: 'verdict conf-high', 'aria-live': 'polite' }, [line, sub]);
  const table = el('div');
  const images = el('div');
  const imgCaption = el('p', { class: 'small muted' });
  const reading = el('p', { class: 'small' });

  function update(id) {
    const refl = ss.reflectance.find((r) => r.spectrum_id === id) || null;
    line.textContent = refl ? iceSentence(name, refl) : 'No reflectance spectrum for this pass.';
    sub.textContent = ss.composition ? `Published: ${pretty(ss.composition).replace(/\.$/, '')}.` : '';
    table.replaceChildren(depthTable(refl));
    imgCaption.textContent = `Every exposure of ${id === ALL ? 'the pass in the blink' : 'this pass'}, one image per detector band, stacked on ${name}’s own position: it stays sharp at the centre while background stars smear into trails.`;
    images.replaceChildren(bodyImages(m, id, baseUrl));
    reading.textContent = readingText(refl);
  }

  const plotHost = el('div');
  const section = el('section', { class: 'card spectrum', id: 'spectrum', 'aria-labelledby': 'spec-h' }, [
    el('h2', { id: 'spec-h', text: `What SPHEREx sees on ${name}: reflected sunlight and ice` }),
    plotHost,
    el('h3', { class: 'sub-h', text: 'Measured band depths' }),
    table,
    compositionIceNote(name, ss) ? el('p', { class: 'small muted', text: compositionIceNote(name, ss) }) : null,
    el('h3', { class: 'sub-h', text: `Every band, centred on ${name}` }),
    imgCaption, images,
    el('div', { class: 'planet-x' }, [
      el('h3', { class: 'sub-h', text: 'What this means for Planet X' }),
      el('p', { text: planetXNote(name, ss) }),
    ]),
    el('details', { class: 'small match-details' }, [
      el('summary', { text: 'Method and published values' }),
      reading,
      ss.method ? el('p', { class: 'muted', text: ss.method }) : null,
      el('p', { class: 'muted', text: detectionNote(ss) }),
      ss.composition_ref ? el('p', { class: 'muted', text: `Published composition: ${pretty(ss.composition_ref)}` }) : null,
    ]),
  ]);
  const first = (spectra.find((s) => s.id === spec) || spectra[0])?.id ?? null;
  update(first);
  const plotM = { ...m, match: null, spectra, features: m.features.map((f) => ({ ...f, label: f.label.split(' ')[0] })) };
  renderSpectrum(plotHost, plotM, {
    spec: first, verdict, howto: howTo(), dimNoisy: true, yRange: (_m, s) => reflYRange(s), yTitle: 'Reflectance (1 = 0.75–1.3 µm mean)', choiceLabel: 'SPHEREx pass',
    onSpecChange: (id) => { update(id); onSpecChange(id); },
  });
  return section;
}
