// Which gallery target the landing page leads with, and why a card has no tool type. Pure.
// The rule reads the manifests, never a slug: prefer a target with both WISE and SPHEREx frames,
// a spectrum type call, no saturated frame and a measured motion that matches the catalogue,
// then the largest measured motion. Weaker candidates are used only when none qualifies.

import { motionHeadline } from './summary.js';

/** The checks a hero candidate can pass, in plain booleans, and its measured speed (arcsec/yr). */
export function heroTraits(m) {
  const mm = m.measured_motion;
  return {
    bothMissions: m.frames.some((f) => f.mission === 'WISE') && m.frames.some((f) => f.mission === 'SPHEREx'),
    typed: !!m.match,
    unsaturated: !m.frames.some((f) => f.warnings.some((w) => /saturat/i.test(w))),
    agrees: !!motionHeadline(mm, m.target)?.agree,
    speed: mm ? Math.hypot(mm.pmra_masyr, mm.pmdec_masyr) / 1000 : 0,
  };
}

const CHECKS = ['bothMissions', 'agrees', 'unsaturated', 'typed'];

/**
 * @param {{entry: object, manifest: object|null}[]} candidates in index order
 * @returns {object|null} the winning entry, or null for an empty list
 */
export function pickHero(candidates) {
  const scored = candidates.filter((c) => c.manifest).map((c, i) => {
    const t = heroTraits(c.manifest);
    return { c, i, met: CHECKS.filter((k) => t[k]).length, speed: t.speed, moving: t.speed >= 0.05 };
  });
  scored.sort((a, b) => b.moving - a.moving || b.met - a.met || b.speed - a.speed || a.i - b.i);
  return scored[0]?.c.entry ?? candidates[0]?.entry ?? null;
}
