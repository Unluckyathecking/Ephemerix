// The validation page: fetch data/validation.json and draw it as plain tables.
// Every failure ends in a readable message. All text goes through textContent (see dom.js).
// Each section is one function returning a <section class="card">; render() lists them in
// order, so a new section (its own table or plot) is one function and one line there.

import { el, $ } from './dom.js';
import {
  verdictLabel, viewHref, builtText,
  residualText, framesText, yearSpan, rangeText, reportProblem, groupRows, motionText,
  provisionalLabel, faintTypesText, motionLabel, weakTestNote,
} from './validationtext.js';
import { scoreTiles, notDetected } from './scoreboard.js';
import { mountChrome } from './chrome.js';
import { pageTitle } from './site.js';
import { bodyRecoveryProblem, recoveryRows, controlText, limitText } from './validationbodies.js';
import { loadVariability, variableStarsSection } from './variability.js';
import { resultsLead, briefRows, choiceSentence, partialTile } from './validationlead.js';
import { findingsList } from './variabilitytext.js';
import { openLinkedSection } from './openhash.js';

const main = $('#main');
const DATA_URL = new URL('data/validation.json', document.baseURI);
const BODIES_URL = new URL('data/body-recovery.json', document.baseURI);
const PAGE = 'How closely do the measurements match?';

const num = (text, extra = '') => el('td', { class: `num ${extra}`.trim(), text });

function th(label, title) {
  return el('th', { scope: 'col', title: title || null, text: label });
}

/**
 * A grouped table. `rowFor(t)` returns the row; `whyFor(t)` an optional sentence that is set
 * under that row across the table's full width (a failure's or a refusal's reason).
 */
function table(caption, heads, targets, rowFor, whyFor = () => null) {
  const body = [];
  for (const g of groupRows(targets)) {
    body.push(el('tr', { class: 'group-row' }, [el('th', { scope: 'colgroup', colspan: String(heads.length), text: g.label })]));
    for (const t of g.rows) {
      const why = whyFor(t);
      body.push(el('tr', { class: why ? 'has-why' : null }, rowFor(t)));
      if (why) body.push(el('tr', { class: 'why-row' }, [el('td', { colspan: String(heads.length) }, [el('div', { class: 'why', text: why })])]));
    }
  }
  return el('div', { class: 'val-scroll', tabindex: '0', role: 'region', 'aria-label': caption }, [
    el('table', { class: 'val-table' }, [
      el('caption', { class: 'sr-only', text: caption }),
      el('thead', {}, [el('tr', {}, heads)]),
      el('tbody', {}, body),
    ]),
  ]);
}

const isNotDetected = (v, reason) => v === 'not_applicable' && /not detected/i.test(reason || '');

/** A result cell: the verdict chip, and a chip with `provisional` (its label) when given. */
function resultCell(v, reason, provisional = null, text = null) {
  const label = isNotDetected(v, reason) ? 'Not detected' : text || verdictLabel(v);
  return el('td', { class: 'verdict-cell' }, [
    el('span', { class: `vtag v-${v}`, title: v === 'not_applicable' ? reason || null : null, text: label }),
    provisional ? el('span', { class: 'vtag v-provisional', text: provisional }) : null,
  ]);
}

/**
 * The sentence under a row: the report's reason for a failure or a refusal, and its caution for
 * a provisional type. A check that could not be made stays on one line (its reason is in the
 * notes at the foot of the page).
 */
function whyText(check, unexplained = null) {
  if (check.verdict === 'fail') return (check.reason || check.note) || unexplained;
  if (check.verdict === 'refused') return check.reason || null;
  if (check.verdict === 'not_applicable' && check.reason && !isNotDetected(check.verdict, check.reason) && /motion fit/i.test(check.reason)) return check.reason;
  return check.provisional || null;
}

function nameCell(t) {
  return el('th', { scope: 'row', class: 'name' }, [el('a', { href: viewHref(t.slug), text: t.name })]);
}

