// Pure text for the top of the Planet X page: what we found on real objects, one line each,
// from data/movers.json, data/body-recovery.json and the Haumea and Makemake view manifests.
// No DOM, so node:test covers it. A line whose data is missing is left out.

const fin = (v) => typeof v === 'number' && Number.isFinite(v);
const pct = (x) => `${Math.round(x * 100)}%`;
const list = (xs) => (xs.length > 1 ? `${xs.slice(0, -1).join(', ')} and ${xs.at(-1)}` : xs.join(''));

/** The blind search: every known dwarf planet ranked first in its field, at its catalogue position. */
export function blindLine(movers) {
  const kb = movers?.known_bodies;
  if (!Array.isArray(kb) || !kb.length) return null;
  const top = kb.every((k) => k.rank === 1);
  const onPos = kb.every((k) => fin(k.offset_px) && k.offset_px <= 1);
  const px = movers.campaign?.pixscale_arcsec;
  const where = onPos ? `, at its JPL position to within one ${fin(px) ? `${Math.round(px)}″ ` : ''}pixel` : '';
  const snr = kb.every((k) => fin(k.snr)) ? ` (S/N ${list(kb.map((k) => k.snr.toFixed(1)))})` : '';
  const how = top ? `each the strongest signal in its field${where}${snr}` : `found ${kb.length} of ${kb.length}${snr}`;
  return { text: `Given no positions, our blind slow-mover search picks out ${list(kb.map((k) => k.name))}, ${how}: a validation, not a discovery.`,
    href: 'search.html', link: 'The blind search' };
}

/** Known bodies followed along their JPL orbits in SPHEREx: recovered of sampled, and beyond Neptune. */
export function recoveryLine(bodies) {
  const b = bodies?.bodies;
  if (!b || !fin(b.recovered) || !fin(b.n)) return null;
  const tno = bodies.by_class?.TNO;
  const tail = tno && fin(tno.recovered) && fin(tno.n) ? ` (${tno.recovered} of ${tno.n} beyond Neptune)` : '';
  return { text: `Following known orbits, our body views recovered ${b.recovered} of ${b.n} known Solar System bodies in SPHEREx${tail}, each within 12″ of its JPL position.`,
    href: 'validation.html#bodies', link: 'Known bodies recovered' };
}

/** "water" or "methane" from the pipeline's own reading of the all-passes spectrum. */
function iceKind(refl) {
  const m = /pattern of (water|methane) ice/.exec(refl?.reading || '');
  return m ? m[1] : null;
}

function depthWords(d) {
  if (d.saturated && fin(d.depth_min)) return `deeper than ${pct(d.depth_min)}`;
  return fin(d.depth) && fin(d.err) ? `${pct(d.depth)} ± ${pct(d.err)} deep` : null;
}

/** One body's ice: Haumea's 2.0 µm water band, Makemake's 2.3 µm methane band. Null if not measured. */
export function iceClause(name, manifest) {
  const refl = (manifest?.solar_system?.reflectance || []).find((r) => r.spectrum_id === 'all-detected');
  const kind = iceKind(refl);
  if (!kind) return null;
  const um = kind === 'water' ? '2.0' : '2.3';
  const d = (refl.band_depths || []).find((x) => x.detected && String(x.label).startsWith(um));
  const w = d && depthWords(d);
  return w ? `${name}’s ${kind} ice (the ${um} µm band ${w})` : null;
}

/** The two body views: their ice, measured by following each body along its orbit. */
export function iceLine(haumea, makemake) {
  const parts = [iceClause('Haumea', haumea), iceClause('Makemake', makemake)].filter(Boolean);
  if (!parts.length) return null;
  return { text: `Following them along their orbits, SPHEREx measures ${list(parts)}.`,
    href: 'index.html?target=haumea', link: 'The Haumea view', href2: 'index.html?target=makemake', link2: 'the Makemake view' };
}

/** All the lines that have their data, in reading order. */
export function foundLines({ movers, bodies, haumea, makemake }) {
  return [blindLine(movers), recoveryLine(bodies), iceLine(haumea, makemake)].filter(Boolean);
}
