// Draws one frame of the sky map on a 2D canvas and returns where the clickable things landed,
// so hit-testing never re-projects. Only what is on screen is projected and drawn.

import { project, toVec, crossesSeam } from './exploreproj.js';
import { galToEq, eclToEq, hammer } from './skymath.js';
import { magLimit, countBrighter, starRadius, starColour } from './exploredata.js';
import { place, drawTargets, drawKnown, drawPaths, drawPin } from './exploremarks.js';

const TAU = Math.PI * 2;

function sampled(fn, step = 2) {
  const out = [];
  for (let t = 0; t <= 360; t += step) { const p = fn(t); out.push(toVec(p.ra, p.dec)); }
  return out;
}

/** Guide curves, computed once: ecliptic, galactic plane, and an RA/Dec grid. */
export function guideCurves() {
  const grid = [];
  for (let h = 0; h < 24; h += 2) grid.push(sampled((t) => ({ ra: h * 15, dec: t / 2 - 90 }), 3));
  for (let d = -75; d <= 75; d += 15) grid.push(sampled((t) => ({ ra: t, dec: d }), 3));
  return {
    ecliptic: sampled((t) => eclToEq(t, 0)),
    galactic: sampled((t) => galToEq(t, 0)),
    grid,
  };
}

/** Stroke a sampled curve, lifting the pen where it passes behind the view. */
function strokeCurve(ctx, view, vecs) {
  let prev = null;
  for (const v of vecs) {
    const p = project(view, v);
    if (prev && !crossesSeam(prev.lon, p.lon) && Math.abs(p.lon) < 179) ctx.lineTo(p.x, p.y);
    else ctx.moveTo(p.x, p.y);
    prev = p;
  }
}

/** The outline of the whole sky (the edge of the ellipse) when zoomed far out. */
function skyOutline(ctx, view) {
  ctx.beginPath();
  for (let lat = -90; lat <= 90; lat += 3) {
    const h = hammer(180, lat);
    const x = view.cx - view.k * h.x, y = view.cy - view.k * h.y;
    if (lat === -90) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  }
  for (let lat = 90; lat >= -90; lat -= 3) {
    const h = hammer(-180, lat);
    ctx.lineTo(view.cx - view.k * h.x, view.cy - view.k * h.y);
  }
  ctx.closePath();
}

const onScreen = (p, view, pad) => p.x > -pad && p.y > -pad && p.x < view.width + pad && p.y < view.height + pad;

/** Cosine of the largest angle from the centre that can still be on screen. */
function visibleCos(view) {
  const half = (view.fov / 2) * (Math.hypot(view.width, view.height) / view.width) * 1.3 + 2;
  return half >= 180 ? -2 : Math.cos((half * Math.PI) / 180);
}

function drawStars(ctx, view, stars, named, palette) {
  // A narrow canvas showing a wide field gets fewer, smaller stars so it does not turn to noise.
  const crowd = Math.min(1, Math.max(0.5, view.k / 200));
  const limit = magLimit(view.fov) - (crowd < 1 ? (1 - crowd) * 2 : 0);
  const n = countBrighter(stars.mag, limit);
  const cosMin = visibleCos(view);
  const c = toVec(view.ra, view.dec);
  const paths = new Map();
  const hits = [];
  const glows = [];
  for (let i = 0; i < n; i++) {
    const x = stars.xyz[i * 3], y = stars.xyz[i * 3 + 1], z = stars.xyz[i * 3 + 2];
    if (x * c[0] + y * c[1] + z * c[2] < cosMin) continue;
    const p = project(view, [x, y, z]);
    if (!onScreen(p, view, 6)) continue;
    const r = starRadius(stars.mag[i], view.fov) * crowd;
    const colour = starColour(stars.bv[i]);
    let path = paths.get(colour);
    if (!path) { path = new Path2D(); paths.set(colour, path); }
    if (r < 1.2) path.rect(p.x - r, p.y - r, 2 * r, 2 * r);
    else { path.moveTo(p.x + r, p.y); path.arc(p.x, p.y, r, 0, TAU); }
    if (stars.mag[i] < 1.6) glows.push([p.x, p.y, r]);
    const name = named.get(i);
    if (name) hits.push({ x: p.x, y: p.y, i, name, mag: stars.mag[i], ra: stars.ra[i], dec: stars.dec[i] });
  }
  for (const [x, y, r] of glows) {
    const g = ctx.createRadialGradient(x, y, 0, x, y, r * 4);
    g.addColorStop(0, palette.glow);
    g.addColorStop(1, 'rgba(0,0,0,0)');
    ctx.fillStyle = g;
    ctx.fillRect(x - r * 4, y - r * 4, r * 8, r * 8);
  }
  for (const [colour, path] of paths) { ctx.fillStyle = colour; ctx.fill(path); }
  return hits;
}

