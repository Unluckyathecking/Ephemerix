// Words around the SPHEREx band strip (js/bandstrip.js). Pure.

// What each thumbnail is: one detector array's frame of the pass, its exposures stacked.
export const STRIP_LEAD = 'Each thumbnail is one of SPHEREx’s six detector arrays: its exposures from this pass, added together.';

const PICK = 'Click a band to blink it over time.';
const METHANE = 'A cold brown dwarf is faint where methane absorbs (about 1.6–2.4 and 3.3 µm) and brightest near 4–5 µm.';
// An L, T or Y spectral type, also subdwarfs ("sdT3") and "d/sdL9".
const BROWN_DWARF_TYPE = /^(?:d\/)?(?:sd)?[LTY]\d/;

/**
 * Is the target a brown dwarf? The published type (gallery index) when known, else the spectrum's class.
 * @param {string|null|undefined} publishedType e.g. "T4.5", "M4 star"
 * @param {string|null|undefined} matchClass the spectrum verdict's class, e.g. "brown dwarf"
 */
export function isBrownDwarf(publishedType, matchClass) {
  if (publishedType) return BROWN_DWARF_TYPE.test(publishedType.trim());
  return matchClass === 'brown dwarf';
}

/** The line under the thumbnails: the methane sentence only for a brown dwarf. */
export function stripNote(brownDwarf) {
  return brownDwarf ? `${METHANE} ${PICK}` : PICK;
}
