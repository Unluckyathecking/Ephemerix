// Position search form. Validates input and either navigates to a live view
// or explains that only gallery targets are available.

import { el } from './dom.js';
import { parsePosition, parseOptionalNumber, CoordError, formatRa, formatDec } from './coords.js';
import { serializeState, emptyState, cleanLabel } from './urlstate.js';
import { looksLikeName, resolveName, resolveBody } from './resolve.js';
import { attachSuggest } from './suggest.js';

const FOVS = [120, 240, 480];
// How long a lookup takes, said next to the button so the wait is no surprise.
const WAIT = {
  sky: 'For a quick look, choose a gallery object. Gathering images for a new position usually takes a minute or two.',
  body: 'A body someone has looked up today opens at once; a new one can take several minutes.',
};
const MODES = {
  sky: { label: 'Object name or sky coordinates', button: 'Find it', placeholder: '08 55 10.83 -07 14 42.5',
    hint: 'A star or brown dwarf by name (Barnard, eps Ind, Gl 699, WISE 0855), or a position in degrees or hours (08 55 10.83 -07 14 42.5).' },
  body: { label: 'Solar System body', button: 'Follow this body', placeholder: 'Eris',
    hint: 'A name or designation such as "Eris", "Quaoar", "433 Eros", "2060" or "3I/ATLAS". The view follows the body through every SPHEREx exposure that caught it.' },
};

/** Go to the live body view for a resolved designation. */
function openBody(designation) {
  window.location.search = serializeState({ ...emptyState(), body: designation });
}

/** A row of buttons, one per suggested body; pressing one calls pick(designation). */
function suggestionButtons(suggestions, pick) {
  return el('span', { class: 'row' }, suggestions.map((s) => el('button', { type: 'button', class: 'btn', text: s.name, onClick: () => pick(s.designation) })));
}

function field(id, label, hint, attrs = {}) {
  const input = el('input', { id, name: id, type: 'text', autocomplete: 'off', spellcheck: 'false', 'aria-describedby': `${id}-hint`, ...attrs });
  return [input, el('div', { class: 'field' }, [
    el('label', { for: id, text: label }), input, el('p', { id: `${id}-hint`, class: 'small muted', text: hint }),
  ])];
}

/** A row of links to gallery views, for a first look without typing. */
function exampleChips(examples, lead) {
  if (!examples?.length) return null;
  return el('p', { class: 'examples' }, [lead, el('span', { class: 'small muted', text: lead ? 'or try' : 'Or try' }),
    ...examples.map((t) => el('a', { class: 'chip', href: `?target=${encodeURIComponent(t.slug)}`, text: t.name }))]);
}

/**
 * @param {{apiBase: string, prefill: object|null, gallery?: Promise<object[]|null>|object[]|null,
 *   examples?: {slug: string, name: string}[]}} opts  gallery: the built views (they open instantly)
 */