/** The scoreboard: passes with their failures beside them, then refusals, misses and partial builds. */
function summaryCard(report) {
  const s = report.summary;
  const missed = notDetected(report.targets).length;
  const unchecked = s.motion?.not_applicable ?? 0;
  const why = [missed ? `${missed} not detected in any image` : null, unchecked > missed ? `${unchecked - missed} for the reason given in its row` : null].filter(Boolean).join(', ');
  const cells = [
    ...scoreTiles(s).map((c) => ({ value: c.value, of: c.of, label: `${c.label}: ${c.sub}`, fail: c.fail, calm: c.calm })),
    ...(unchecked ? [{ value: String(unchecked), of: '', label: `No motion check: ${why}`, fail: null }] : []),
    { ...partialTile(s), fail: null },
  ];
  const prov = s.type?.provisional;
  return el('section', { class: 'card val-summary', 'aria-labelledby': 'sum-h' }, [
    el('h2', { id: 'sum-h', text: 'Scoreboard' }),
    el('div', { class: 'sum-row' }, cells.map((c) => el('div', { class: 'sum-cell' }, [
      el('strong', { class: 'sum-value' }, [c.value, c.of ? el('small', { text: ` ${c.of}` }) : null]),
      el('span', { class: 'small muted', text: c.label }),
      c.fail ? el('span', { class: 'sum-extra' }, [el('span', { class: 'fail', text: c.fail })]) : null,
      c.calm ? el('span', { class: 'sum-extra', text: c.calm }) : null,
    ]))),
    weakTestNote(report.targets) ? el('p', { class: 'small weak-note', text: weakTestNote(report.targets) }) : null,
    el('p', { class: 'small muted', text: `${s.targets} targets. Pass rates cover only the comparisons we could make. The table lists missing detections and unclassified spectra separately.${prov ? ` ${prov} of the types that pass ${prov === 1 ? 'is' : 'are'} marked provisional: a neighbouring source may add some of the light.` : ''}${faintTypesText(s.type) ? ` ${faintTypesText(s.type)}` : ''}` }),
  ]);
}

function methodSection(report) {
  const th_ = report.thresholds || {};
  const rule = (k, label) => el('li', {}, [el('strong', { text: `${label}. ` }), th_[k] || '']);
  const built = builtText(report.built);
  return el('section', { class: 'card', 'aria-labelledby': 'method-h' }, [
    el('h2', { id: 'method-h', text: 'How the checks work' }),
    el('p', { text: 'We measured the gallery objects using the same method as a live search. We set the motion and type criteria below before comparing the measurements with Gaia and the published literature. The limit for light from a neighbouring source was chosen afterwards, once we could see which targets it affected.' }),
    el('ul', { class: 'rules' }, [
      rule('motion', 'Motion'), ...(th_.weak_test ? [rule('weak_test', 'Weak test')] : []), rule('all_frames', 'Motion from all images'), rule('type', 'Type'), rule('refused', 'Unclassified'), rule('provisional', 'Provisional'), rule('not_applicable', 'Not applicable'),
    ]),
    el('p', { text: 'The motion test divides the difference by our own stated error only; the catalogue’s error is left out. For motions fitted to single detections, several fits have a reduced χ² well under 1, which suggests those stated errors are larger than the scatter of the positions, so a 3 σ pass there is a lenient test. That reading does not hold for a motion fitted on all images at once: there the reduced χ² was 0.6 and 0.5 while the first stated errors were too small, as sources planted in the real images showed. A failure can be a few mas/yr; the table gives the plain difference in mas/yr so you can judge it yourself.' }),
    el('p', { class: 'small muted', text: built ? `Last built ${built}. Rebuild with python -m pxs.validation.` : 'Build time unknown.' }),
  ]);
}

