// The footer's one line on how current the SPHEREx data is, from data/data-status.json
// (tools/data_status.py). Pure: no DOM, no fetch. Anything off gives '' so the footer shows nothing.

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** "2026-10-02" -> "2 Oct 2026"; null for anything that is not a real calendar date. */
export function formatDate(iso) {
  const m = typeof iso === 'string' ? /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso) : null;
  if (!m) return null;
  const [y, mo, d] = [Number(m[1]), Number(m[2]), Number(m[3])];
  const probe = new Date(Date.UTC(y, mo - 1, d));
  if (probe.getUTCFullYear() !== y || probe.getUTCMonth() !== mo - 1 || probe.getUTCDate() !== d) return null;
  return `${d} ${MONTHS[mo - 1]} ${y}`;
}

function names(releases) {
  const n = releases.map((r) => r.name);
  const list = n.length > 1 ? `${n.slice(0, -1).join(', ')} and ${n[n.length - 1]}` : n[0];
  return `${n.length > 1 ? 'releases' : 'release'} ${list}`;
}

/** @param {object} status parsed data-status.json @returns {string} the line, or '' */
export function dataStatusLine(status) {
  const ix = status?.index;
  if (!ix || !Array.isArray(ix.releases) || ix.releases.length === 0) return '';
  const through = formatDate(ix.newest_frame);
  const refreshed = formatDate(ix.refreshed);
  const total = ix.frames_total;
  if (!through || !refreshed || !Number.isInteger(total) || total < 0) return '';
  if (!ix.releases.every((r) => typeof r?.name === 'string' && r.name.trim())) return '';
  let line = `SPHEREx data through ${through} (${names(ix.releases)}; ${total.toLocaleString('en-GB')} frames indexed, last refreshed ${refreshed}).`;
  if (status.gallery !== undefined && status.gallery !== null) {
    const newest = formatDate(status.gallery.newest_frame);
    const built = formatDate(status.gallery.built);
    if (!newest || !built) return '';
    line += ` The views on this site show SPHEREx frames to ${newest} and were built on ${built}.`;
  }
  return line;
}
