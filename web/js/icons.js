// Player icons as inline SVG, so they look the same on every platform (the text glyphs
// they replace render as colour emoji on some phones).

const PATHS = {
  play: 'M4 2.5v11l9-5.5z',
  pause: 'M3.5 2.5h3v11h-3zM9.5 2.5h3v11h-3z',
  prev: 'M3 2.5h2v11H3zM14 2.5v11L6 8z',
  next: 'M11 2.5h2v11h-2zM2 2.5v11L10 8z',
};

/** @param {'play'|'pause'|'prev'|'next'} name */
export function icon(name) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 16 16');
  svg.setAttribute('aria-hidden', 'true');
  svg.setAttribute('focusable', 'false');
  const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  path.setAttribute('d', PATHS[name]);
  svg.append(path);
  return svg;
}
