"""Project-page images and the social preview, taken from the running site at 2x.

Serve web/ (python3 -m http.server 8765 --directory web), then:
  uv run --with playwright python web/tools/make_page_images.py <base url> <out dir> [--social web/social.png]

Writes 01-..06-*.png and captions.md into <out dir>. Every picture is a screenshot of a real
page with real data; nothing is drawn by hand. Reduced motion is on, so each view rests on its
newest SPHEREx image. Set CHROMIUM to a browser binary to skip Playwright's own download.
"""
import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

EXE = os.environ.get("CHROMIUM") or None
BASE, OUT = sys.argv[1].rstrip("/") + "/", Path(sys.argv[2])
SOCIAL = Path(sys.argv[sys.argv.index("--social") + 1]) if "--social" in sys.argv else OUT / "social.png"

# name, path, viewport (w, h), what to capture ("fold" or a CSS selector), caption
SHOTS = [
    ("01-check-on-one-screen", "?target=2mass-0415-0935", (1440, 1500), "fold",
     "One screen, one answer: 16 years of WISE and SPHEREx images of 2MASS J0415-0935, its measured motion beside the catalogue's, and the type read from its SPHEREx spectrum beside the published one."),
    ("02-spectrum-and-verdict", "?target=2mass-0415-0935", (1000, 1100), "#spectrum",
     "The SPHEREx spectrum of 2MASS J0415-0935 with the best brown-dwarf template over it: dark where methane and water absorb, bright near 4 microns, typed T7 to T9 against a published T8."),
    ("03-unclassified", "?target=wise-0855-0714", (1440, 1400), "fold",
     "WISE 0855-0714: the motion agrees with the catalogue, but a star shares the SPHEREx pixel, so the spectrum is left unclassified and the page says why."),
    ("04-scoreboard", "validation.html", (1440, 900), "fold",
     "Every check against published values, failures included: the scoreboard is computed from the same data file as the tables under it."),
    ("05-planet-x-reach", "planetx.html", (1440, 900), ".px-plot-card",
     "Could SPHEREx see Planet X? Predicted brightness of each hypothetical planet against distance, with the depth of each survey: at 400 to 800 au it falls below one SPHEREx map."),
    ("06-haumea-ice", "?target=haumea", (1440, 1500), "fold",
     "Ephemerix also follows a Solar System body along its orbit: Haumea, 50 au away, with the water-ice bands in its reflected sunlight measured band by band."),
]

# The social card is the landing hero with everything but the question, the name and the blink hidden.
SOCIAL_CSS = """
  header.site nav, .tagline, .check-form, .hero-note, .hero-caption, .hero-visual > .btn, .hero-play, .hero-target,
  .scorestrip, .start, section[aria-labelledby=gallery-h], footer.site, .skip { display: none !important; }
  header.site { border: 0; padding: 44px 64px 0; max-width: none; min-height: 0; }
  .wordmark { font-size: 34px; } .brand-mark { width: 38px; height: 38px; }
  main { padding: 28px 64px 0; max-width: none; }
  .hero { grid-template-columns: minmax(0, 1fr) 372px; gap: 56px; padding: 0; align-items: center; }
  .hero h1 { font-size: 68px; max-width: 11ch; margin: 0 0 22px; }
  .lede { font-size: 21px; line-height: 1.45; max-width: 30rem; margin: 0; }
  .hero-eyebrow { font-size: 13px; margin-bottom: 14px; }
"""


def settle(pg, sel=None):
    pg.wait_for_load_state("networkidle")
    if sel:
        pg.wait_for_selector(sel, timeout=20000)
    pg.evaluate("document.fonts.ready")
    pg.wait_for_timeout(1500)


with sync_playwright() as p:
    b = p.chromium.launch(executable_path=EXE)
    OUT.mkdir(parents=True, exist_ok=True)
    lines = ["# Project-page images", "", "Screenshots of the site at 2x, made by `web/tools/make_page_images.py`. One caption each.", ""]
    for name, path, (w, h), what, caption in SHOTS:
        ctx = b.new_context(viewport={"width": w, "height": h}, device_scale_factor=2, reduced_motion="reduce")
        pg = ctx.new_page()
        pg.goto(BASE + path)
        settle(pg, ".spec-plot .main-svg, .px-plot .main-svg, .val-summary")
        file = OUT / f"{name}.png"
        if what == "fold":
            pg.screenshot(path=str(file))
        else:
            loc = pg.locator(what).first
            loc.scroll_into_view_if_needed()
            pg.wait_for_timeout(400)
            loc.screenshot(path=str(file))
        lines += [f"- `{name}.png`: {caption}"]
        print(f"wrote {file} ({file.stat().st_size // 1024} kB)")
        ctx.close()

    ctx = b.new_context(viewport={"width": 1200, "height": 630}, device_scale_factor=1, reduced_motion="reduce")
    pg = ctx.new_page()
    pg.goto(BASE)
    settle(pg, ".hero-readout")
    pg.add_style_tag(content=SOCIAL_CSS)
    pg.wait_for_timeout(600)
    SOCIAL.parent.mkdir(parents=True, exist_ok=True)
    pg.screenshot(path=str(SOCIAL), clip={"x": 0, "y": 0, "width": 1200, "height": 630})
    lines += [f"- `{SOCIAL.name}` (1200 x 630, the link preview): the question Ephemerix answers, with the blink of 2MASS J0415-0935 and its two answers beside the published ones."]
    print(f"wrote {SOCIAL} ({SOCIAL.stat().st_size // 1024} kB)")
    ctx.close()
    b.close()
    (OUT / "captions.md").write_text("\n".join(lines) + "\n")