/** What we chose after seeing results: the three choices above, and the variable stars' own. */
function choicesSection(variables) {
  const varChoice = variables ? findingsList(variables).find(([k]) => /after seeing results/i.test(k)) : null;
  return el('section', { class: 'card', id: 'choices', 'aria-labelledby': 'choices-h' }, [
    el('h2', { id: 'choices-h', text: 'What we chose after seeing results' }),
    el('p', { text: 'Three choices were made after seeing results, and each changes what the table shows. First, the errors of a motion fitted on all images at once are multiplied by 1.7. That factor was set after CWISE J0623+0715 had failed at 3.9 σ without it; sources planted in the real images give factors from 1.4 to 2.0, and that object passes at any factor above 1.3. Second, a neighbouring source is fitted together with the target, except in images where a star was first removed. That exception was made after fitting the neighbour there too made CWISE J2112-0529 fail at 3.8 σ; its pass rests on 5 images. Third, Epsilon Indi B is scored against Gaia DR3 and fails. Its note also compares the measurement with Chen et al. 2022, who model the pair’s orbit; that second reference was added after the failure, and the agreement with it is expected only if the two brown dwarfs share the light at 4.6 µm roughly as they share the mass, which has not been measured. The variable stars have their own list of such choices, in the Variable stars section below.' }),
    el('p', { text: 'The limit for light from a neighbouring source was also chosen afterwards, once we could see which targets it affected (see How the checks work).' }),
    varChoice ? el('p', {}, [el('strong', { text: 'Variable stars. ' }), varChoice[1]]) : null,
  ]);
}

/** The five targets the brief names, one row each: motion, type and (variable stars) brightness. */
function briefSection(report, variables) {
  const chip = (verdict, text) => el('span', { class: `vtag v-${verdict === 'pass' ? 'pass' : verdict === 'fail' ? 'fail' : 'not_applicable'}`, text });
  const rows = briefRows(report, variables).map((r) => el('tr', {}, [
    el('th', { scope: 'row', class: 'name' }, [el('a', { href: viewHref(r.slug), text: r.name })]),
    el('td', { 'data-label': 'Motion, ours / catalogue' }, [el('span', { class: 'num', text: r.motion.text }), ' ', chip(r.motion.verdict, r.motion.word)]),
    el('td', { 'data-label': 'Type, ours against published' }, [r.type.text, ' ', r.type.verdict === 'pass' ? chip('pass', 'agrees') : null]),
    el('td', { class: r.brightness ? 'brief-change' : 'brief-change none', 'data-label': 'Brightness change we measured', text: r.brightness || '—' }),
  ]));
  return el('section', { class: 'card val-brief', id: 'brief', 'aria-labelledby': 'brief-h' }, [
    el('h2', { id: 'brief-h', text: 'The five targets the challenge named' }),
    el('div', { class: 'val-scroll', tabindex: '0', role: 'region', 'aria-label': 'The five targets the challenge named' }, [
      el('table', { class: 'val-table brief-table' }, [
        el('caption', { class: 'sr-only', text: 'The five targets the challenge named: motion, type and brightness change' }),
        el('thead', {}, [el('tr', {}, [th('Target'), th('Motion, ours / catalogue'), th('Type, ours against published'), th('Brightness change we measured')])]),
        el('tbody', {}, rows),
      ]),
    ]),
    el('p', { class: 'small muted', text: `${choiceSentence(report.targets)} Each name opens its view.` }),
  ]);
}

/** A section behind a closed <details>, keeping its id and content; the title becomes the summary. */
function closed(sec, title) {
  const h = sec.querySelector(':scope > h2');
  const id = h?.id;
  h?.remove();
  return el('details', { class: 'card val-more', id: sec.id || null }, [
    el('summary', {}, [el('h2', { id, text: title })]), ...sec.childNodes,
  ]);
}

