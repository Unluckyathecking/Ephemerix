// Tiny DOM helpers. All text goes through textContent; manifest strings are untrusted.

/**
 * Create an element. attrs: plain attributes, plus `text`, `class`, `on{Event}` handlers.
 * @param {string} tag
 * @param {Record<string, any>} [attrs]
 * @param {Array<Node|string|null|false>} [children]
 */
export function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === 'text') node.textContent = v;
    else if (k === 'class') node.className = v;
    else if (k.startsWith('on') && typeof v === 'function') node.addEventListener(k.slice(2).toLowerCase(), v);
    else node.setAttribute(k, v === true ? '' : String(v));
  }
  for (const c of children) if (c != null && c !== false) node.append(c);
  return node;
}

export const $ = (sel, root = document) => root.querySelector(sel);

/** Copy text; falls back to a selected textarea when the Clipboard API is unavailable. */
export async function copyText(text) {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch { /* fall through to the textarea route */ }
  const ta = el('textarea', { class: 'offscreen', 'aria-hidden': 'true' });
  ta.value = text;
  document.body.append(ta);
  ta.select();
  let ok = false;
  try { ok = document.execCommand('copy'); } catch { ok = false; }
  ta.remove();
  return ok;
}

/** Brief status message in a polite live region next to a button. */
export function flash(node, message, ms = 2400) {
  node.textContent = message;
  clearTimeout(node._t);
  node._t = setTimeout(() => { node.textContent = ''; }, ms);
}

export const prefersReducedMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;

/** True when a key event should be left to the focused control. */
export function isTypingTarget(target, key) {
  if (!(target instanceof Element)) return false;
  if (target.closest('dialog[open]')) return true;
  if (target.matches('textarea, select, [contenteditable="true"]')) return true;
  if (target.matches('input')) return true;
  if (key === ' ' && target.matches('button, a, summary, [role="button"]')) return true;
  return false;
}

/** Short date like "8 May 2010". */
export function shortDate(iso) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' });
}
