// User-facing names for frame sets. Raw band ids ("spx-b6", "W2") never reach the page
// on their own; everything is labelled from `mission` and `wavelength_um`. Pure.

// Nominal WISE band centres; a passband midpoint would mislabel W1 (2.8-3.8 gives 3.3).
const WISE_NOMINAL = { W1: 3.4, W2: 4.6, W3: 12, W4: 22 };

/** A wavelength in µm: "0.75", "1.1", "5.0". Hundredths only when they carry information. */
export function formatUm(x) {
  if (!Number.isFinite(x)) return '?';
  const r = Math.round(x * 100) / 100;
  return Math.abs(r * 10 - Math.round(r * 10)) < 1e-6 ? r.toFixed(1) : r.toFixed(2);
}

/** "4.4–5.0 µm" from a [lo, hi] window, or null. */
export function windowLabel(wl) {
  return Array.isArray(wl) && wl.length === 2 ? `${formatUm(wl[0])}–${formatUm(wl[1])} µm` : null;
}

/**
 * Full label for a frame or frame set: "SPHEREx 4.4–5.0 µm", "WISE W2 (4.6 µm)".
 * @param {{mission: string, band: string, wavelength_um?: number[]|null, wl?: number|null}} s
 */
export function setLabel(s) {
  const wl = s.wavelength_um ?? s.window ?? null;
  if (s.mission === 'WISE') {
    const nominal = WISE_NOMINAL[s.band] ?? (wl ? (wl[0] + wl[1]) / 2 : null);
    if (/^W\d$/.test(s.band)) return nominal != null ? `WISE ${s.band} (${formatUm(nominal)} µm)` : `WISE ${s.band}`;
    return nominal != null ? `WISE ${formatUm(nominal)} µm` : 'WISE';
  }
  const win = windowLabel(wl);
  if (win) return `${s.mission} ${win}`;
  return `${s.mission} ${s.band}`;
}

/**
 * Replace SPHEREx frame-set ids inside pipeline text ("disagrees with spx-b6") by their labels.
 * @param {string} text
 * @param {object[]} frames  frames whose `band` ids may appear in the text
 */
export function nameBands(text, frames) {
  const named = new Map(frames.filter((f) => f.mission === 'SPHEREx').map((f) => [f.band, setLabel(f)]));
  return named.size ? text.replace(/\bspx-[\w-]+\b/g, (id) => named.get(id) ?? id) : text;
}

/** Shorter label for tight spaces (the band strip): "4.4–5.0 µm", "W2". */
export function shortLabel(s) {
  if (s.mission === 'WISE' && /^W\d$/.test(s.band)) return s.band;
  return windowLabel(s.wavelength_um ?? s.window ?? null) || s.band;
}
