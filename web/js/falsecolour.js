// Methane false colour: which three SPHEREx band images of one pass go into red, green and blue.
// Pure; the drawing is in bandstrip.js.
//
// Red is 4.42-5.0 µm, where a cold brown dwarf is brightest. Green (1.65-2.42 µm) and blue
// (2.42-3.82 µm) both hold methane bands, at 2.2 and 3.3 µm, that take most of a T or Y dwarf's
// light there, so it comes out red while ordinary stars come out white or blue-green.

export const FC_CHANNELS = [
  { ch: 'R', um: 4.7, color: '#ff0000' },
  { ch: 'G', um: 2.0, color: '#00ff00' },
  { ch: 'B', um: 3.3, color: '#0000ff' },
];

/**
 * @param {{set: object, frame: object|null}[]} pass  from framesets.passFrames
 * @param {(frame: object) => boolean} hasImage  whether the frame's PNG loaded
 * @returns {{ok: boolean, channels: {ch: string, color: string, frame: object|null, set: object|null}[], reason: string}}
 */
export function falseColourPlan(pass, hasImage = () => true) {
  const channels = FC_CHANNELS.map(({ ch, um, color }) => {
    const hit = pass.find((p) => p.set.window && p.set.window[0] <= um && um < p.set.window[1]);
    return { ch, color, set: hit?.set ?? null, frame: hit?.frame ?? null };
  });
  const missing = channels.filter((c) => !c.set || !c.frame);
  if (missing.length) {
    const what = missing.map((c) => `${c.ch === 'R' ? '4.4–5.0' : c.ch === 'G' ? '1.65–2.4' : '2.4–3.8'} µm`).join(' and ');
    return { ok: false, channels, reason: `False colour needs this pass's ${what} image${missing.length > 1 ? 's' : ''}, which ${missing.length > 1 ? 'are' : 'is'} not in this view.` };
  }
  const broken = channels.filter((c) => !hasImage(c.frame));
  if (broken.length) return { ok: false, channels, reason: 'False colour is off: an image it needs did not load.' };
  return { ok: true, channels, reason: '' };
}

/** Caption naming the mapping, from the frames actually used. */
export function falseColourCaption(plan, label) {
  return `False colour, not true colour: red ${label(plan.channels[0].set)}, green ${label(plan.channels[1].set)}, blue ${label(plan.channels[2].set)}. `
    + 'A methane brown dwarf is faint in green and blue, so it shows red; ordinary stars, bright at the shorter wavelengths too, look white or blue-green. '
    + 'Each band keeps its own fixed display stretch, so hues are a guide, not flux ratios.';
}