function motionTable(report) {
  const heads = [th('Target'), th('Catalogue (mas/yr)', 'pmRA, pmDec'), th('Measured (mas/yr)', 'pmRA, pmDec'),
    th('Difference (mas/yr)', 'measured minus catalogue: pmRA, pmDec'), th('Total (″/yr)', 'measured, then catalogue'),
    th('Stated error (mas/yr)'), th('Worst, in σ'), th('Baseline, detections'), th('Result')];
  return table('Measured motion against the catalogue', heads, report.targets, (t) => {
    const m = t.motion;
    const x = motionText(m);
    const bad = m.verdict === 'fail' ? 'bad' : '';
    return [
      nameCell(t), num(x.catalogue), num(x.measured), num(x.diff, bad), num(x.total),
      num(x.error), num(x.sigma, bad), num(x.baseline === '—' ? '—' : `${x.baseline}, ${x.detections}`),
      resultCell(m.verdict, m.reason, null, motionLabel(m)),
    ];
  }, (t) => whyText(t.motion, 'The cause of this difference is not yet established.'));
}

function typeTable(report) {
  const heads = [th('Target'), th('Published type'), th('Our best fit'), th('Our range'), th('Result')];
  return table('Spectral type against the published type', heads, report.targets, (t) => [
    nameCell(t),
    el('td', { text: t.known_type || '—' }),
    el('td', { text: t.type.best ? `${t.type.best}${t.type.pair ? ` (blend of ${t.type.pair.join(' + ')})` : ''}` : '—' }),
    el('td', { text: rangeText(t.type) }),
    resultCell(t.type.verdict, t.type.reason, provisionalLabel(t.type)),
  ], (t) => whyText(t.type));
}

function dataTable(report) {
  const heads = [th('Target'), th('WISE'), th('WISE years'), th('SPHEREx'), th('Largest centroid residual'),
    th('Not detected'), th('Build')];
  return table('Frames, residuals and build state', heads, report.targets, (t) => [
    nameCell(t),
    el('td', { class: 'num', text: framesText(t.frames.wise) }),
    el('td', { class: 'num', text: yearSpan(t.frames.wise) }),
    el('td', { class: 'num', text: framesText(t.frames.spherex) }),
    el('td', { text: residualText(t.residual) }),
    num(`${t.residual.undetected} of ${t.residual.frames}`),
    el('td', {}, [el('span', { class: `vtag ${t.degraded.flag ? 'v-refused' : 'v-pass'}`, text: t.degraded.flag ? 'Partial' : 'Complete' })]),
  ]);
}

function notesFor(t) {
  const items = [];
  if (t.motion.verdict === 'fail') items.push(['Motion failed', t.motion.note || t.motion.reason || 'The cause of this difference is not yet established.']);
  else if (t.motion.note) items.push(['Motion', t.motion.note]);
  if (t.motion.second_reference?.text) items.push(['Second reference', t.motion.second_reference.text]);
  if (t.motion.verdict === 'not_applicable' && t.motion.reason) items.push(['No motion check', t.motion.reason]);
  if (['refused', 'not_applicable', 'fail'].includes(t.type.verdict) && t.type.reason) {
    items.push([{ refused: 'Unclassified', fail: 'Type failed' }[t.type.verdict] || 'No type check', t.type.reason]);
  }
  if (t.type.provisional) items.push(['Provisional type', t.type.provisional]);
  for (const g of t.frames.gaps || []) items.push(['Missing WISE coverage', g]);
  const r = t.residual;
  if (r.max_px != null && (r.frame_warnings || []).length) items.push(['Largest residual frame', `${r.frame_id}: ${r.frame_warnings.join('; ')}.`]);
  for (const d of t.degraded.reasons || []) if (!(t.frames.gaps || []).includes(d)) items.push(['Partial build', d]);
  return items;
}

function notesSection(report) {
  const blocks = report.targets.map((t) => {
    const items = notesFor(t);
    return el('div', { class: 'val-notes' }, [
      el('h3', {}, [el('a', { href: viewHref(t.slug), text: t.name })]),
      items.length ? el('ul', {}, items.map(([k, v]) => el('li', {}, [el('strong', { text: `${k}. ` }), v]))) : el('p', { class: 'small muted', text: 'Nothing to add.' }),
    ]);
  });
  return el('section', { class: 'card', 'aria-labelledby': 'notes-h' }, [
    el('h2', { id: 'notes-h', text: 'Where the measurements disagree or fall short' }),
    ...blocks,
  ]);
}