function drawFigures(ctx, view, stars, figures, palette) {
  const cosMin = visibleCos(view);
  const c = toVec(view.ra, view.dec);
  ctx.beginPath();
  const cache = new Map();
  const pt = (i) => {
    if (!cache.has(i)) {
      const v = [stars.xyz[i * 3], stars.xyz[i * 3 + 1], stars.xyz[i * 3 + 2]];
      cache.set(i, v[0] * c[0] + v[1] * c[1] + v[2] * c[2] < cosMin ? null : project(view, v));
    }
    return cache.get(i);
  };
  for (const f of figures) {
    for (const poly of f.lines) {
      for (let j = 1; j < poly.length; j++) {
        const a = pt(poly[j - 1]), b = pt(poly[j]);
        if (!a || !b || crossesSeam(a.lon, b.lon) || Math.abs(a.lon) > 170 || Math.abs(b.lon) > 170) continue;
        ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y);
      }
    }
  }
  ctx.strokeStyle = palette.figure;
  ctx.lineWidth = 1;
  ctx.stroke();
}

function drawFigureNames(ctx, view, figures, palette, placed) {
  // Constellation names only once there is room for them (about 230 px per radian of sky).
  if (view.fov > 220 || view.fov < 6 || view.k < 230) return;
  ctx.font = `500 ${view.fov > 100 ? 10 : 11}px ${palette.sans}`;
  for (const f of figures) {
    if (!f.labelVec) continue;
    const p = project(view, f.labelVec);
    if (Math.abs(p.lon) > 150 || !onScreen(p, view, 0)) continue;
    place(ctx, placed, f.name.toUpperCase(), p.x, p.y, palette.figureName, 'center');
  }
}

function drawStarNames(ctx, view, hits, palette, placed) {
  const limit = (view.fov > 150 ? 1.0 : view.fov > 60 ? 2.0 : view.fov > 20 ? 3.2 : 4.5) - (view.k < 250 ? 0.7 : 0);
  ctx.font = `400 11px ${palette.sans}`;
  ctx.strokeStyle = palette.starRing;
  ctx.lineWidth = 1;
  for (const h of hits) {
    if (h.mag > limit) continue;
    // The quieter marker class: well-known named stars get a thin ring and their name.
    ctx.beginPath(); ctx.arc(h.x, h.y, starRadius(h.mag, view.fov) + 4, 0, TAU); ctx.stroke();
  }
  for (const h of hits) if (h.mag <= limit) place(ctx, placed, h.name, h.x + 8, h.y - 6, palette.starName);
}

/**
 * Draw a frame. `scene`: {stars, figures, named (Map index -> name), targets, known, guides, pin, selected, grid}.
 * @returns {{targets: Array<{x:number,y:number}|null>, known: Array<{x:number,y:number}|null>, stars: Array<object>}}
 */
export function drawFrame(ctx, view, scene, palette) {
  ctx.fillStyle = palette.space;
  ctx.fillRect(0, 0, view.width, view.height);
  if (view.fov > 150) {
    skyOutline(ctx, view);
    ctx.fillStyle = palette.sky; ctx.fill();
    ctx.strokeStyle = palette.outline; ctx.lineWidth = 1; ctx.stroke();
    ctx.save();
    ctx.clip(); // keep the Milky Way band inside the sky
  } else {
    ctx.save();
    ctx.fillStyle = palette.sky; ctx.fillRect(0, 0, view.width, view.height);
  }
  ctx.lineWidth = 1;
  if (scene.grid) {
    ctx.beginPath();
    for (const c of scene.guides.grid) strokeCurve(ctx, view, c);
    ctx.strokeStyle = palette.grid; ctx.stroke();
  }
  // The Milky Way as a soft band about 20 and 8 degrees wide along the galactic plane.
  const degPx = (view.k * Math.PI) / 180;
  ctx.lineCap = 'round';
  ctx.beginPath(); strokeCurve(ctx, view, scene.guides.galactic);
  ctx.strokeStyle = palette.band; ctx.lineWidth = 20 * degPx; ctx.stroke();
  ctx.lineWidth = 8 * degPx; ctx.stroke();
  ctx.lineCap = 'butt';
  ctx.restore();
  ctx.setLineDash([2, 5]);
  ctx.beginPath(); strokeCurve(ctx, view, scene.guides.galactic);
  ctx.strokeStyle = palette.galactic; ctx.lineWidth = 1.5; ctx.stroke();
  ctx.setLineDash([6, 6]);
  ctx.beginPath(); strokeCurve(ctx, view, scene.guides.ecliptic);
  ctx.strokeStyle = palette.ecliptic; ctx.lineWidth = 1; ctx.stroke();
  ctx.setLineDash([]);
  drawFigures(ctx, view, scene.stars, scene.figures, palette);
  const starHits = drawStars(ctx, view, scene.stars, scene.named, palette);
  // Labels are placed in priority order: our views, then the objects we can build, then stars and
  // constellations; a label that would overlap one already placed is dropped.
  const placed = [];
  const paths = drawPaths(ctx, view, scene.targets, palette);
  drawPin(ctx, view, scene.pin, palette);
  const knownPts = drawKnown(ctx, view, scene.known, scene.selected, palette);
  const targetPts = drawTargets(ctx, view, scene.targets, scene.selected, palette, placed);
  ctx.font = `500 11px ${palette.sans}`;
  for (const k of knownPts.labels) place(ctx, placed, k.text, k.x, k.y, palette.known);
  drawStarNames(ctx, view, starHits, palette, placed);
  drawFigureNames(ctx, view, scene.figures, palette, placed);
  return { targets: targetPts, known: knownPts.pts, stars: starHits, paths };
}
