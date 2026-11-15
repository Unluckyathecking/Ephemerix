// Link-outs to other public tools for one sky position, built from RA/Dec only. Pure.
// Each pattern was checked by loading it for WISE 0855-0714 (see web/README.md).

const fmt = (x) => x.toFixed(6);

/**
 * @param {number} ra degrees
 * @param {number} dec degrees
 * @param {number} [fovArcsec] field to show where the tool takes one
 * @returns {{id: string, label: string, help: string, href: string}[]}
 */
export function linkOuts(ra, dec, fovArcsec = 240) {
  if (!Number.isFinite(ra) || !Number.isFinite(dec) || ra < 0 || ra >= 360 || dec < -90 || dec > 90) return [];
  const fov = Number.isFinite(fovArcsec) && fovArcsec > 0 ? fovArcsec : 240;
  const r = fmt(ra), d = fmt(dec);
  return [
    { id: 'aladin', label: 'Aladin Lite (CDS)', help: 'Survey images of this field',
      href: `https://aladin.cds.unistra.fr/AladinLite/?ra=${r}&dec=${d}&fov=${(fov / 3600 * 2).toFixed(4)}` },
    { id: 'wiseview', label: 'WiseView', help: 'Blink the unWISE images',
      href: `http://byw.tools/wiseview#ra=${r}&dec=${d}&size=${Math.min(2000, Math.round(fov))}` },
    { id: 'irsa-spherex', label: 'IRSA SPHEREx Data Explorer', help: 'Every SPHEREx image that covers this point',
      href: `https://irsa.ipac.caltech.edu/applications/spherex/?api=spectral-images&ra=${r}&dec=${d}&spatialRegionOperation=contains_point&execute=true` },
  ];
}
