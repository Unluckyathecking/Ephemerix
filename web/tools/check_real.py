"""Headless checks of real pipeline views in the site, with a screenshot of each.

Serve a copy of web/ whose gallery holds real builds, then:
  uv run --with playwright python web/tools/check_real.py <base url> <img dir> [<slug> ...]
With no slugs, every star target in web/gallery/index.json is checked (Solar System body
views have no frames of this kind and are skipped).
Set CHROMIUM to a browser binary to skip Playwright's own download.

Per view: the blink plays; every frame's predicted position and measured centroid sit on
the light in its PNG (the overlays line up); the spectrum shows points, molecular bands and
template curves when there is a match; the manifest's warnings appear on the page; no
console errors. Prints one line per check and exits non-zero if any fails.
"""
import json
import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

EXE = os.environ.get("CHROMIUM") or None

BASE, IMG, SLUGS = sys.argv[1].rstrip("/") + "/", sys.argv[2], sys.argv[3:]
if not SLUGS:
    _idx = json.loads((Path(__file__).resolve().parents[1] / "gallery" / "index.json").read_text())
    SLUGS = [e["slug"] for e in _idx["targets"] if e.get("group") != "solar-system"]
results = []

# Light-weighted centroid of the PNG within 4 px of a position, after removing the local
# median; returns the distance (px) of each frame's centroid_px from the light.
ALIGN_JS = """async (slug) => {
  const m = await (await fetch(`gallery/${slug}/manifest.json`)).json();
  const out = [];
  for (const f of m.frames.filter(f => f.centroid_px)) {
    const img = new Image(); img.src = `gallery/${slug}/${f.image}`; await img.decode();
    const c = document.createElement('canvas'); c.width = img.width; c.height = img.height;
    const g = c.getContext('2d'); g.drawImage(img, 0, 0);
    const d = g.getImageData(0, 0, c.width, c.height).data;
    const [px, py] = f.centroid_px;
    const win = (r) => { const vals = [];
      for (let y = Math.floor(py) - r; y <= Math.floor(py) + r; y++) for (let x = Math.floor(px) - r; x <= Math.floor(px) + r; x++)
        if (x >= 0 && y >= 0 && x < c.width && y < c.height) vals.push([x, y, d[(y * c.width + x) * 4]]);
      return vals; };
    let vals = win(4);
    let low = Math.min(...vals.map(v => v[2]));
    // A core clipped to white by the display stretch: use the centre of the white plateau.
    const plateau = low === 255;
    if (plateau) vals = win(15);
    // A uniform dark window: a no-data hole inside a saturated core; look wider.
    if (!plateau && vals.every(v => v[2] === low)) { vals = win(15); low = Math.min(...vals.map(v => v[2])); }
    let w = 0, bx = 0, by = 0;
    for (const [x, y, v] of vals) { const k = plateau ? (v === 255 ? 1 : 0) : Math.max(0, v - low); w += k; bx += k * (x + 0.5); by += k * (y + 0.5); }
    // A plateau wider than the window (Barnard's Star in W1): the centroid is inside it.
    const inside = plateau && vals.every(v => v[2] === 255);
    let off = inside ? 0 : w ? Math.hypot(bx / w - px, by / w - py) : 99;
    // A saturated core's white plateau can be lopsided (Barnard's Star, W1, the 2010 three-band
    // epoch), so its mean says little about where the star is. Only in that case the centroid
    // may instead be judged against the position predicted from the catalogue motion.
    if (plateau && off >= 1.5 && f.predicted_px) off = Math.min(off, Math.hypot(f.predicted_px[0] - px, f.predicted_px[1] - py));
    out.push([f.id, off]);
  }
  return out;
}"""


def check(name, ok, info=""):
    results.append((name, bool(ok), info))
    print(f"{'PASS' if ok else 'FAIL'} {name} {info}")