function section(id, title, intro, content) {
  return el('section', { class: 'card', 'aria-labelledby': id }, [
    el('h2', { id, text: title }), el('p', { class: 'small muted', text: intro }), content,
  ]);
}

/** A bar from 0 to 1: the recovered fraction, with its 95% interval as a line. */
function intervalBar(r) {
  const p = (x) => `${(x * 100).toFixed(1)}%`;
  return el('span', { class: 'rec-bar', 'aria-hidden': 'true' }, [
    el('span', { class: 'rec-fill', style: `width:${p(r.frac)}` }),
    r.lo != null && r.hi != null ? el('span', { class: 'rec-ci', style: `left:${p(r.lo)};width:${p(r.hi - r.lo)}` }) : null,
  ]);
}

function bodiesSection(d) {
  const rows = recoveryRows(d);
  const ci = (r) => (r.lo != null ? `${Math.round(r.lo * 100)}–${Math.round(r.hi * 100)}%` : '—');
  const heads = [th('Predicted V'), th('Passes'), th('Recovered', 'current rule: S/N 5 in two bands'), th('Fraction'),
    th('95% interval'), th('Before', 'recovered under the old rule, S/N 5 in one band')];
  const body = rows.map((r) => el('tr', {}, [
    el('th', { scope: 'row', class: 'name', text: r.bin.replace('-', '–') }),
    num(String(r.n)), num(String(r.k)),
    el('td', { class: 'rec-cell' }, [intervalBar(r), el('span', { class: 'num', text: ` ${Math.round(r.frac * 100)}%` })]),
    num(ci(r)), num(r.before == null ? '—' : String(r.before)),
  ]));
  const nb = d.bodies ? ` ${d.bodies.recovered} of ${d.bodies.n} bodies were recovered in at least one pass.` : '';
  const fd = d.false_detections.passes;
  const tiles = [
    d.bodies ? ['Bodies recovered', `${d.bodies.recovered}`, `of ${d.bodies.n}`, 'in at least one pass'] : null,
    d.passes?.n ? ['Passes recovered', `${d.passes.k}`, `of ${d.passes.n}`, 'detected, within 12″ of the predicted position'] : null,
    fd?.n ? ['False detections', `${fd.k}`, `of ${fd.n}`, 'on empty control tracks, current rule'] : null,
  ].filter(Boolean);
  return el('section', { class: 'card', id: 'bodies', 'aria-labelledby': 'bodies-h' }, [
    el('h2', { id: 'bodies-h', text: 'Known bodies recovered' }),
    el('p', { class: 'small muted', text: `The Solar System body mode run on ${d.bodies?.n ?? 'a sample of'} known asteroids, Trojans, Centaurs and trans-Neptunian objects drawn by fixed rules from JPL's Small-Body Database, every SPHEREx pass analysed as the site does. A pass is recovered when it is detected and the body-centred image puts it within 12 arcsec of the JPL Horizons position.${nb}` }),
    el('div', { class: 'sum-row' }, tiles.map(([label, value, of, sub]) => el('div', { class: 'sum-cell' }, [
      el('strong', { class: 'sum-value' }, [value, el('small', { text: ` ${of}` })]),
      el('span', { class: 'small muted', text: `${label}: ${sub}` }),
    ]))),
    el('p', { class: 'rec-limit', text: limitText(d) }),
    el('p', { class: 'small', text: `${controlText(d)}${d.passes?.n ? ` At that rate about ${Math.round(d.false_detections.passes.k / d.false_detections.passes.n * d.passes.n)} of the ${d.passes.n} real passes are expected to be false, so a lone recovery far below the limit is not evidence of a deeper one.` : ''}` }),
    el('div', { class: 'val-scroll', tabindex: '0', role: 'region', 'aria-label': 'Recovery by predicted V magnitude' }, [
      el('table', { class: 'val-table rec-table' }, [
        el('caption', { class: 'sr-only', text: 'Recovery of known bodies by predicted V magnitude' }),
        el('thead', {}, [el('tr', {}, heads)]),
        el('tbody', {}, body),
      ]),
    ]),
    el('p', { class: 'small muted', text: 'Predicted V is from JPL Horizons. Passes of one body are not independent, so the intervals are somewhat too narrow.' }),
  ]);
}

