// The site's identity and shared words. The name and tagline live here and nowhere else:
// every page takes its title, header, footer and share text from this module, so a rename
// is one edit. Pure (no DOM), so node can test it.

export const SITE = {
  name: 'Ephemerix',
  tagline: 'Blink. You won\'t miss it.',
  // One line on where the name comes from, shown in the footer.
  gloss: 'The name comes from “ephemeris”, a table of predicted positions for a moving object.',
  team: 'Blink Sixteen',
  event: 'NASA Space Apps 2026',
};

/** Header links, in order. `short` is the label on a phone, where all six must fit one line. */
export const NAV = [
  { key: 'gallery', href: './', label: 'Gallery', short: 'Gallery' },
  { key: 'status', href: 'status.html', label: 'Archive uptime', short: 'Uptime' },
  { key: 'explore', href: 'explore.html', label: 'Explore the sky', short: 'Sky' },
  { key: 'validation', href: 'validation.html', label: 'Do measurements match?', short: 'Results' },
  { key: 'planetx', href: 'planetx.html', label: 'Can it see Planet X?', short: 'Planet X?' },
  { key: 'search', href: 'search.html', label: 'Blind search', short: 'Search' },
];

/** Every data source and service the tool uses, credited on every page. */
export const CREDITS = [
  'SPHEREx and WISE/NEOWISE images: NASA/JPL-Caltech, served by the NASA/IPAC Infrared Science Archive (IRSA)',
  'Star positions and motions: ESA Gaia DR3 (Gaia Collaboration, DPAC) and CatWISE2020 (Marocco et al. 2021), with NOIRLab Astro Data Lab as a second source',
  'Solar System positions and names: JPL Horizons and the JPL Small-Body Database',
  'Object names: CDS Sesame (SIMBAD), Strasbourg',
  'Brown-dwarf templates: SPIFF (Gagné et al., arXiv:2604.22012)',
  'Sun-like reference spectrum: CALSPEC (STScI). Planet Nine reference orbits: Brown and Batygin 2021',
  'Plots: Plotly.js (MIT). Type: Newsreader, IBM Plex Sans and IBM Plex Mono (SIL Open Font License)',
];

export const DISCLAIMER = `A ${SITE.event} entry by team ${SITE.team}. Not an official NASA or ESA product.`;
export const AI_NOTE = 'We used Claude Code to write the code for this site and its data pipeline.';

/** Browser title for a page: "Do measurements match? · Ephemerix", or the name with its tagline. */
export function pageTitle(page = null) {
  return page ? `${page} · ${SITE.name}` : `${SITE.name}: ${SITE.tagline}`;
}
