// Static-ish panels of the view: motion readout, frame details, the honest
// limits panel, credits, and the share dialog.

import { el, shortDate, copyText, flash } from './dom.js';
import { describeMotion, motionBasis, motionHeadline, noMotionHeadline, noMotionReason, motionSignificant, insignificantText } from './summary.js';
import { vettingRows } from './vetting.js';
import { frameFlag } from './flags.js';
import { setLabel, nameBands } from './labels.js';
import { linkOuts } from './links.js';
import { gaiaCounterpart } from './gaiacheck.js';
import { rejectedSummary } from './rejected.js';
import { archiveNote } from './archivestatus.js';

export const DEGRADED_TEXT = 'Some archive data could not be fetched just now, so this view is incomplete. Try again in a few minutes.';

/** Calm notice for a view built from partial data; null otherwise. Retry only for live views. */
export function degradedNotice(m, { live, onRetry }) {
  if (!m.degraded || !live) return null;
  return el('div', { class: 'notice degraded', role: 'status' }, [
    el('p', { text: DEGRADED_TEXT }),
    archiveNote(), // archive uptime (js/archivestatus.js)
    live ? el('button', { type: 'button', class: 'btn', text: 'Retry', onClick: onRetry }) : null,
  ]);
}

/** Notice for a view without proper motion, with a one-click "use the measured motion". */
function noMotionNotice(m, useMotion) {
  if (m.track.length) return null;
  const mm = m.measured_motion;
  const meas = mm && describeMotion(mm.pmra_masyr, mm.pmdec_masyr, mm.err_masyr);
  const parts = [el('p', { text: 'No proper motion was given, so no track is drawn and the spectrum is taken at the fixed position. For a fast mover that is the wrong spot by 2025.' })];
  if (meas && !motionSignificant(mm)) {
    // An insignificant motion must not be promoted to a track.
    parts.push(el('p', { text: `The images give no motion we can measure (${insignificantText(mm, 'arcsec per year')}), so there is no motion to use.` }));
  } else if (meas) {
    parts.push(el('p', { text: `The images themselves give ${meas.words}.` }));
    parts.push(useMotion.href
      ? el('a', { class: 'btn', href: useMotion.href, text: 'Use this motion' })
      : el('p', { class: 'small muted', text: useMotion.reason }));
  }
  return el('div', { class: 'notice', role: 'note' }, parts);
}

function vettingBlock(v) {
  const rows = vettingRows(v);
  if (!rows.length) return null;
  return el('details', { class: 'more-evidence' }, [el('summary', { text: 'Measurement details' }), el('div', { class: 'vetting' }, rows.map((r) => el('div', { class: 'motion-row' }, [
    el('span', { class: 'motion-label', text: r.label }),
    el('span', { class: 'mono', text: r.value }),
    r.help ? el('span', { class: 'small muted', text: r.help }) : null,
  ])))]);
}

/** The Gaia counterpart line under the motion rows, or null for a Solar System body. */
function gaiaRow(m) {
  const g = gaiaCounterpart(m);
  if (!g) return null;
  const head = { match: 'In Gaia DR3', unrelated: 'Gaia DR3 neighbour', none: 'No Gaia star here', limited: 'No Gaia star here (bright stars only)', unchecked: 'Gaia DR3' }[g.status];
  return el('div', { class: `motion-row gaia-row gaia-${g.status}` }, [
    el('span', { class: 'motion-label', text: head }),
    el('span', { class: 'small', text: g.text }),
  ]);
}

/**
 * @param {object} m manifest
 * @param {{href: string|null, reason: string}} useMotion where "Use this motion" goes, or why it can't
 */
