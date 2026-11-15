// The two numbers Backyard Worlds vetters use: W1-W2 colour and reduced proper motion
// H_W2. Both come from the pipeline (manifest `vetting`); nothing is recomputed here. Pure.

const fin = Number.isFinite;

/**
 * Rows to show, each with a one-line explanation. [] when there is nothing to show.
 * @param {{w1_mag?: number|null, w2_mag?: number|null, w1_w2?: number|null,
 *          reduced_pm_w2?: number|null, catalogue?: string|null}|null} v
 * @returns {{key: string, label: string, value: string, help: string}[]}
 */
export function vettingRows(v) {
  if (!v) return [];
  const rows = [];
  const from = v.catalogue ? `, from ${v.catalogue}` : '';
  if (fin(v.w1_w2)) {
    rows.push({ key: 'w1w2', label: 'W1−W2 colour', value: `${v.w1_w2.toFixed(2)} mag${from}`,
      help: 'Most stars sit near 0. T dwarfs are usually above about 1 and Y dwarfs redder still, because methane removes light from W1. A large value suggests a cold brown dwarf.' });
  }
  if (fin(v.reduced_pm_w2)) {
    rows.push({ key: 'hw2', label: 'Reduced proper motion H_W2', value: `${v.reduced_pm_w2.toFixed(1)} mag`,
      help: 'W2 brightness corrected for speed of motion. A large value means the object is faint for how fast it moves, so it is probably nearby and intrinsically dim: a brown dwarf, but also possibly a white dwarf or a subdwarf.' });
  }
  if (rows.length && (fin(v.w1_mag) || fin(v.w2_mag))) {
    const mags = [fin(v.w1_mag) && `W1 ${v.w1_mag.toFixed(2)}`, fin(v.w2_mag) && `W2 ${v.w2_mag.toFixed(2)}`].filter(Boolean).join(', ');
    rows.push({ key: 'mags', label: 'Catalogue magnitudes', value: `${mags}${from}`, help: '' });
  }
  return rows;
}

/** Lines for the forum summary; [] when absent. */
export function vettingLines(v) {
  return vettingRows(v).map((r) => `${r.label}: ${r.value}`);
}