export function searchForm({ apiBase, prefill, gallery = null, examples = [], lead = null }) {
  const [pos, posField] = field('pos', MODES.sky.label, MODES.sky.hint, { inputmode: 'text', placeholder: MODES.sky.placeholder });
  const [pmra, pmraField] = field('pmra', 'pmRA (mas/yr)', 'Optional, includes cos(Dec).', { inputmode: 'decimal' });
  const [pmdec, pmdecField] = field('pmdec', 'pmDec (mas/yr)', 'Optional.', { inputmode: 'decimal' });
  const [epoch, epochField] = field('epoch', 'Epoch (year)', 'Optional, the year the position refers to.', { inputmode: 'decimal', placeholder: '2016.0' });
  const fov = el('select', { id: 'fov', name: 'fov' }, FOVS.map((f) => el('option', { value: String(f), text: `${f}″ (${f / 60}′)`, selected: f === 240 })));
  const msg = el('p', { class: 'form-msg', role: 'status', 'aria-live': 'polite' });
  if (prefill?.ra != null) {
    pos.value = `${prefill.ra} ${prefill.dec}`;
    if (prefill.pmra != null) pmra.value = String(prefill.pmra);
    if (prefill.pmdec != null) pmdec.value = String(prefill.pmdec);
    if (prefill.epoch != null) epoch.value = String(prefill.epoch);
    if (FOVS.includes(prefill.fov)) fov.value = String(prefill.fov);
  }

  const motionRow = el('div', { class: 'row-fields' }, [pmraField, pmdecField, epochField,
    el('div', { class: 'field' }, [el('label', { for: 'fov', text: 'Field of view' }), fov])]);
  // The optional fields stay folded away until someone needs them (or a lookup fills them in).
  // The body switch and the optional fields share one fold, so the first screen asks for nothing else.
  const more = el('details', { class: 'search-more', open: prefill?.pmra != null || prefill?.epoch != null || !!prefill?.body }, [
    el('summary', { text: 'More: a Solar System body, or proper motion and field of view' }),
  ]);
  const hint = posField.querySelector('p'); // shown under the input-and-button line, not inside it
  const submit = el('button', { type: 'submit', class: 'btn primary', text: MODES.sky.button });
  const wait = el('p', { class: 'small muted search-wait', text: WAIT.sky });
  let mode = 'sky';
  let found = null; // the last name looked up, so the view it opens can show that name
  const segs = {};
  const sg = attachSuggest({ input: pos, apiBase, gallery, active: () => mode === 'sky',
    onLiveOffline: () => { msg.textContent = 'Building a new view needs the live server, which this copy of the site does not have. The gallery views open here.'; } });
  const wrap = el('div', { class: 'suggest-wrap' });
  pos.replaceWith(wrap);
  wrap.append(pos, sg.node);
  const setMode = (m) => {
    mode = m;
    for (const [k, b] of Object.entries(segs)) b.setAttribute('aria-pressed', String(k === m));
    posField.querySelector('label').textContent = MODES[m].label;
    hint.textContent = MODES[m].hint;
    pos.placeholder = MODES[m].placeholder;
    submit.textContent = MODES[m].button;
    wait.textContent = WAIT[m];
    motionRow.hidden = m === 'body';
  };
  segs.sky = el('button', { type: 'button', class: 'seg', text: 'Star or position', 'aria-pressed': 'true', onClick: () => setMode('sky') });
  segs.body = el('button', { type: 'button', class: 'seg', text: 'Solar System body', 'aria-pressed': 'false', onClick: () => setMode('body') });
  // Most people want a star or a position, so the body switch sits in the fold, not before the box.
  const toggle = el('div', { class: 'search-kind' }, [el('p', { class: 'small muted', text: 'Looking for a dwarf planet, comet or asteroid instead?' }),
    el('div', { class: 'segmented', role: 'group', 'aria-label': 'What to look up' }, [segs.sky, segs.body])]);
  more.append(toggle, motionRow);

  const form = el('form', { class: 'search', novalidate: true }, [
    el('div', { class: 'search-line' }, [posField, submit]),
    sg.understood,
    hint,
    exampleChips(examples, lead),
    msg,
    more,
    wait,
  ]);
  if (prefill?.body) {
    setMode('body');
    pos.value = prefill.body;
  }

  async function lookUpBody(name) {
    if (!apiBase) { msg.textContent = 'Following a Solar System body needs the live server, which this copy of the site does not have.'; return; }
    msg.textContent = `Looking up “${name}” in the JPL Small-Body Database…`;
    const r = await resolveBody(name, { apiBase });
    if (r.ok) {
      msg.textContent = `Found ${r.name}. Opening…`;
      openBody(r.designation);
      return;
    }
    msg.replaceChildren(r.message);
    if (r.suggestions.length) {
      msg.append(' ', suggestionButtons(r.suggestions, (n) => { pos.value = n; lookUpBody(n); }));
    }
    // The two kinds are not a trap: a star name typed here can be tried as a star in one press.
    msg.append(' ', el('button', { type: 'button', class: 'btn', text: 'Look it up as a star or position instead',
      onClick: () => { setMode('sky'); form.requestSubmit(); } }));
    pos.focus();
  }

  /** After a failed star lookup: offer the body view when the name is a Solar System body. */
  async function offerBody(name, starMessage) {
    const b = apiBase ? await resolveBody(name, { apiBase }) : { ok: false };
    if (!b.ok) { msg.textContent = starMessage; pos.focus(); return; }
    // Tried as a body before giving up: a Solar System name typed in the star box just opens.
    msg.textContent = `“${name}” is a Solar System body, ${b.name}. Following it…`;
    openBody(b.designation);
  }

  async function lookUp(name) {
    msg.textContent = `Looking up “${name}”…`;
    const r = await resolveName(name, { apiBase });
    if (!r.ok) { await offerBody(name, r.message); return; }
    found = { label: cleanLabel(name), ra: +r.ra.toFixed(7), dec: +r.dec.toFixed(7) };
    pos.value = `${+r.ra.toFixed(7)} ${+r.dec.toFixed(7)}`;
    pmra.value = r.pmra != null ? String(r.pmra) : '';
    pmdec.value = r.pmdec != null ? String(r.pmdec) : '';
    epoch.value = r.epoch != null ? String(r.epoch) : '';
    more.open = r.pmra != null || r.epoch != null;
    const motion = r.pmra != null ? `, proper motion ${r.pmra}, ${r.pmdec} mas/yr at epoch ${r.epoch ?? '?'}` : '. No proper motion was found, so the view will use the fixed position';
    msg.textContent = `Found “${r.name}” via ${r.source}: RA ${formatRa(r.ra)}, Dec ${formatDec(r.dec)}${motion}. Check the values and press “Find it”.`;
  }

  form.addEventListener('submit', (e) => {
    e.preventDefault();
    for (const i of [pos, pmra, pmdec, epoch]) i.removeAttribute('aria-invalid');
    if (mode === 'body') {
      const name = pos.value.trim();
      if (!name) { msg.textContent = 'Type the name or designation of a Solar System body.'; pos.focus(); return; }
      lookUpBody(name);
      return;
    }
    const best = sg.best();
    if (best) { msg.textContent = `Opening ${best.name}…`; sg.go(best); return; }
    if (looksLikeName(pos.value)) { lookUp(pos.value.trim()); return; }
    let p, pm;
    try {
      p = parsePosition(pos.value);
    } catch (err) {
      pos.setAttribute('aria-invalid', 'true');
      msg.textContent = err instanceof CoordError ? err.message : 'That position could not be read.';
      pos.focus();
      return;
    }
    const fail = (inputs, text) => {
      more.open = true;
      inputs.forEach((i) => i.setAttribute('aria-invalid', 'true'));
      msg.textContent = text;
      inputs[0].focus();
    };
    pm = {};
    for (const [input, key, label] of [[pmra, 'pmra', 'pmRA'], [pmdec, 'pmdec', 'pmDec'], [epoch, 'epoch', 'Epoch']]) {
      try {
        pm[key] = parseOptionalNumber(input.value, label);
      } catch (err) {
        fail([input], err.message);
        return;
      }
    }
    if ((pm.pmra == null) !== (pm.pmdec == null)) return fail([pmra, pmdec], 'Give both pmRA and pmDec, or neither.');
    if (pm.epoch != null && (pm.epoch < 1900 || pm.epoch > 2100)) return fail([epoch], 'Epoch should be a year such as 2016.0.');
    const where = `RA ${formatRa(p.ra)}, Dec ${formatDec(p.dec)}`;
    if (!apiBase) {
      msg.textContent = `Read as ${where}. Live searches are not connected on this copy of the site, so only the gallery targets above can be opened.`;
      return;
    }
    const named = found && found.ra === +p.ra.toFixed(7) && found.dec === +p.dec.toFixed(7) ? found.label : null;
    const state = { ...emptyState(), ra: +p.ra.toFixed(7), dec: +p.dec.toFixed(7), ...pm, fov: Number(fov.value), label: named };
    msg.textContent = `Opening ${where}…`;
    window.location.search = serializeState(state);
  });
  return form;
}