export function motionPanel(m, useMotion = { href: null, reason: '' }) {
  const mm = m.measured_motion;
  const t = m.target;
  const meas = mm && describeMotion(mm.pmra_masyr, mm.pmdec_masyr, mm.err_masyr);
  const cat = describeMotion(t.pmra_masyr, t.pmdec_masyr);
  const rows = [];
  if (meas) {
    const years = mm.baseline_years ?? 16;
    const moved = meas.arcsecPerYear * years;
    const px = moved / (m.fov_arcsec / m.size_px);
    const basis = motionBasis(mm);
    const n = Math.round(px);
    const span = `${moved.toFixed(1)} arcsec in total, ${n >= 1 ? `about ${n} ${n === 1 ? 'pixel' : 'pixels'}` : 'less than one pixel'} in these images.`;
    rows.push(el('div', { class: 'motion-row' }, [
      el('span', { class: 'motion-label', text: 'Measured here' }),
      el('span', { class: 'motion-words', text: meas.words }),
      el('span', { class: 'small muted', text: basis.allFrames ? `${basis.sentence}. Over ${years.toFixed(1)} years that is ${span}` : `${basis.sentence} over ${years.toFixed(1)} years: ${span}` }),
      el('span', { class: 'mono small', text: meas.exact }),
    ]));
  } else {
    rows.push(el('div', { class: 'motion-row' }, [
      el('span', { class: 'motion-label', text: 'Measured here' }),
      el('span', { class: 'motion-words', text: 'Not measured' }),
      el('span', { class: 'small muted', text: noMotionReason(m) || 'The object was found in fewer than two frames, so no motion could be measured.' }),
    ]));
  }
  rows.push(el('div', { class: 'motion-row' }, [
    el('span', { class: 'motion-label', text: 'Catalogue' }),
    el('span', { class: 'motion-words', text: cat ? cat.words : 'Unknown' }),
    cat ? el('span', { class: 'mono small', text: cat.exact }) : el('span', { class: 'small muted', text: 'No published motion for this position, so no predicted track is drawn.' }),
  ]));
  const head = motionHeadline(mm, t);
  return el('section', { class: 'card motion', id: 'motion', 'aria-labelledby': 'motion-h' }, [
    el('h2', { id: 'motion-h', text: 'How fast is it moving?' }),
    head ? el('p', { class: `motion-headline ${head.agree ? 'agree' : 'differ'}`, text: head.text })
      : !mm ? el('p', { class: 'motion-headline unmeasured', text: noMotionHeadline(m) }) : null,
    el('div', { class: 'motion-pair' }, rows),
    gaiaRow(m),
    noMotionNotice(m, useMotion),
    vettingBlock(m.vetting),
  ]);
}

/** Details for the frame on screen. Returns an updater. `frames` name band ids in pipeline notes. */
export function frameDetails(host, notFound = 'not detected in this frame', frames = []) {
  const dl = el('dl', { class: 'facts' });
  const warn = el('ul', { class: 'frame-warnings' });
  host.replaceChildren(el('h3', { class: 'sr-only', text: 'This frame' }), dl, warn);
  return (f, scale) => {
    if (!f) return;
    const fact = (k, v) => [el('dt', { text: k }), el('dd', { text: v })];
    const wl = f.wavelength_um ? `${f.wavelength_um[0]}–${f.wavelength_um[1]} µm` : '—';
    const found = f.centroid_px
      ? `found${f.centroid_err_arcsec != null ? ` (±${f.centroid_err_arcsec}″)` : ''}`
      : notFound;
    const offset = f.centroid_px && f.predicted_px
      ? `${(Math.hypot(f.centroid_px[0] - f.predicted_px[0], f.centroid_px[1] - f.predicted_px[1]) * scale).toFixed(1)}″ from prediction`
      : null;
    dl.replaceChildren(
      ...fact('Date', `${shortDate(f.date)}${f.date_span_days ? `, stacked over ${f.date_span_days < 10 ? f.date_span_days.toFixed(1) : Math.round(f.date_span_days)} days` : ''}`),
      ...fact('Images', `${setLabel(f)}${f.mission === 'WISE' ? `, passband ${wl}` : ''}`),
      ...fact('Object', offset ? `${found}, ${offset}` : found),
      ...fact('Stack', `${f.n_exposures ?? '?'} exposure${f.n_exposures === 1 ? '' : 's'}${f.native_pixscale_arcsec ? `, ${f.native_pixscale_arcsec}″ pixels` : ''}${f.flag_fraction ? `, ${(f.flag_fraction * 100).toFixed(0)}% pixels flagged` : ''}`),
    );
    const flag = frameFlag(f);
    warn.replaceChildren(...(flag ? [el('li', { text: nameBands(flag.long, frames) })] : []));
  };
}

