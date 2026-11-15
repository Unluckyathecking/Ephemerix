// Pointer, wheel and keyboard input for the sky map canvas. Turns raw events into a few intents
// (pan, zoom, tap, hover, key) so the page logic never sees event details.

const TAP_SLOP = 6; // pixels a press may wander and still count as a tap
const TAP_MS = 700;

/**
 * @param {HTMLCanvasElement} canvas
 * @param {{pan: (dx:number, dy:number) => void, zoom: (factor:number, x:number, y:number) => void,
 *   tap: (x:number, y:number) => void, hover: (x:number, y:number) => void, leave: () => void,
 *   key: (e: KeyboardEvent) => boolean, settle: () => void}} on
 */
export function bindInput(canvas, on) {
  const pointers = new Map();
  let press = null; // first pointer of a gesture: start point, time, and whether it became a drag
  let pinch = null;

  const local = (e) => {
    const r = canvas.getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top };
  };
  const pair = () => {
    const [a, b] = [...pointers.values()];
    return { d: Math.hypot(a.x - b.x, a.y - b.y), x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
  };

  canvas.addEventListener('pointerdown', (e) => {
    if (e.button !== 0 && e.pointerType === 'mouse') return;
    canvas.setPointerCapture(e.pointerId);
    const p = local(e);
    pointers.set(e.pointerId, p);
    if (pointers.size === 1) press = { ...p, t: performance.now(), moved: false };
    if (pointers.size === 2) { pinch = pair(); press = press && { ...press, moved: true }; }
    canvas.classList.add('is-grabbing');
  });

  canvas.addEventListener('pointermove', (e) => {
    const p = local(e);
    if (!pointers.has(e.pointerId)) { if (e.pointerType === 'mouse') on.hover(p.x, p.y); return; }
    const prev = pointers.get(e.pointerId);
    pointers.set(e.pointerId, p);
    if (pointers.size === 2 && pinch) {
      const now = pair();
      if (pinch.d > 0 && now.d > 0) on.zoom(now.d / pinch.d, now.x, now.y);
      on.pan(now.x - pinch.x, now.y - pinch.y);
      pinch = now;
      return;
    }
    if (press && !press.moved && Math.hypot(p.x - press.x, p.y - press.y) > TAP_SLOP) press = { ...press, moved: true };
    if (press?.moved) on.pan(p.x - prev.x, p.y - prev.y);
  });

  const end = (e) => {
    if (!pointers.has(e.pointerId)) return;
    const p = local(e);
    pointers.delete(e.pointerId);
    if (pointers.size < 2) pinch = null;
    if (pointers.size === 0) {
      canvas.classList.remove('is-grabbing');
      const wasTap = press && !press.moved && performance.now() - press.t < TAP_MS && e.type === 'pointerup';
      press = null;
      if (wasTap) on.tap(p.x, p.y); else on.settle();
    }
  };
  canvas.addEventListener('pointerup', end);
  canvas.addEventListener('pointercancel', end);
  canvas.addEventListener('pointerleave', (e) => { if (e.pointerType === 'mouse' && !pointers.size) on.leave(); });

  let wheelTimer = 0;
  canvas.addEventListener('wheel', (e) => {
    e.preventDefault();
    const p = local(e);
    const lines = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? 400 : 1;
    on.zoom(Math.exp(-e.deltaY * lines * 0.0018), p.x, p.y);
    clearTimeout(wheelTimer);
    wheelTimer = setTimeout(on.settle, 250);
  }, { passive: false });

  canvas.addEventListener('keydown', (e) => { if (on.key(e)) e.preventDefault(); });
}