async function loadBodies() {
  try {
    const res = await fetch(BODIES_URL, { headers: { Accept: 'application/json' } });
    if (!res.ok) return null;
    const d = await res.json();
    return bodyRecoveryProblem(d) ? null : d;
  } catch {
    return null;
  }
}

function render(report, bodies, variables) {
  document.title = pageTitle(PAGE);
  const n = report.targets.length;
  const bodiesSec = bodies ? bodiesSection(bodies) : el('section', { class: 'card', id: 'bodies', 'aria-labelledby': 'bodies-h' }, [
    el('h2', { id: 'bodies-h', text: 'Known bodies recovered' }),
    el('p', { class: 'small muted', text: 'The known-body recovery results (data/body-recovery.json) could not be loaded.' }),
  ]);
  main.replaceChildren(el('div', { class: 'val' }, [
    el('h1', { text: 'How closely do the measurements match?' }),
    el('p', { class: 'answer', id: 'val-answer', text: resultsLead(report.summary).join(' ') }),
    el('p', { class: 'val-next small' }, ['See any target for yourself in ', el('a', { href: 'index.html', text: 'the blink' }),
      ', or read ', el('a', { href: 'planetx.html', text: 'whether SPHEREx could see Planet X' }), ' and about ', el('a', { href: 'search.html', text: 'our blind search' }), '.']),
    summaryCard(report),
    briefSection(report, variables),
    closed(choicesSection(variables), 'What we chose after seeing results'),
    closed(section('motion-h', 'Motion against the catalogue', 'Measured from the WISE and SPHEREx positions. The catalogue column is Gaia DR3 or the Kirkpatrick et al. 2021 parallax programme, as listed for each target in data/targets.json.', motionTable(report)), `All ${n} motions`),
    closed(section('type-h', 'Spectral type', 'From the SPHEREx spectrum, against the type in the literature.', typeTable(report)), `All ${n} spectral types`),
    closed(notesSection(report), 'Where the measurements disagree or fall short'),
    closed(methodSection(report), 'How the checks work'),
    closed(section('data-h', 'Coverage and tracking', 'Residuals are in arcseconds on the display grid (1 pixel is 1″) and also in the native pixels of that frame’s instrument. There is no pass mark; larger values are listed as they are.', dataTable(report)), 'Coverage and tracking'),
    closed(bodiesSec, 'Solar System bodies'),
    closed(variableStarsSection(variables), 'Variable stars'),
  ]));
  openLinkedSection();
}

function showError(message) {
  main.replaceChildren(el('section', { class: 'status card error', role: 'alert' }, [
    el('h1', { text: 'The validation data could not be shown' }),
    el('p', { text: message }),
    el('p', {}, [el('a', { class: 'btn primary', href: './', text: 'Back to the gallery' })]),
  ]));
}

async function load() {
  let res;
  try {
    res = await fetch(DATA_URL, { headers: { Accept: 'application/json' } });
  } catch {
    return showError('The server could not be reached. Check your connection and try again.');
  }
  if (!res.ok) return showError(`The server answered with an error (HTTP ${res.status}).`);
  let body;
  try {
    body = await res.json();
  } catch {
    return showError('The server sent data that is not valid JSON.');
  }
  const problem = reportProblem(body);
  if (problem) return showError(problem);
  const bodies = await loadBodies();
  const variables = await loadVariability();
  try {
    render(body, bodies, variables);
  } catch {
    showError('The validation data has an unexpected shape and could not be drawn.');
  }
}

mountChrome('validation');
document.title = pageTitle(PAGE);
load();
