// The sky map's first screen. Where the whole sky leaves the orange rings big enough to tap
// apart, open on it; on a narrow screen open on the region that holds the most of our built views
// and say how many more there are. Pure functions.

import { makeView, project, toVec, maxFov } from './exploreproj.js';

const MIN_PX_PER_RAD = 110; // below this the whole-sky rings crowd into each other
const PHONE_FOVS = [150, 130, 115]; // widest first: prefer showing more sky

/** True when the whole sky, fitted to this canvas, keeps the rings tappable. */
export function wholeSkyFits(width, height) {
  return width / ((maxFov(width, height) * Math.PI) / 180) >= MIN_PX_PER_RAD;
}

function countShown(view, points, inset) {
  let n = 0;
  for (const t of points) {
    const p = project(view, toVec(t.ra, t.dec));
    if (p.x >= inset.side && p.x <= view.width - inset.side && p.y >= inset.top && p.y <= view.height - inset.bottom) n += 1;
  }
  return n;
}

/**
 * The opening centre and field.
 * @param {Array<{ra: number, dec: number}>} points our built views
 * @param {{top: number, bottom: number, side: number}} inset screen edges covered by controls
 * @returns {{ra: number, dec: number, fov: number, shown: number, whole: boolean}}
 */
export function openingView(points, width, height, inset, home = { ra: 90, dec: 5 }) {
  if (wholeSkyFits(width, height)) {
    const fov = maxFov(width, height);
    return { ...home, fov, shown: countShown(makeView({ ...home, fov, width, height }), points, inset), whole: true };
  }
  let best = null;
  for (const fov of PHONE_FOVS) {
    // Candidate centres: every view, and every RA hour on a few declinations.
    const centres = [...points.map((p) => ({ ra: p.ra, dec: p.dec }))];
    for (let ra = 0; ra < 360; ra += 15) for (const dec of [-30, 0, 30]) centres.push({ ra, dec });
    for (const c of centres) {
      const shown = countShown(makeView({ ...c, fov, width, height }), points, inset);
      if (!best || shown > best.shown) best = { ra: c.ra, dec: c.dec, fov, shown, whole: false };
    }
  }
  return best;
}

/** One line for the status bar on arrival. */
export function openingWords(shown, total) {
  if (shown >= total) return `All ${total} of our built views are on the map: tap an orange ring to watch it move.`;
  const rest = total - shown;
  return `${shown} of our ${total} built views are on screen: tap an orange ring to watch it move, `
    + `or drag (or press Reset view) for the other ${rest === 1 ? 'one' : rest}.`;
}
