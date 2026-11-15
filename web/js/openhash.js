// A link to a part of the page that sits in a closed <details> opens that section, so
// "planetx.html#px-sources" lands on the sources rather than on a closed heading.

function openTarget() {
  const id = decodeURIComponent(location.hash.slice(1));
  const target = id && document.getElementById(id);
  if (!target) return;
  let opened = false;
  for (let d = target.closest('details'); d; d = d.parentElement?.closest('details')) {
    if (!d.open) { d.open = true; opened = true; }
  }
  if (opened) target.scrollIntoView();
}

/** Open the linked section now and whenever the hash changes. */
export function openLinkedSection() {
  openTarget();
  window.addEventListener('hashchange', openTarget);
}