/** "Which measurements were left out?": a closed disclosure; each listed frame opens in the blink. Null when nothing was. */
export function rejectedPanel(m, onPick) {
  const r = rejectedSummary(m);
  if (!r) return null;
  const frameList = (items) => el('ul', { class: 'rej-list frames' },items.map((x) => el('li', {}, [
    el('button', { type: 'button', class: 'linkish', text: x.text, title: 'Show this frame in the blink', onClick: () => onPick(x.frame) }),
  ])));
  const part = (title, note, items) => el('div', { class: 'rej-part' }, [
    el('h3', { text: title }), note ? el('p', { class: 'small muted', text: note }) : null, items.length ? frameList(items) : null,
  ]);
  return el('details', { class: 'card rejected' }, [
    el('summary', {}, [el('h2', { text: 'Which measurements were left out?' })]),
    r.flagged.length ? part('Frames with the most flagged pixels', r.flaggedNote, r.flagged) : null,
    r.missed.length ? part('Object not found', r.missedNote, r.missed) : null,
    r.reasons.length ? part('Notes on individual images', '', []) : null,
    r.reasons.length ? el('ul', { class: 'rej-list small' }, r.reasons.map((x) => el('li', { text: x.text }))) : null,
  ]);
}

export function honestyPanel() {
  const items = [
    'SPHEREx has 6.15 arcsecond pixels and a few passes per spot since 2025, so on its own a nearby brown dwarf shifts by only a pixel or two. WISE images from 2010 to 2024 stretch the baseline to 16 years, with no WISE data from 2011 to late 2013.',
    'A planet a few hundred to a thousand au away would shift by roughly 7 to 25 arcminutes between SPHEREx passes six months apart, mostly parallax, far outside this small fixed field. This view will not catch it.',
    'Fast movers such as asteroids cross the field within hours, so each shows up in only one or two exposures and is removed when the exposures of a pass are stacked.',
    'Bright stars saturate SPHEREx. Their images and spectra are unreliable; a badge on the image says when this was flagged.',
    'The spectrum is measured at the predicted position, with a fit that reaches a few SPHEREx pixels around it. A second star that close can fool the match; when the star catalogue shows one, the view says so.',
    'Template types are a guide. For a more precise type, look for a published measurement from a dedicated spectrograph.',
  ];
  return el('details', { class: 'card honesty', open: true }, [
    el('summary', {}, [el('h2', { text: 'What this can and can’t do' })]),
    el('ul', {}, items.map((t) => el('li', { text: t }))),
  ]);
}

/** Plain links to other public tools for this position (new tab, no referrer). */
export function linkOutBlock(t, fovArcsec) {
  const links = linkOuts(t.ra, t.dec, fovArcsec);
  if (!links.length) return null;
  return el('section', { class: 'card links', 'aria-labelledby': 'links-h' }, [
    el('h2', { id: 'links-h', text: 'Open this position elsewhere' }),
    el('ul', {}, links.map((l) => el('li', {}, [
      el('a', { href: l.href, target: '_blank', rel: 'noopener noreferrer', text: `${l.label} ↗` }),
      el('span', { class: 'small muted', text: ` ${l.help}` }),
    ]))),
  ]);
}

export function creditsBlock(m) {
  const list = m.credits.length ? m.credits : ['No data credits were supplied with this view.'];
  return el('section', { class: 'credits', 'aria-labelledby': 'credits-h' }, [
    el('h2', { id: 'credits-h', text: 'Data and references' }),
    el('ul', {}, list.map((c) => el('li', { text: c }))),
    m.generated ? el('p', { class: 'small muted', text: `View built ${m.generated}.` }) : null,
  ]);
}

/** Share dialog with the embed snippet. */
export function embedDialog(getEmbedUrl, title) {
  const ta = el('textarea', { class: 'mono', rows: '4', readonly: true, 'aria-label': 'Embed code' });
  const status = el('span', { class: 'small', 'aria-live': 'polite' });
  const dlg = el('dialog', { class: 'dialog', 'aria-labelledby': 'embed-h' }, [
    el('h2', { id: 'embed-h', text: 'Embed this view' }),
    el('p', { class: 'muted', text: 'Paste this into a web page or forum that allows iframes. The embedded view shows the object without the site header and footer.' }),
    ta,
    el('div', { class: 'row' }, [
      el('button', { type: 'button', class: 'btn primary', text: 'Copy code',
        onClick: async () => flash(status, (await copyText(ta.value)) ? 'Copied.' : 'Select the text and copy it.') }),
      el('button', { type: 'button', class: 'btn', text: 'Close', onClick: () => dlg.close() }),
      status,
    ]),
  ]);
  document.body.append(dlg);
  return () => {
    const src = getEmbedUrl().replace(/"/g, '&quot;');
    ta.value = `<iframe src="${src}" title="${title.replace(/"/g, '&quot;')}" width="100%" height="760" style="border:0" loading="lazy"></iframe>`;
    dlg.showModal();
    ta.select();
  };
}
