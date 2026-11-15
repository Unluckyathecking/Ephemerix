// The one sentence that leads a view of a hard field (docs/api.md `field`). Pure.
//
// Only glare leads for now: the crowding rule (`field.crowded`) has not yet been confirmed on a
// real crowded field, so it is not headlined.

const GLARE = /^This spot is so bright in the infrared/;

/**
 * The pipeline's own glare sentence when `field.saturated` is true, else null.
 * @param {object} m validated manifest
 * @returns {string|null}
 */
export function fieldHeadline(m) {
  if (!m?.field?.saturated) return null;
  return (m.warnings || []).find((w) => GLARE.test(w)) || null;
}