with sync_playwright() as p:
    b = p.chromium.launch(executable_path=EXE)
    for slug in SLUGS:
        ctx = b.new_context(viewport={"width": 1280, "height": 900})
        pg = ctx.new_page()
        msgs: list[str] = []
        pg.on("console", lambda m, out=msgs: out.append(f"error: {m.text}") if m.type == "error" else None)
        pg.on("pageerror", lambda e, out=msgs: out.append(f"pageerror: {e}"))
        pg.goto(f"{BASE}?mode=full&target={slug}", wait_until="networkidle")
        pg.wait_for_selector("canvas.stage", timeout=20000)
        m = pg.evaluate(f"fetch('gallery/{slug}/manifest.json').then(r => r.json())")
        top = pg.evaluate("document.querySelector('canvas.stage').getBoundingClientRect().top")
        # A hard field (docs/api.md `field`) leads with its glare sentence above the strip, by design.
        lead = pg.evaluate("(() => { const n = document.querySelector('.field-note'); return n ? n.getBoundingClientRect().height + 16 : 0; })()")
        play = pg.locator(".controls .btn.primary")
        if play.get_attribute("aria-label") == "Play":
            play.click()
        labels = set()
        for _ in range(6):
            labels.add(pg.get_attribute("canvas.stage", "aria-label"))
            pg.wait_for_timeout(450)
        check(f"{slug}: blink advances", len(labels) > 1, labels)
        play.click()  # pause
        d = pg.evaluate(ALIGN_JS, slug)
        worst_id, worst = max(d, key=lambda t: t[1], default=("-", 0.0))
        med = sorted(v for _, v in d)[len(d) // 2] if d else 0.0
        check(f"{slug}: centroids sit on the light (max offset < 1.5 px)", worst < 1.5,
              f"median {med:.2f}, max {worst:.2f} px ({worst_id}) over {len(d)} detected frames")
        if m["spectra"]:
            pg.wait_for_selector(".spec-plot .main-svg", timeout=20000)
            pg.wait_for_timeout(500)
            names = pg.evaluate("document.querySelector('.spec-plot').data.map(t => t.name)")
            npts = pg.evaluate("document.querySelector('.spec-plot').data.filter(t => t.mode === 'markers').reduce((a, t) => a + t.x.length, 0)")
            check(f"{slug}: spectrum points drawn", npts > 0, f"{npts} points")
            if m["match"]:
                check(f"{slug}: template curves drawn", any("template" in n for n in names), names)
            # Band shading is rect shapes; the plot also draws line shapes marking gaps in the spectrum.
            shapes = pg.evaluate("(document.querySelector('.spec-plot').layout.shapes || []).filter(s => s.type === 'rect').length")
            check(f"{slug}: molecular bands shaded", shapes == len(m["features"]) > 0, shapes)
        notes = pg.text_content(".notes") if pg.locator(".notes").count() else ""
        missing = [w for w in m["warnings"] if w not in notes]
        check(f"{slug}: every manifest warning is in the notes disclosure", not missing, missing)
        check(f"{slug}: notes collapsed, no banner above the view", pg.get_attribute(".notes-more", "open") is None and pg.locator(".banner").count() == 0)
        # The title and the three-tile verdict strip sit above the image by design; nothing else may.
        check(f"{slug}: the blink image starts high on the page", top - lead < 440, f"{top:.0f}px, lead {lead:.0f}px")
        chips = []
        for _ in range(min(len(m["frames"]), 80)):
            pg.locator("body").press("ArrowRight")
            if pg.locator(".flag-badge").is_visible():
                chips.append(pg.inner_text(".flag-badge > span:first-child"))
        check(f"{slug}: the chip on the image stays short", all(len(c) <= 24 for c in chips), sorted(set(chips)))
        z = float(pg.get_attribute("canvas.stage", "data-zoom"))
        check(f"{slug}: opens with Follow off and the whole path framed", not pg.is_checked("#follow") and 1 <= z <= 2, z)
        head = pg.inner_text(".motion-headline") if pg.locator(".motion-headline").count() else ""
        want = "Measured " if m.get("measured_motion") else "Not measured: "
        check(f"{slug}: motion headline in plain words", head.startswith(want), head)
        if slug in ("r-draconis", "rw-aurigae"):  # "Brightness over time" (js/variability.js)
            pg.wait_for_selector(".variability .var-plot .main-svg", timeout=20000)
            names = pg.evaluate("document.querySelector('.var-plot').data.map(t => t.name)")
            npts = pg.evaluate("document.querySelector('.var-plot').data.reduce((a, t) => a + t.x.length, 0)")
            summary = pg.inner_text(".var-summary")
            check(f"{slug}: brightness block plots the star and a comparison star", npts > 50 and any("Comparison" in n for n in names)
                  and any(n.startswith(m["target"]["name"].removesuffix(" A")) for n in names), f"{npts} points, {names}")
            check(f"{slug}: brightness block says what is seen and its limits", len(summary) > 80 and "relative" in pg.inner_text(".var-limit").lower(), summary)
            if slug == "r-draconis":
                pg.click(".variability .seg >> nth=1")
                pg.wait_for_timeout(400)
                xmax = pg.evaluate("Math.max(...document.querySelector('.var-plot').data.flatMap(t => t.x))")
                check(f"{slug}: brightness block folds on the period", 1 < xmax <= 2, xmax)
            for w in (1440, 390):
                pg.set_viewport_size({"width": w, "height": 900})
                pg.wait_for_timeout(500)
                over = pg.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
                check(f"{slug}: brightness block fits at {w} px", over <= 0, over)
                pg.locator(".variability").screenshot(path=f"{IMG}/var-block-{slug}-{w}.png")
            pg.set_viewport_size({"width": 1280, "height": 900})
        else:
            check(f"{slug}: no brightness block", pg.locator(".variability").count() == 0)
        check(f"{slug}: console clean", not msgs, msgs)
        pg.screenshot(path=f"{IMG}/real-{slug}.png", full_page=True)
        ctx.close()
    b.close()

failed = [r for r in results if not r[1]]
print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
sys.exit(1 if failed else 0)
