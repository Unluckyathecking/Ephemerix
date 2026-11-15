// A faint hatch over the pixels of a frame that hold no usable data (docs/api.md `gaps_image`:
// a mask PNG, 255 where there is no data). The hatch is built once per frame at image resolution
// and drawn with the image, so it zooms and pans with it.

export const GAP_KEY = (id) => `gaps:${id}`;
export const HATCH_LEGEND = 'Hatched: no usable data here';
const STEP = 4; // one diagonal line every STEP image pixels
const RGBA = [205, 214, 228, 90]; // pale grey, about a third opaque

/**
 * Pure: hatch pixels from mask pixels. `mask` is RGBA bytes of a w x h image; returns RGBA bytes
 * that are transparent except on every STEP-th diagonal inside the masked area.
 * @param {Uint8ClampedArray} mask
 * @param {number} w
 * @param {number} h
 */
export function hatchPixels(mask, w, h) {
  const out = new Uint8ClampedArray(w * h * 4);
  for (let y = 0; y < h; y += 1) {
    for (let x = 0; x < w; x += 1) {
      const i = (y * w + x) * 4;
      if (mask[i] > 127 && (x + y) % STEP === 0) out.set(RGBA, i);
    }
  }
  return out;
}

/** The hatch as a canvas the size of the mask image, or null if it cannot be read. */
export function hatchCanvas(img) {
  const w = img.naturalWidth || img.width, h = img.naturalHeight || img.height;
  if (!w || !h) return null;
  try {
    const c = document.createElement('canvas');
    c.width = w;
    c.height = h;
    const ctx = c.getContext('2d');
    ctx.drawImage(img, 0, 0);
    const data = ctx.getImageData(0, 0, w, h);
    data.data.set(hatchPixels(data.data, w, h));
    ctx.putImageData(data, 0, 0);
    return c;
  } catch {
    return null; // a mask from another origin without CORS cannot be read: no hatch
  }
}
