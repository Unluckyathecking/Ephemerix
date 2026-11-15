// Sky <-> pixel math for the manifest grid (docs/api.md).
// Pixel convention: edges. Top-left corner is (0, 0), the grid centre is at
// (size/2, size/2), x grows west (RA down), y grows south (Dec down).
// Matches src/pxs/astrometry.py.

const RAD = Math.PI / 180;
const MAS_PER_DEG = 3.6e6;

/** Julian epoch (decimal year) of an MJD. */
export function decimalYear(mjd) {
  return 2000 + (mjd - 51544.5) / 365.25;
}

/** Move a position by linear proper motion. pmra includes cos(dec); cos taken at the start dec. */
export function propagate(ra, dec, epoch, pmra, pmdec, toYear) {
  const dt = toYear - epoch;
  const raNew = ra + (pmra * dt) / MAS_PER_DEG / Math.cos(dec * RAD);
  return { ra: ((raNew % 360) + 360) % 360, dec: dec + (pmdec * dt) / MAS_PER_DEG };
}

/** Grid description from a manifest. */
export function gridOf(manifest) {
  return {
    ra0: manifest.center.ra,
    dec0: manifest.center.dec,
    size: manifest.size_px,
    scale: manifest.fov_arcsec / manifest.size_px, // arcsec per pixel
  };
}

/** Pixel [x, y] of a sky position on the grid, or null if behind the tangent point. */
export function skyToPx(grid, ra, dec) {
  const a = ra * RAD, d = dec * RAD, a0 = grid.ra0 * RAD, d0 = grid.dec0 * RAD;
  const da = a - a0;
  const cosc = Math.sin(d0) * Math.sin(d) + Math.cos(d0) * Math.cos(d) * Math.cos(da);
  if (cosc <= 0) return null;
  const xi = (Math.cos(d) * Math.sin(da)) / cosc;
  const eta = (Math.cos(d0) * Math.sin(d) - Math.sin(d0) * Math.cos(d) * Math.cos(da)) / cosc;
  const k = 1 / (grid.scale / 3600 * RAD);
  return [grid.size / 2 - xi * k, grid.size / 2 - eta * k];
}

/** Sky position {ra, dec} (deg) of pixel (x, y). */
export function pxToSky(grid, x, y) {
  const s = (grid.scale / 3600) * RAD;
  const xi = (grid.size / 2 - x) * s;
  const eta = (grid.size / 2 - y) * s;
  const a0 = grid.ra0 * RAD, d0 = grid.dec0 * RAD;
  const rho = Math.hypot(xi, eta);
  if (rho === 0) return { ra: grid.ra0, dec: grid.dec0 };
  const c = Math.atan(rho);
  const dec = Math.asin(Math.cos(c) * Math.sin(d0) + (eta * Math.sin(c) * Math.cos(d0)) / rho);
  const ra = a0 + Math.atan2(xi * Math.sin(c), rho * Math.cos(d0) * Math.cos(c) - eta * Math.sin(d0) * Math.sin(c));
  return { ra: (((ra / RAD) % 360) + 360) % 360, dec: dec / RAD };
}

/** Pixel position of a catalogue source at a given decimal year. */
export function sourcePxAt(grid, src, year) {
  const pmra = Number.isFinite(src.pmra_masyr) ? src.pmra_masyr : 0;
  const pmdec = Number.isFinite(src.pmdec_masyr) ? src.pmdec_masyr : 0;
  const p = propagate(src.ra, src.dec, src.epoch, pmra, pmdec, year);
  return skyToPx(grid, p.ra, p.dec);
}

/** Total motion (mas/yr) and position angle (deg east of north) from components. */
export function motionVector(pmra, pmdec) {
  const total = Math.hypot(pmra, pmdec);
  const pa = ((Math.atan2(pmra, pmdec) / RAD) % 360 + 360) % 360;
  return { total, pa };
}
