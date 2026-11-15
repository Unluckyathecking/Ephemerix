// Frame sets (one per `band` id), blink presets, and SPHEREx pass grouping. Pure.

import { decimalYear } from './sky.js';

const MISSION_ORDER = { WISE: 0, SPHEREx: 1 };
const mid = (wl) => (wl ? (wl[0] + wl[1]) / 2 : null);
const KEY_UM = 4.6; // where WISE W2 and the reddest SPHEREx band overlap

/** One entry per band id, WISE first, then by wavelength. */
export function bandSets(frames) {
  const map = new Map();
  for (const f of frames) {
    const s = map.get(f.band) || { band: f.band, mission: f.mission, window: f.wavelength_um, wl: mid(f.wavelength_um), count: 0, detections: 0 };
    s.count += 1;
    if (f.centroid_px) s.detections += 1;
    map.set(f.band, s);
  }
  return [...map.values()].sort((a, b) =>
    (MISSION_ORDER[a.mission] ?? 9) - (MISSION_ORDER[b.mission] ?? 9) || (a.wl ?? 0) - (b.wl ?? 0) || a.band.localeCompare(b.band));
}

/** The set of `mission` whose window contains `um`, else the one with the nearest midpoint. */
function nearestSet(sets, mission, um) {
  const own = sets.filter((s) => s.mission === mission);
  return own.find((s) => s.window && s.window[0] <= um && um <= s.window[1])
    || own.reduce((best, s) => (!best || Math.abs((s.wl ?? 0) - um) < Math.abs((best.wl ?? 0) - um) ? s : best), null);
}

export const PRESETS = [
  { id: 'wise-spherex', label: 'WISE + SPHEREx at 4.6 µm', help: 'Both missions at about the same wavelength: 16 years of motion.' },
  { id: 'spherex', label: 'SPHEREx only', help: 'Only SPHEREx, at one wavelength, 2025 onward.' },
  { id: 'spherex-all', label: 'All SPHEREx bands', help: 'Every SPHEREx band in date order. The brightness jumps between wavelengths as well as dates.' },
  { id: 'all', label: 'Everything', help: 'Every image set in date order.' },
];

/** Band ids for a preset ([] when the preset has nothing to show here). */
export function presetBands(frames, id) {
  const sets = bandSets(frames);
  const w = sets.find((s) => s.mission === 'WISE' && s.band === 'W2') || nearestSet(sets, 'WISE', KEY_UM);
  const spx = nearestSet(sets, 'SPHEREx', KEY_UM);
  if (id === 'wise-spherex') return w && spx ? [w.band, spx.band] : [];
  if (id === 'spherex') return spx ? [spx.band] : [];
  if (id === 'spherex-all') return sets.filter((s) => s.mission === 'SPHEREx').map((s) => s.band);
  if (id === 'all') return sets.map((s) => s.band);
  return [];
}

/** Default blink: WISE + SPHEREx at 4.6 µm when both exist, else one band of what there is. */
export function defaultBands(frames) {
  for (const id of ['wise-spherex', 'spherex']) {
    const b = presetBands(frames, id);
    if (b.length) return b;
  }
  const sets = bandSets(frames);
  const w = sets.find((s) => s.band === 'W2') || sets[0];
  return w ? [w.band] : [];
}

/** The preset whose bands equal `bands` (order ignored), or null. */
export function matchPreset(frames, bands) {
  const key = [...bands].sort().join(',');
  return PRESETS.find((p) => {
    const b = presetBands(frames, p.id);
    return b.length && [...b].sort().join(',') === key;
  })?.id ?? null;
}

/** Bands from the URL: explicit `bands` win, then `preset`, then the default. */
export function resolveBands(requested, frames, preset = null) {
  const known = new Set(frames.map((f) => f.band));
  const ok = (requested || []).filter((b) => known.has(b));
  if (ok.length) return ok;
  const p = preset ? presetBands(frames, preset) : [];
  return p.length ? p : defaultBands(frames);
}

export function activeFrames(frames, bands) {
  const set = new Set(bands);
  return frames.filter((f) => set.has(f.band));
}

/** Decimal year halfway between the last WISE frame and the first SPHEREx frame, or null. */
export function handoverYear(frames) {
  const wise = frames.filter((f) => f.mission === 'WISE').map((f) => f.mjd);
  const spx = frames.filter((f) => f.mission === 'SPHEREx').map((f) => f.mjd);
  if (!wise.length || !spx.length) return null;
  return decimalYear((Math.max(...wise) + Math.min(...spx)) / 2);
}

/** Index of the frame in `list` closest in time to `mjd`. */
export function nearestIndex(list, mjd) {
  let best = 0;
  for (let i = 1; i < list.length; i += 1) {
    if (Math.abs(list[i].mjd - mjd) < Math.abs(list[best].mjd - mjd)) best = i;
  }
  return best;
}

/**
 * The SPHEREx pass nearest to `mjd`: for every SPHEREx band, the frame closest in time to
 * the anchor frame, if within `tolDays`. Frames of one pass differ by days, passes by months.
 * @returns {{set: object, frame: object|null}[]} ordered by wavelength; [] without SPHEREx
 */
export function passFrames(frames, mjd, tolDays = 30) {
  const spx = frames.filter((f) => f.mission === 'SPHEREx');
  if (!spx.length) return [];
  const anchor = spx[nearestIndex(spx, mjd)];
  return bandSets(spx).map((set) => {
    const own = spx.filter((f) => f.band === set.band);
    const f = own[nearestIndex(own, anchor.mjd)];
    return { set, frame: Math.abs(f.mjd - anchor.mjd) <= tolDays ? f : null };
  });
}
