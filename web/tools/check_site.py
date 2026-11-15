"""Headless checks of the web frontend against the synthetic fixtures.

Serve web/ first (python3 -m http.server 8765 --directory web), then:
  uv run --with playwright python web/tools/check_site.py docs/validation/img
Set CHROMIUM to a browser binary to skip Playwright's own download.

The synthetic fixtures live in web/tests/fixtures/gallery/, which is not served. Every page
here gets a Playwright route that answers requests under /gallery/ from that folder, so the
site code never knows about fixtures and web/gallery/ can hold the real gallery.
"""
import json
import math
import os
import re
import sys
import urllib.parse
from pathlib import Path

from playwright.sync_api import sync_playwright

EXE = os.environ.get("CHROMIUM") or None
WEB = Path(__file__).resolve().parent.parent
FIX = WEB / "tests" / "fixtures" / "gallery"
BASE = os.environ.get("SITE_BASE", "http://localhost:8765/")  # another port if 8765 is taken
IMG = sys.argv[1]
results = []


def check(name, ok, info=""):
    results.append((name, bool(ok), info))


def hammer_chart(ra, dec):
    """Independent Hammer-Aitoff (RA 12h in the middle, RA increasing to the left): unit-free x right, y up."""
    lon = math.radians((ra % 360) - 180)
    p = math.radians(dec)
    den = math.sqrt(1 + math.cos(p) * math.cos(lon / 2))
    return -2 * math.sqrt(2) * math.cos(p) * math.sin(lon / 2) / den, math.sqrt(2) * math.sin(p) / den


def fixture_gallery(route):
    """Answer a request under /gallery/ from the fixture folder (404 outside it)."""
    rel = urllib.parse.unquote(urllib.parse.urlparse(route.request.url).path).split("/gallery/", 1)[-1]
    path = (FIX / rel).resolve()
    if FIX.resolve() in path.parents and path.is_file():
        route.fulfill(path=str(path))
    else:
        route.fulfill(status=404, body="not found")


# Zoom, the image-set toggles and the overlays sit under "More controls", closed by default.
# Most checks drive them, so the disclosure is opened as soon as it is drawn; `more=False`
# leaves it alone for the check that it starts closed and opens on a click.
OPEN_MORE_JS = """new MutationObserver(() => { const d = document.querySelector('details.more-controls:not([data-opened])');
  if (d) { d.open = true; d.dataset.opened = '1'; } }).observe(document, { childList: true, subtree: true });"""


def page(b, w=1280, h=900, reduced=False, perms=False, fixtures=True, more=True, hint=False):
    ctx = b.new_context(viewport={"width": w, "height": h}, device_scale_factor=2 if w < 600 else 1,
                        reduced_motion="reduce" if reduced else "no-preference")
    if not hint:  # the one-time Simple hint (js/mode.js) is checked on its own page; elsewhere it is already seen
        ctx.add_init_script("try { localStorage.setItem('ephemerix-mode-hint', '1'); } catch (e) {}")
    if more:
        ctx.add_init_script(OPEN_MORE_JS)
    if perms:
        ctx.grant_permissions(["clipboard-read", "clipboard-write"], origin=BASE.rstrip("/"))
    # The deployed config points at the live service; these checks run against a gallery-only site.
    ctx.route("**/js/config.js", lambda r: r.fulfill(body="export const API_BASE = '';\nexport const LIVE_TIMEOUT_MS = 150000;\n", content_type="text/javascript"))
    if fixtures:
        ctx.route("**/gallery/**", fixture_gallery)
    # Archive uptime (js/archivestatus.js): no status unless a check stubs one, and no 404 noise.
    ctx.route("**/api/archives", lambda r: r.fulfill(body="{}", content_type="application/json"))
    pg = ctx.new_page()
    pg.msgs = []
    pg.on("console", lambda m: pg.msgs.append(f"{m.type}: {m.text}") if m.type in ("error", "warning") else None)
    pg.on("pageerror", lambda e: pg.msgs.append(f"pageerror: {e}"))
    return pg


ALIGN_JS = """async () => {
  const m = await (await fetch('gallery/synthetic-fast-mover/manifest.json')).json();
  const out = [];
  for (const f of m.frames.filter(f => f.band === 'W2')) {
    const img = new Image(); img.src = 'gallery/synthetic-fast-mover/' + f.image; await img.decode();
    const c = document.createElement('canvas'); c.width = img.width; c.height = img.height;
    const g = c.getContext('2d'); g.drawImage(img, 0, 0);
    const d = g.getImageData(0, 0, c.width, c.height).data;
    const [px, py] = f.predicted_px; let best = 0, bx = 0, by = 0;
    for (let y = Math.floor(py) - 6; y <= Math.floor(py) + 6; y++) for (let x = Math.floor(px) - 6; x <= Math.floor(px) + 6; x++) {
      const w = Math.max(0, d[(y * c.width + x) * 4] - 150); best += w; bx += w * (x + 0.5); by += w * (y + 0.5); }
    out.push(Math.hypot(bx / best - px, by / best - py));
  }
  return out;
}"""

with sync_playwright() as p:
    b = p.chromium.launch(executable_path=EXE)

    # 1. Landing
    pg = page(b)
    pg.goto(BASE, wait_until="networkidle")
    pg.wait_for_selector(".hero-stage canvas", timeout=10000)
    pg.wait_for_timeout(1500)
    check("landing: gallery cards", pg.locator(".target-card").count() == 3)
    check("landing: brief group first", "brief" in pg.locator(".group-h").first.inner_text().lower(), pg.locator(".group-h").all_inner_texts())
    check("landing: every card says what the tool made of it, or why not", pg.locator(".target-card .types:not([hidden])").count() == 3, pg.locator(".target-card .types").all_inner_texts())
    types_text = " | ".join(pg.locator(".target-card .types").all_inner_texts())
    check("landing: no type call gives its reason in a few words", "no type: too faint to classify" in types_text and "no type: no usable spectrum" in types_text, types_text)
    check("landing: one-type tool result shown as approximate", "Ephemerix about Y0" in " ".join(pg.inner_text(".target-card .types").split()), pg.inner_text(".target-card .types"))
    check("landing: leads with the question, and the first paragraph names WISE and SPHEREx", pg.inner_text("#hero-h").startswith("Is that dot moving") and "SPHEREx" in pg.inner_text(".lede") and "WISE" in pg.inner_text(".lede"))
    check("landing: the check box is in the hero, one line", pg.locator(".hero #pos").is_visible() and pg.locator(".hero .search button[type=submit]").is_visible())
    check("landing: hero playing", pg.get_attribute(".hero-play", "aria-label") == "Pause the blink")
    check("landing: caption computed", "moved" in pg.inner_text(".hero-caption"), pg.inner_text(".hero-caption"))
    pg.screenshot(path=f"{IMG}/web-landing-desktop.png")
    check("landing: console clean", not pg.msgs, pg.msgs)

    # 2. Overlay alignment on the source images
    d = pg.evaluate(ALIGN_JS)
    check("overlay: predicted_px within 0.5 px of the light-weighted centroid in every W2 frame", max(d) < 0.5, f"max {max(d):.2f} px over {len(d)} frames")

    # 3. Full view, URL round trip
    q = "?target=synthetic-fast-mover&frame=wise-w2-2019p40&bands=W2,spx-b6&spec=spx-2025b"
    pg = page(b, perms=True)
    pg.goto(BASE + q, wait_until="networkidle")
    pg.wait_for_selector(".spec-plot .main-svg", timeout=20000)
    pg.wait_for_timeout(800)
    check("view: URL unchanged after load", pg.evaluate("location.search") == q, pg.evaluate("location.search"))
    check("view: deep-linked frame shown, paused", "2019" in pg.get_attribute("canvas.stage", "aria-label")
          and pg.get_attribute(".controls .btn.primary", "aria-label") == "Play")
    check("view: spec epoch restored", pg.locator(".spec-controls .seg[aria-pressed=true]").inner_text() == "Nov 2025")
    check("view: band chips restored", pg.eval_on_selector_all(".chips input:checked", "e => e.map(x => x.value)") == ["W2", "spx-b6"])
    check("view: matching preset shown pressed", pg.get_attribute("[data-preset=wise-spherex]", "aria-pressed") == "true")
    check("view: frame warnings shown", "partial coverage" in pg.inner_text(".frame-warnings").lower())
    check("flags: badge on the flagged frame", pg.locator(".flag-badge").is_visible() and "3 notes" in pg.inner_text(".flag-badge") and "18% of the pixels" in pg.eval_on_selector(".flag-tip", "e => e.textContent"), pg.inner_text(".stage-wrap"))
    check("labels: no raw band ids on the page", "spx-b" not in pg.inner_text("body"))
    check("labels: sets named from mission and wavelength", "SPHEREx 4.42–5.0 µm" in pg.inner_text(".chips") and "WISE W2 (4.6 µm)" in pg.inner_text(".chips"))
    check("vetting: W1-W2 and H_W2 sit behind 'More evidence', closed by default", pg.get_attribute(".more-evidence", "open") is None and "w1−w2 colour" not in pg.inner_text(".motion").lower())
    pg.click(".more-evidence summary")
    pg.evaluate("document.activeElement.blur()")  # the key checks below press keys on the page, not on the disclosure
    check("vetting: W1-W2 and H_W2 in the motion panel", "w1−w2 colour" in pg.inner_text(".motion").lower() and "h_w2" in pg.inner_text(".motion").lower())
    check("timeline: gap in the selected sets shaded and labelled", pg.locator(".tl-gap").count() == 1 and "no images 2011" in pg.inner_text(".tl-gap"), pg.locator(".tl-gap").all_inner_texts())
    links = pg.eval_on_selector_all(".links a", "e => e.map(a => [a.href, a.target, a.rel])")
    check("links: three link-outs, new tab, noopener noreferrer", len(links) == 3 and all(t == "_blank" and r == "noopener noreferrer" for _, t, r in links), links)
    check("band strip: six bands of one pass", pg.locator(".strip-cell").count() == 6)
    check("view: spectrum traces", pg.evaluate("document.querySelector('.spec-plot').data.length") >= 3)
    check("view: motion agrees", "they agree" in pg.inner_text(".motion-headline"), pg.inner_text(".motion"))
    pg.screenshot(path=f"{IMG}/web-view-desktop.png", full_page=True)
    pg.locator("body").press("ArrowRight")
    pg.wait_for_timeout(500)
    s = pg.evaluate("location.search")
    check("keys: arrow steps and writes frame to URL", "frame=wise-w2-2020p40" in s, s)
    pg.locator("body").press(" ")
    pg.wait_for_timeout(200)
    check("keys: space plays", pg.get_attribute(".controls .btn.primary", "aria-label") == "Pause")
    pg.locator("body").press(" ")
    pg.locator("#spec-log").check()
    pg.wait_for_timeout(300)
    check("spectrum: log toggle", pg.evaluate("document.querySelector('.spec-plot').layout.yaxis.type") == "log")
    pg.get_by_role("button", name="Copy summary for Talk").first.click()
    pg.wait_for_timeout(300)
    clip = pg.evaluate("navigator.clipboard.readText()")
    check("summary: copied text", clip.startswith("Candidate check: SYNTHETIC") and "View: http" in clip, clip[:80])
    check("summary: vetting numbers included", "W1−W2 colour: 3.30" in clip and "H_W2" in clip, clip)
    pg.get_by_role("button", name="Embed").click()
    snippet = pg.input_value(".dialog textarea")
    check("embed: snippet has embed=1", "embed=1" in snippet and snippet.startswith("<iframe"), snippet[:90])
    pg.keyboard.press("Escape")
    pg.mouse.move(*[v + 200 for v in (pg.locator("canvas.stage").bounding_box()["x"], pg.locator("canvas.stage").bounding_box()["y"])])
    pg.wait_for_timeout(100)
    check("crosshair: RA/Dec readout", pg.inner_text(".readout").startswith("RA 10 00"), pg.inner_text(".readout"))
    check("view: console clean", not pg.msgs, pg.msgs)

    # 4b. Presets: SPHEREx only is one click from the default, and reachable by URL
    pg = page(b)
    pg.goto(BASE + "?mode=full&target=synthetic-fast-mover", wait_until="networkidle")
    pg.wait_for_selector("canvas.stage")
    check("preset: default is WISE + SPHEREx at 4.6 µm", pg.eval_on_selector_all(".chips input:checked", "e => e.map(x => x.value)") == ["W2", "spx-b6"])
    pg.get_by_role("button", name="SPHEREx only").click()
    pg.wait_for_timeout(400)
    check("preset: SPHEREx only in one click", pg.eval_on_selector_all(".chips input:checked", "e => e.map(x => x.value)") == ["spx-b6"]
          and "preset=spherex" in pg.evaluate("location.search"), pg.evaluate("location.search"))
    pg.get_by_role("button", name="All SPHEREx bands").click()
    pg.wait_for_timeout(400)
    check("preset: all SPHEREx bands", len(pg.eval_on_selector_all(".chips input:checked", "e => e.map(x => x.value)")) == 6)
    pg.goto(BASE + "?mode=full&target=synthetic-fast-mover&preset=spherex", wait_until="networkidle")
    pg.wait_for_selector("canvas.stage")
    check("preset: SPHEREx only by URL", pg.eval_on_selector_all(".chips input:checked", "e => e.map(x => x.value)") == ["spx-b6"])
    # Band strip: click the methane band, the player jumps to it
    pg.locator(".strip-cell", has_text="1.65–2.42").click()
    pg.wait_for_timeout(500)
    s = pg.evaluate("location.search")
    check("band strip: click jumps the player to that band", "bands=spx-b3" in s and "frame=spherex-spx-b3" in s
          and "SPHEREx 1.65–2.42 µm" in pg.get_attribute("canvas.stage", "aria-label"), s)
    check("band strip: methane band shows the object undetected", "not found" in pg.locator(".strip-cell", has_text="1.65–2.42").inner_text())
    check("presets/strip: console clean", not pg.msgs, pg.msgs)

    # 4c. Difference and sum
    q = "?target=synthetic-fast-mover&cmp=diff&a=wise-w2-2010p37&b=wise-w2-2024p40"
    pg = page(b)
    pg.goto(BASE + q, wait_until="networkidle")
    pg.wait_for_selector(".cmp-panel:not([hidden])")
    pg.wait_for_timeout(500)
    check("diff: URL state restored and kept", pg.evaluate("location.search") == q, pg.evaluate("location.search"))
    check("diff: labelled as display difference", "B − A" in pg.inner_text(".cmp-msg") and "not photometry" in pg.inner_text(".compare-box"))
    check("diff: blink paused", pg.get_attribute(".controls .btn.primary", "aria-label") == "Play")
    MID = """() => { const c = document.querySelector('canvas.stage'); const g = c.getContext('2d');
      const d = g.getImageData(Math.round(c.width * 0.85), Math.round(c.height * 0.55), 6, 6).data; let s = 0;
      for (let i = 0; i < d.length; i += 4) s += d[i]; return s / (d.length / 4); }"""
    bg = pg.evaluate(MID)
    check("diff: background cancels to mid-grey", 100 < bg < 156, bg)
    pg.set_viewport_size({"width": 1280, "height": 1500})
    pg.wait_for_timeout(300)
    pg.screenshot(path=f"{IMG}/web-difference.png", full_page=False)
    pg.locator("body").press("ArrowRight")
    pg.wait_for_timeout(400)
    check("diff: arrow keys leave the comparison alone", "a=wise-w2-2010p37" in pg.evaluate("location.search"))
    pg.get_by_role("button", name="A plus B").click()
    pg.wait_for_timeout(400)
    check("sum: mode in URL", "cmp=sum" in pg.evaluate("location.search"))
    pg.select_option("#cmp-b", "spherex-spx-b6-2025p39")
    pg.wait_for_timeout(300)
    check("diff: different sets refused with a reason", "same set" in pg.inner_text(".cmp-msg") and "stretch" in pg.inner_text(".cmp-msg"), pg.inner_text(".cmp-msg"))
    pg.get_by_role("button", name="Back to the blink").click()
    pg.wait_for_timeout(400)
    check("diff: leaving clears the URL", "cmp=" not in pg.evaluate("location.search"))
    check("diff: console clean", not pg.msgs, pg.msgs)

    # 4d. Match null with a reason, no proper motion, partial vetting
    pg = page(b)
    pg.goto(BASE + "?mode=full&target=synthetic-faint", wait_until="networkidle")
    pg.wait_for_selector(".spec-plot .main-svg", timeout=20000)
    v = pg.inner_text(".spectrum .verdict")
    check("no match: reason from warnings in the verdict", "too faint to classify" in v, v)
    check("no match: calm style", "conf-low" not in pg.get_attribute(".spectrum .verdict", "class"))
    check("no match: points still plotted", pg.evaluate("document.querySelector('.spec-plot').data.length") >= 1)
    check("spectrum: flagged points counted with reason", "4 of 97 points were flagged" in pg.inner_text(".flag-note") and "cosmic" in pg.inner_text(".flag-note"), pg.inner_text(".flag-note"))
    check("no pm: notice shown", "No proper motion was given" in pg.inner_text(".motion"))
    check("no pm: without the live server, the reason replaces the button", pg.locator(".notice a").count() == 0 and "needs the live server" in pg.inner_text(".notice"))
    check("vetting: partial block hidden", "w1−w2" not in pg.inner_text(".motion").lower())
    check("faint: console clean", not pg.msgs, pg.msgs)

    # 4e. Match extras (optional fields), served as a modified fixture
    import json as _j
    base_m = _j.loads((FIX / "synthetic-fast-mover/manifest.json").read_text())

    def variant(match_patch):
        m2 = _j.loads(_j.dumps(base_m))
        m2["match"].update(match_patch)
        return _j.dumps(m2)
    pg = page(b)
    pg.route("**/synthetic-fast-mover/manifest.json", lambda r: r.fulfill(body=variant(
        {"type_range": ["Y1", "Y1"], "range_open_cold": True, "pair": None}),
        content_type="application/json"))
    pg.goto(BASE + "?mode=full&target=synthetic-fast-mover", wait_until="networkidle")
    pg.wait_for_selector(".spectrum .verdict")
    v = pg.inner_text(".spectrum .verdict")
    check("match: open cold end shown as 'Y1 or colder'", "Y1 or colder" in v, v)
    pg = page(b)
    pg.route("**/synthetic-fast-mover/manifest.json", lambda r: r.fulfill(body=variant(
        {"type_range": ["T1", "T3"], "pair": {"types": ["T1", "T6"], "chi2": 80, "delta_vs_single": 25.5}}), content_type="application/json"))
    pg.goto(BASE + "?mode=full&target=synthetic-fast-mover", wait_until="networkidle")
    pg.wait_for_selector(".spectrum .verdict")
    v = pg.inner_text(".spectrum .verdict")
    check("match: blended pair line", "two blended brown dwarfs, about T1 and T6" in v, v)
    check("match: a pair is not contradicted by a single-type range", "Likely type" not in v, v)
    check("match: confidence words describe the class", "Class: brown dwarf" in v and ("class call" in v or "unlike an ordinary star" in v), v)
    pg = page(b)
    pg.route("**/synthetic-fast-mover/manifest.json", lambda r: r.fulfill(body=variant(
        {"class": "not a brown dwarf", "type_range": ["M8", "M8"], "range_open_warm": True}), content_type="application/json"))
    pg.goto(BASE + "?mode=full&target=synthetic-fast-mover", wait_until="networkidle")
    pg.wait_for_selector(".spectrum .verdict")
    v = pg.inner_text(".spectrum .verdict")
    check("match: not-a-brown-dwarf class, no type range", "not a brown dwarf" in v and "Likely type" not in v, v)
    pg = page(b)
    pg.route("**/synthetic-fast-mover/manifest.json", lambda r: r.fulfill(body=variant(
        {"class": "uncertain", "confidence": "high", "type_range": ["T7", "T9"]}), content_type="application/json"))
    pg.goto(BASE + "?mode=full&target=synthetic-fast-mover", wait_until="networkidle")
    pg.wait_for_selector(".spectrum .verdict")
    v = pg.inner_text(".spectrum .verdict")
    check("match: uncertain class shows no type range and no class-confidence words", "uncertain" in v and "Likely type" not in v and "class call is clear" not in v, v)
    check("match extras: console clean", not pg.msgs, pg.msgs)

    # 4f. Phone width with the strip and compare open
    pg = page(b, 390, 844)
    pg.goto(BASE + "?mode=full&target=synthetic-fast-mover&cmp=diff", wait_until="networkidle")
    pg.wait_for_selector(".cmp-panel:not([hidden])")
    pg.wait_for_timeout(500)
    check("phone: no horizontal scroll (compare + strip)", pg.evaluate("document.documentElement.scrollWidth <= innerWidth"))
    check("phone compare: console clean", not pg.msgs, pg.msgs)

    # 4. Null cases on a phone
    pg = page(b, 390, 844)
    pg.goto(BASE + "?mode=full&target=synthetic-no-motion", wait_until="networkidle")
    pg.wait_for_selector("canvas.stage")
    pg.wait_for_timeout(500)
    check("null: no spectrum message", "No usable spectrum" in pg.inner_text(".spectrum"))
    check("null: motion not measured", "Not measured" in pg.inner_text(".motion"))
    check("null: track disabled", pg.locator(".layers input").first.is_disabled())
    check("phone: no horizontal scroll (null view)", pg.evaluate("document.documentElement.scrollWidth <= innerWidth"))
    check("null: console clean", not pg.msgs, pg.msgs)

    pg = page(b, 390, 844)
    pg.goto(BASE + "?mode=full&target=synthetic-fast-mover&frame=wise-w1-2010p87&bands=W1,W2", wait_until="networkidle")
    pg.wait_for_selector(".spec-plot .main-svg", timeout=20000)
    pg.wait_for_timeout(500)
    check("null centroid frame: 'not detected'", "not detected" in pg.inner_text(".facts"))
    check("phone: no horizontal scroll (view)", pg.evaluate("document.documentElement.scrollWidth <= innerWidth"))
    pg.locator(".stage-wrap").scroll_into_view_if_needed()
    pg.wait_for_timeout(300)
    pg.screenshot(path=f"{IMG}/web-view-phone.png")
    pg.locator(".band-strip").scroll_into_view_if_needed()
    pg.wait_for_timeout(300)
    pg.screenshot(path=f"{IMG}/web-strip-phone.png")
    check("phone view: console clean", not pg.msgs, pg.msgs)

    pg = page(b, 390, 844, reduced=True)
    pg.goto(BASE, wait_until="networkidle")
    pg.wait_for_selector(".hero-play")
    pg.wait_for_timeout(500)
    check("reduced motion: hero not autoplaying", pg.get_attribute(".hero-play", "aria-label") == "Play the blink")
    check("phone: no horizontal scroll (landing)", pg.evaluate("document.documentElement.scrollWidth <= innerWidth"))
    pg.screenshot(path=f"{IMG}/web-landing-phone.png")
    check("reduced landing: console clean", not pg.msgs, pg.msgs)

    # 5. Embed, errors, search
    pg = page(b)
    pg.goto(BASE + "?mode=full&target=synthetic-fast-mover&embed=1", wait_until="networkidle")
    pg.wait_for_selector("canvas.stage")
    check("embed: chrome hidden", not pg.locator("header.site").is_visible() and not pg.locator(".actions").is_visible())
    check("embed: the view only, without the 'Check the data' cards", not pg.locator(".trust-grid").is_visible() and pg.locator(".verdict-strip").is_visible() and pg.locator("#spectrum").is_visible())
    pg.goto(BASE + "?mode=full&target=nope", wait_until="networkidle")
    pg.wait_for_selector(".status.error")
    check("bad target: clear error", "not found" in pg.inner_text(".status.error"))
    pg.msgs.clear()
    pg.goto(BASE + "?mode=full&ra=133.78&dec=-7.24", wait_until="networkidle")
    pg.wait_for_selector("#pos")
    check("position without API: notice + prefill", "no live server" in pg.inner_text(".landing") and pg.input_value("#pos") == "133.78 -7.24")
    pg.fill("#pos", "25 00 00 +10 00 00")
    pg.click(".search button[type=submit]")
    check("search: validation message", "RA is out of range" in pg.inner_text(".form-msg"), pg.inner_text(".form-msg"))
    pg.fill("#pos", "08 55 10.83 -07 14 42.5")
    pg.click(".search button[type=submit]")
    check("search: parsed, gallery-only explained", "Read as RA 08 55 10.83" in pg.inner_text(".form-msg"))
    check("search/landing: console clean", not pg.msgs, pg.msgs)
    # 6. History writes stay few under scrubbing and key repeat
    pg = page(b)
    pg.add_init_script("""(() => { const o = history.replaceState.bind(history); window.__rs = 0;
      history.replaceState = (...a) => { window.__rs++; return o(...a); }; })()""")
    pg.goto(BASE + "?mode=full&target=synthetic-fast-mover&frame=wise-w2-2010p37", wait_until="networkidle")
    pg.wait_for_selector(".timeline")
    box = pg.locator(".timeline").bounding_box()
    pg.mouse.move(box["x"] + 5, box["y"] + box["height"] / 2)
    pg.mouse.down()
    for i in range(50):
        pg.mouse.move(box["x"] + 5 + i * (box["width"] - 10) / 50, box["y"] + box["height"] / 2)
        pg.wait_for_timeout(15)
    pg.mouse.up()
    pg.locator("body").focus()
    for _ in range(60):
        pg.keyboard.press("ArrowRight")
        pg.wait_for_timeout(30)
    pg.wait_for_timeout(500)
    n = pg.evaluate("window.__rs")
    check("history: few replaceState calls when scrubbing and key-repeating", n <= 10, n)
    check("history: console clean", not pg.msgs, pg.msgs)

    # 7. A missing image
    pg = page(b)
    pg.route("**/wise-w2-2019p40.png", lambda r: r.abort())
    pg.goto(BASE + "?mode=full&target=synthetic-fast-mover&frame=wise-w2-2019p40", wait_until="networkidle")
    pg.wait_for_selector("canvas.stage")
    check("missing image: notes report it", "1 image(s) could not be loaded" in pg.inner_text(".notes-lines") and "1 image(s) could not be loaded" in pg.text_content(".notes"), pg.text_content(".notes"))
    check("missing image: view still renders", pg.locator(".spectrum").count() == 1)
    other = [m for m in pg.msgs if "Failed to load resource" not in m]
    check("missing image: no other console errors", not other, other)

    # 8. Live mode with a slow manifest
    cfg = f"export const API_BASE = '{BASE.rstrip('/')}';\nexport const LIVE_TIMEOUT_MS = 150000;\n"
    manifest = (FIX / "synthetic-fast-mover/manifest.json").read_text()
    pg = page(b)
    pg.route("**/js/config.js", lambda r: r.fulfill(body=cfg, content_type="text/javascript"))
    pg.route("**/api/view*", lambda r: None)  # hold forever
    pg.goto(BASE + "?mode=full&ra=150.0123&dec=20.0046", wait_until="domcontentloaded")
    pg.wait_for_selector("text=Working for")
    t1 = pg.inner_text(".status .muted")
    pg.wait_for_timeout(2200)
    t2 = pg.inner_text(".status .muted")
    check("live: elapsed counter advances", t1 != t2, f"{t1} -> {t2}")
    pg.click("text=Cancel")
    pg.wait_for_selector(".status.error")
    check("live: cancel shows message", "cancelled" in pg.inner_text(".status.error"))
    pg2 = page(b)
    pg2.route("**/js/config.js", lambda r: r.fulfill(body=cfg, content_type="text/javascript"))
    pg2.route("**/api/view*", lambda r: r.fulfill(body=manifest, content_type="application/json"))
    def frames(r):
        name = r.request.url.split("/api/frames/")[-1]
        r.fulfill(path=FIX / "synthetic-fast-mover/frames" / name)
    pg2.route("**/api/frames/**", frames)
    pg2.goto(BASE + "?mode=full&ra=150.0123&dec=20.0046", wait_until="networkidle")
    pg2.wait_for_selector("canvas.stage", timeout=10000)
    pg2.wait_for_timeout(500)
    check("live: view renders, images resolve against response URL", "could not be loaded" not in pg2.inner_text("main") and pg2.locator(".eyebrow").inner_text().lower() == "position search")
    check("live: console clean", not pg2.msgs, pg2.msgs)
    check("live: the all-sky locator renders with a context line", pg2.locator(".locator-map").is_visible() and "arcminutes across" in pg2.inner_text(".locator-context"), pg2.inner_text(".locator-context"))

    # 9. Live mode with a build job: 202, stage progress, then the finished manifest
    import json as _json
    statuses = [
        {"state": "running", "stage": "Searching WISE frames", "progress": 0.1},
        {"state": "running", "stage": "Reading WISE images (5 of 16)", "progress": 0.35},
        {"state": "running", "stage": "Reading WISE images (5 of 16)", "progress": 0.35},
        {"state": "done", "progress": 1, "manifest_url": "/gallery/synthetic-fast-mover/manifest.json"},
    ]
    def job(r):
        r.fulfill(body=_json.dumps(statuses.pop(0) if len(statuses) > 1 else statuses[0]),
                  content_type="application/json")
    pg3 = page(b)
    pg3.route("**/js/config.js", lambda r: r.fulfill(body=cfg, content_type="text/javascript"))
    pg3.route("**/api/view*", lambda r: r.fulfill(status=202, content_type="application/json",
                                                  body='{"job": "j1", "status_url": "/api/jobs/j1"}'))
    pg3.route("**/api/jobs/j1", job)
    pg3.goto(BASE + "?mode=full&ra=150.0123&dec=20.0046", wait_until="domcontentloaded")
    pg3.wait_for_selector("text=Reading WISE images (5 of 16)", timeout=10000)
    check("live job: stage text shown", "Reading WISE images" in pg3.inner_text(".live-stage"))
    check("live job: progress bar advances", abs(pg3.eval_on_selector(".live-progress", "e => e.value") - 0.35) < 1e-6)
    check("live job: cancel offered", pg3.locator("text=Cancel").count() == 1)
    pg3.wait_for_selector("canvas.stage", timeout=15000)
    pg3.wait_for_timeout(500)
    check("live job: finished view renders", "could not be loaded" not in pg3.inner_text("main"))
    check("live job: console clean", not pg3.msgs, pg3.msgs)

    # 10. Live mode refused (rate limit): message with the wait, search form kept and filled
    pg4 = page(b)
    pg4.route("**/js/config.js", lambda r: r.fulfill(body=cfg, content_type="text/javascript"))
    pg4.route("**/api/view*", lambda r: r.fulfill(status=429, headers={"Retry-After": "120"}, content_type="application/json",
                                                  body='{"error": "You have started many new views recently.", "retry_after_s": 120}'))
    pg4.goto(BASE + "?mode=full&ra=150.0123&dec=20.0046", wait_until="networkidle")
    pg4.wait_for_selector("#pos")
    check("live 429: wait time shown", "Try again in about 120 s" in pg4.inner_text(".banner"), pg4.inner_text("main")[:200])
    check("live 429: form kept and prefilled", pg4.input_value("#pos") == "150.0123 20.0046")
    other = [m for m in pg4.msgs if "429" not in m]
    check("live 429: no other console errors", not other, other)

    # 11. Name search: no live server, a miss, a network failure, a hit (mocked /api/resolve)
    pg5 = page(b)
    pg5.goto(BASE + "#search", wait_until="networkidle")
    pg5.fill("#pos", "WISE 0855-0714")
    pg5.click(".search button[type=submit]")
    pg5.wait_for_timeout(200)
    check("name: without the live server, a clear message", "needs the live server" in pg5.inner_text(".form-msg"), pg5.inner_text(".form-msg"))
    pg5 = page(b)
    pg5.route("**/js/config.js", lambda r: r.fulfill(body=cfg, content_type="text/javascript"))
    answers = [
        lambda r: r.fulfill(content_type="application/json", body='{"resolved": false, "message": "Could not resolve that name. Enter the coordinates instead."}'),
        lambda r: r.abort(),
        lambda r: r.fulfill(content_type="application/json", body='{"resolved": true, "name": "WISE J085510.83-071442.5", "ra": 133.7862, "dec": -7.2453, "epoch": 2000.0, "pmra": -8123.7, "pmdec": 673.2, "source": "CDS Sesame"}'),
    ]
    pg5.route("**/api/resolve*", lambda r: answers.pop(0)(r))
    pg5.goto(BASE + "#search", wait_until="networkidle")
    pg5.fill("#pos", "No such object 123")
    pg5.click(".search button[type=submit]")
    pg5.wait_for_selector(".form-msg:has-text('Could not resolve')", timeout=5000)
    check("name: miss fails soft", "Could not resolve" in pg5.inner_text(".form-msg"))
    pg5.click(".search button[type=submit]")
    pg5.wait_for_selector(".form-msg:has-text('could not be reached')", timeout=5000)
    check("name: network failure fails soft", "could not be reached" in pg5.inner_text(".form-msg"))
    # A name outside the offline index (data/names.json) still goes to the live name service.
    pg5.fill("#pos", "Teide 1")
    pg5.click(".search button[type=submit]")
    pg5.wait_for_selector(".form-msg:has-text('via CDS Sesame')", timeout=5000)
    check("name: hit fills position and motion, names the service",
          pg5.input_value("#pos") == "133.7862 -7.2453" and pg5.input_value("#pmra") == "-8123.7" and pg5.input_value("#epoch") == "2000"
          and "via CDS Sesame" in pg5.inner_text(".form-msg"), pg5.inner_text(".form-msg"))
    other = [m for m in pg5.msgs if "ERR_FAILED" not in m and "Failed to load resource" not in m]
    check("name: no other console errors", not other, other)

    # 12. "Use this motion" with a live server: a position link with the measured motion
    pg6 = page(b)
    pg6.route("**/js/config.js", lambda r: r.fulfill(body=cfg, content_type="text/javascript"))
    pg6.goto(BASE + "?mode=full&target=synthetic-faint", wait_until="networkidle")
    pg6.wait_for_selector(".notice a")
    h = pg6.get_attribute(".notice a", "href")
    check("no pm: 'Use this motion' links to the position with the measured motion",
          "ra=45.25" in h and "pmra=970.4" in h and "pmdec=-1436.4" in h and "target=" not in h, h)
    check("use motion: console clean", not pg6.msgs, pg6.msgs)

    # 13. Gallery: the shipped (real) gallery is separate from the fixtures
    EMPTY = '{"schema": 1, "targets": []}'
    pg7 = page(b, fixtures=False)
    pg7.route("**/gallery/index.json", lambda r: r.fulfill(body=EMPTY, content_type="application/json"))
    pg7.goto(BASE, wait_until="networkidle")
    pg7.wait_for_selector("#gallery-h")
    check("empty gallery: sensible empty state, no error", "No gallery targets built yet" in pg7.inner_text(".landing")
          and pg7.locator(".target-card").count() == 0 and "could not be loaded" not in pg7.inner_text("main"), pg7.inner_text(".landing")[-300:])
    check("empty gallery: search still offered", pg7.locator("#pos").count() == 1)
    check("empty gallery: console clean", not pg7.msgs, pg7.msgs)
    pg7 = page(b, fixtures=False)
    pg7.goto(BASE + "?mode=full&target=synthetic-fast-mover", wait_until="networkidle")
    pg7.wait_for_selector(".status.error")
    check("shipped gallery holds no fixture: a fixture slug is not found", "not found" in pg7.inner_text(".status.error"), pg7.inner_text(".status.error"))
    # The site has no gallery override: query parameters cannot redirect reads to another origin or path.
    hosts, paths = set(), []
    pg7 = page(b)
    pg7.on("request", lambda r: (hosts.add(urllib.parse.urlparse(r.url).netloc), paths.append(urllib.parse.urlparse(r.url).path)))
    for bad in ("https://evil.example/g/", "//evil.example/g/", "/tests/fixtures/gallery/", "../tests/fixtures/gallery/"):
        pg7.goto(BASE + "?gallery=" + urllib.parse.quote(bad, safe=""), wait_until="networkidle")
        pg7.wait_for_selector(".target-card")
    check("gallery override: absolute, protocol-relative and path values are ignored; only the site's own origin is contacted",
          hosts == {urllib.parse.urlparse(BASE).netloc} and not any(p.startswith("/g/") or "/tests/" in p for p in paths), (hosts, paths[:6]))

    # 14. Classifier display: details disclosure, pair once, confidence words, neutral classes, per-pass line
    def vpage(patch, url="?mode=full&target=synthetic-fast-mover"):
        pgx = page(b)
        pgx.route("**/synthetic-fast-mover/manifest.json", lambda r: r.fulfill(body=variant(patch), content_type="application/json"))
        pgx.goto(BASE + url, wait_until="networkidle")
        pgx.wait_for_selector(".spectrum .verdict")
        return pgx
    pg = vpage({"delta_chi2": 22.1, "delta_class": 1016.0, "bands_detected": ["H2O 1.4 um"]})
    check("match: no 'Δχ²' anywhere on the page", "Δχ²" not in pg.inner_text("body"), pg.inner_text(".spectrum .verdict"))
    check("match: raw numbers sit behind a closed 'Details' disclosure", pg.locator(".match-details").count() == 1
          and pg.get_attribute(".match-details", "open") is None and "score gap" not in pg.inner_text(".spectrum .verdict").lower())
    pg.click(".match-details summary")
    d = pg.text_content(".match-details")  # the labels are small capitals on screen
    check("match: details name the score gap and class gap as the docs define them",
          "Score gap" in d and "22.1" in d and "runner-up score minus best score" in d and "Class gap" in d and "1016" in d and "H2O 1.4 um" in d, d)
    pg.locator(".spectrum .verdict").screenshot(path=f"{IMG}/web-match-details.png")
    pg = vpage({"verdict": "Consistent with a blend of T1 and T6 brown dwarfs.", "pair": {"types": ["T1", "T6"], "chi2": 80, "delta_vs_single": 25.5}})
    check("match: a pair already named by the verdict is not repeated", pg.locator(".verdict-pair").count() == 0
          and pg.inner_text(".spectrum .verdict").count("T1") == 1, pg.inner_text(".spectrum .verdict"))
    pg = vpage({"confidence": "medium"})
    check("match: medium confidence also says no template may fit closely", "no template fits closely" in pg.inner_text(".spectrum .verdict"))
    for cls, conf in (("uncertain", "low"), ("not a brown dwarf", "low")):
        pg = vpage({"class": cls, "confidence": conf, "type_range": None})
        vc = pg.get_attribute(".spectrum .verdict", "class")
        bc = pg.get_attribute(".spectrum .badge", "class")
        border = pg.eval_on_selector(".spectrum .verdict", "e => getComputedStyle(e).borderLeftColor")
        check(f"match: class '{cls}' is neutral, not an error", "neutral" in vc and "conf-low" not in vc and "neutral" in bc and border != "rgb(255, 139, 122)", (vc, bc, border))
    pg = vpage({"per_pass": [{"id": f"p{i}", "label": f"Pass {i}", "class": "brown dwarf", "type": "T8"} for i in range(4)]})
    check("per-pass: agreement in one line", pg.inner_text(".verdict-passes") == "All 4 passes agree: T8", pg.inner_text(".spectrum .verdict"))
    pg = vpage({"per_pass": [{"id": "a", "class": "brown dwarf", "type": "T8"}, {"id": "b", "class": "brown dwarf", "type": "T8"},
                             {"id": "c", "class": "brown dwarf", "type": "T7"}, {"id": "d", "class": "uncertain", "type": None}]})
    check("per-pass: disagreement lists each pass", pg.inner_text(".verdict-passes") == "Passes disagree: T8, T8, T7, uncertain", pg.inner_text(".spectrum .verdict"))
    pg = page(b)
    pg.goto(BASE + "?mode=full&target=synthetic-fast-mover", wait_until="networkidle")
    pg.wait_for_selector(".spectrum .verdict")
    check("per-pass: absent shows nothing", pg.locator(".verdict-passes").count() == 0)
    check("classifier display: console clean", not pg.msgs, pg.msgs)

    # 15. Flagged points with no flux: counted, with reasons, and ticked on the axis
    def with_gaps(r):
        m2 = _j.loads(_j.dumps(base_m))
        for sp in m2["spectra"]:
            for wl, why in ((1.31, "saturated"), (3.9, "saturated"), (4.7, "masked")):
                sp["points"].append({"wl_um": wl, "bw_um": 0.04, "flux": None, "err": None, "detector": 3, "flagged": True, "reason": why})
        r.fulfill(body=_j.dumps(m2), content_type="application/json")
    pg = page(b)
    pg.route("**/synthetic-fast-mover/manifest.json", with_gaps)
    pg.goto(BASE + "?mode=full&target=synthetic-fast-mover&spec=spx-2025b", wait_until="networkidle")
    pg.wait_for_selector(".spec-plot .main-svg", timeout=20000)
    pg.wait_for_timeout(300)
    note = pg.inner_text(".gap-note")
    check("gaps: count and reasons stated under the spectrum", note.startswith("3 points left out of this spectrum: no usable flux (saturated 2 / masked 1)"), note)
    ticks = pg.evaluate("document.querySelector('.spec-plot').layout.shapes.filter(s => s.type === 'line').map(s => s.x0)")
    check("gaps: a tick on the axis baseline at each missing wavelength", ticks == [1.31, 3.9, 4.7], ticks)
    check("gaps: plotted points unchanged", pg.evaluate("document.querySelector('.spec-plot').data.filter(t => t.mode === 'markers').reduce((n, t) => n + t.x.length, 0)") == 97)
    pg.locator(".spectrum").screenshot(path=f"{IMG}/web-spectrum-gaps.png")
    pg = page(b)
    pg.goto(BASE + "?mode=full&target=synthetic-fast-mover&spec=spx-2025b", wait_until="networkidle")
    pg.wait_for_selector(".spec-plot .main-svg", timeout=20000)
    check("gaps: nothing said when no point is missing", pg.inner_text(".gap-note") == "")

    # 16. Degraded views: calm notice at the top; Retry only for a live view
    DEGRADED = "Some archive data could not be fetched just now, so this view is incomplete. Try again in a few minutes."
    pg = page(b)
    pg.goto(BASE + "?mode=full&target=synthetic-fast-mover", wait_until="networkidle")
    pg.wait_for_selector("canvas.stage")
    check("not degraded: no notice", pg.locator(".notice.degraded").count() == 0)
    pg = page(b)
    pg.route("**/synthetic-fast-mover/manifest.json", lambda r: r.fulfill(body=_j.dumps({**base_m, "degraded": True}), content_type="application/json"))
    pg.goto(BASE + "?mode=full&target=synthetic-fast-mover", wait_until="networkidle")
    pg.wait_for_selector("canvas.stage")
    first = pg.evaluate("document.querySelector('.view').firstElementChild.className")
    check("degraded gallery view: no banner, one quiet line in the notes", pg.locator(".notice.degraded").count() == 0 and "Built while an archive service was unavailable" in pg.text_content(".notes-degraded"), first)
    check("degraded gallery view: no Retry anywhere", pg.get_by_role("button", name="Retry").count() == 0)
    served = []
    pg8 = page(b)
    pg8.route("**/js/config.js", lambda r: r.fulfill(body=cfg, content_type="text/javascript"))
    pg8.route("**/api/view*", lambda r: (served.append(1), r.fulfill(body=_j.dumps({**base_m, "degraded": True}), content_type="application/json")))
    pg8.route("**/api/frames/**", frames)
    pg8.goto(BASE + "?mode=full&ra=150.0123&dec=20.0046", wait_until="networkidle")
    pg8.wait_for_selector(".notice.degraded button", timeout=10000)
    check("degraded: live view offers Retry", pg8.inner_text(".notice.degraded button") == "Retry")
    pg8.screenshot(path=f"{IMG}/web-degraded.png", clip={"x": 0, "y": 0, "width": 1280, "height": 360})
    pg8.click(".notice.degraded button")
    pg8.wait_for_selector(".notice.degraded button", timeout=10000)
    check("degraded: Retry asks the server again", len(served) == 2, len(served))
    check("degraded: console clean", not pg8.msgs, pg8.msgs)

    # 17. Real-manifest cases: a calm notes disclosure, a short chip, framing, hero rule
    REAL_NOTES = [
        "WISE frame-quality scores did not arrive from IRSA in time, so WISE frames were chosen by coverage alone (frames with unusual noise are still left out) and the 2010 three-band frames, which only that lookup lists, are missing.",
        "Every SPHEREx spectrum point is unusable (357 where the target saturates the detector, 1 where too much of the target is covered by bad pixels), so there is no spectrum to judge.",
        "CatWISE2020 sources could not be fetched, so none are marked.",
        "The target saturates some frames (W1, W2, spx-b1); positions there are less reliable.",
    ]
    SAT_ID = base_m["frames"][3]["id"]

    def real_like(r):
        m2 = _j.loads(_j.dumps(base_m))
        m2.update(degraded=True, warnings=REAL_NOTES, match=None, spectra=[])
        for i, f in enumerate(m2["frames"]):
            f["flag_fraction"] = 0.0105
            f["warnings"] = ["frame quality unknown for 14 frames", 'registered to 7 Gaia stars: frame offset -0.05" E, +0.14" N removed']
            if i == 3:
                f["warnings"] += ["saturated", "saturated core: position measured from the unsaturated wings"]
                f["flag_fraction"] = 0.04
        r.fulfill(body=_j.dumps(m2), content_type="application/json")
    pg = page(b)
    pg.route("**/synthetic-fast-mover/manifest.json", real_like)
    pg.goto(BASE + "?mode=full&target=synthetic-fast-mover&frame=" + base_m["frames"][0]["id"], wait_until="networkidle")
    pg.wait_for_selector("canvas.stage")
    top = pg.evaluate("document.querySelector('canvas.stage').getBoundingClientRect().top")
    # The title and the three-tile verdict strip sit above the image by design; nothing else may.
    check("notes: the image starts high on the page, not under a wall of warnings", top < 440, top)
    check("verdict strip: three tiles under the title, each linking to its section",
          pg.eval_on_selector_all(".verdict-strip a.vtile", "e => e.map(a => a.getAttribute('href'))") == ["#motion", "#spectrum", "#data"]
          and all(pg.locator(h).count() == 1 for h in ("#motion", "#spectrum", "#data")), pg.inner_text(".verdict-strip"))
    check("notes: collapsed, count visible", pg.get_attribute(".notes-more", "open") is None and pg.inner_text(".notes-more summary") == "Data-quality notes and flags (4)", pg.inner_text(".notes"))
    check("notes: one visible line says what changes the reading", "No spectrum: the star saturates SPHEREx" in pg.inner_text(".notes-lines"), pg.inner_text(".notes-lines"))
    check("notes: every warning is in the disclosure, no banner", all(w in pg.text_content(".notes-more") for w in REAL_NOTES) and pg.locator(".banner").count() == 0)
    check("notes: stored degraded view has one quiet line, no Retry", "Built while an archive service was unavailable; a few 2010 WISE frames and catalogue markers are missing." in pg.text_content(".notes-degraded")
          and pg.get_by_role("button", name="Retry").count() == 0)
    pg.click(".notes-more summary")
    check("notes: opens on click", pg.get_attribute(".notes-more", "open") is not None)
    check("chip: routine notes (about 1% flagged, quality unknown, Gaia registration) show no chip", not pg.locator(".flag-badge").is_visible())
    pg.goto(BASE + "?mode=full&target=synthetic-fast-mover&frame=" + SAT_ID, wait_until="networkidle")
    pg.wait_for_selector("canvas.stage")
    pg.wait_for_timeout(300)
    check("chip: a saturated frame shows a short chip, full text in the tooltip", pg.locator(".flag-badge").is_visible() and pg.inner_text(".flag-badge").startswith("⚠") and len(pg.eval_on_selector(".flag-badge > span:first-child", "e => e.textContent")) < 20
          and "unsaturated wings" in pg.eval_on_selector(".flag-tip", "e => e.textContent"), pg.inner_text(".stage-wrap"))
    check("chip: the frame card carries the full text", "unsaturated wings" in pg.inner_text(".frame-warnings"))
    check("notes: console clean", not pg.msgs, pg.msgs)

    # Hero rule on the fixtures: the one moving target leads, with measured numbers read from its manifest
    pg = page(b)
    pg.goto(BASE, wait_until="networkidle")
    pg.wait_for_selector(".hero-caption")
    check("hero: chosen from the index by rule (the moving, typed target)", "SYNTHETIC fast mover" in pg.text_content(".hero-target") and "SYNTHETIC fast mover" in pg.get_attribute(".hero-visual a.btn.primary", "aria-label"), pg.inner_text(".hero-visual"))
    check("hero: the readout carries the measured and catalogue numbers and the published type", "″ a year" in pg.inner_text(".hero-readout") and "catalogue 2.9" in pg.inner_text(".hero-readout") and "published" in pg.inner_text(".hero-readout"), pg.inner_text(".hero-readout"))

    # Zoom slider: continuous, URL round trip, accessible value text, keys, wheel rules
    if (WEB / "gallery" / "barnards-star" / "manifest.json").exists():
        pg = page(b, fixtures=False)
        pg.goto(BASE + "?mode=full&target=barnards-star&zoom=2.4&follow=0", wait_until="networkidle")
        pg.wait_for_selector("canvas.stage")
        check("zoom: fractional zoom restored from the URL", pg.input_value("#zoom") == "2.4" and pg.inner_text(".zoom-out") == "2.4×" and pg.get_attribute("canvas.stage", "data-zoom") == "2.40", pg.inner_text(".zoom-out"))
        check("zoom: slider has a label and value text", pg.get_attribute("#zoom", "aria-label") == "Zoom" and pg.get_attribute("#zoom", "aria-valuetext") == "2.4 times")
        pg.goto(BASE + "?mode=full&target=barnards-star&zoom=2", wait_until="networkidle")
        pg.wait_for_selector("canvas.stage")
        check("zoom: an old integer value is accepted", pg.get_attribute("canvas.stage", "data-zoom") == "2.00")
        pg.goto(BASE + "?mode=full&target=barnards-star", wait_until="networkidle")
        pg.wait_for_selector("canvas.stage")
        z0 = float(pg.get_attribute("canvas.stage", "data-zoom"))
        check("framing: the 170 arcsec path of Barnard's Star opens at about 1x with Follow off", 1 <= z0 < 1.5 and not pg.is_checked("#follow"), z0)
        pg.click("text=Fit track")
        seen = []
        for z in ("1.3", "1.35", "1.4"):
            pg.fill("#zoom", z)
            seen.append(pg.get_attribute("canvas.stage", "data-zoom"))
        check("zoom: the slider changes the view scale continuously", seen == ["1.30", "1.35", "1.40"], seen)
        pg.fill("#zoom", "2.1")
        pg.wait_for_timeout(400)
        check("zoom: the URL carries a fractional zoom and Follow", "zoom=2.1" in pg.evaluate("location.search") and "follow=1" in pg.evaluate("location.search"), pg.evaluate("location.search"))
        check("follow: zooming past the fitting level switches it on, and says so", pg.is_checked("#follow") and "switch to Fixed sky" in pg.inner_text(".follow-note"), pg.inner_text(".follow-note"))
        pg.click("text=Fit track")
        check("zoom: Fit track returns to the default framing", abs(float(pg.get_attribute("canvas.stage", "data-zoom")) - z0) < 0.01 and not pg.is_checked("#follow"))
        box = pg.locator("canvas.stage").bounding_box()
        pg.mouse.move(box["x"] + 300, box["y"] + 300)
        pg.mouse.wheel(0, -300)
        pg.wait_for_timeout(150)
        check("wheel: a plain scroll over an unfocused image does not zoom it", pg.get_attribute("canvas.stage", "data-zoom") == f"{z0:.2f}")
        pg.evaluate("""() => { const c = document.querySelector('canvas.stage'); const r = c.getBoundingClientRect();
          c.dispatchEvent(new WheelEvent('wheel', { deltaY: -60, ctrlKey: true, clientX: r.left + 300, clientY: r.top + 300, bubbles: true, cancelable: true })); }""")
        pg.wait_for_timeout(150)
        check("wheel: Ctrl+wheel zooms about the cursor", float(pg.get_attribute("canvas.stage", "data-zoom")) > z0)
        pg.focus("canvas.stage")
        before = float(pg.get_attribute("canvas.stage", "data-zoom"))
        pg.keyboard.press("-")
        mid = float(pg.get_attribute("canvas.stage", "data-zoom"))
        pg.keyboard.press("+")
        check("keys: - and + zoom when the image has focus", mid < before and float(pg.get_attribute("canvas.stage", "data-zoom")) > mid, (before, mid))
        check("zoom: console clean", not pg.msgs, pg.msgs)

        # Follow mode keeps the object at the centre; fixed sky at the default never loses it
        for slug in ("barnards-star", "wise-0855-0714"):
            pf = page(b, fixtures=False, reduced=True)
            pf.goto(BASE + f"?mode=full&target={slug}&zoom=3&follow=1", wait_until="networkidle")
            pf.wait_for_selector("canvas.stage")
            n = int(pf.get_attribute(".timeline", "aria-valuemax")) + 1
            worst = 0.0
            for _ in range(n):
                pf.locator("body").press("ArrowRight")
                pf.wait_for_timeout(60)
                o = pf.get_attribute("canvas.stage", "data-object")
                if o:
                    x, y = (float(t) for t in o.split(","))
                    worst = max(worst, abs(x - 0.5), abs(y - 0.5))
            view_px = pf.evaluate("document.querySelector('canvas.stage').clientWidth")
            check(f"follow: {slug}: the object stays at the centre in all {n} frames (within 6 view pixels)", worst * view_px < 6, f"worst {worst * view_px:.1f} of {view_px}px")
            pf = page(b, fixtures=False, reduced=True)
            pf.goto(BASE + f"?mode=full&target={slug}", wait_until="networkidle")
            pf.wait_for_selector("canvas.stage")
            inside = True
            for _ in range(n):
                pf.locator("body").press("ArrowRight")
                pf.wait_for_timeout(60)
                o = pf.get_attribute("canvas.stage", "data-object")
                if o:
                    x, y = (float(t) for t in o.split(","))
                    inside &= 0 < x < 1 and 0 < y < 1
            check(f"fixed sky: {slug}: at the default zoom the object never leaves the view", inside)
        # Zoomed in with Fixed sky: an edge arrow and a keyboard-reachable re-centre
        pf = page(b, fixtures=False, reduced=True)
        pf.goto(BASE + "?mode=full&target=barnards-star&zoom=4&follow=0", wait_until="networkidle")
        pf.wait_for_selector("canvas.stage")
        gone = False
        for _ in range(40):
            pf.locator("body").press("ArrowRight")
            pf.wait_for_timeout(40)
            if pf.locator(".recentre").is_visible():
                gone = True
                break
        check("fixed sky: an object that leaves the view offers a re-centre button", gone)
        if gone:
            pf.focus(".recentre")
            pf.keyboard.press("Enter")
            x, y = (float(t) for t in pf.get_attribute("canvas.stage", "data-object").split(","))
            check("fixed sky: re-centre by keyboard brings it back into view", 0 < x < 1 and 0 < y < 1 and not pf.locator(".recentre").is_visible(), (x, y))

    # 18. A long gap in time: shaded on the timeline, announced on the image
    def gappy(r):
        m2 = _j.loads(_j.dumps(base_m))
        m2["frames"] = [f for f in m2["frames"] if not (2011 <= 2000 + (f["mjd"] - 51544.5) / 365.25 < 2025.0)]
        r.fulfill(body=_j.dumps(m2), content_type="application/json")
    pg = page(b, reduced=True)
    pg.route("**/synthetic-fast-mover/manifest.json", gappy)
    pg.goto(BASE + "?mode=full&target=synthetic-fast-mover&preset=wise-spherex", wait_until="networkidle")
    pg.wait_for_selector("canvas.stage")
    check("gap: the timeline shades and labels the stretch with no images", pg.locator(".tl-gap").count() == 1 and "no images 2011" in pg.inner_text(".tl-gap"), pg.locator(".tl-gap").all_inner_texts())
    check("view: opens on the newest SPHEREx image", "SPHEREx" in pg.get_attribute("canvas.stage", "aria-label"), pg.get_attribute("canvas.stage", "aria-label"))
    pg.locator("body").press("ArrowRight")  # wraps from the newest image to the first
    pg.locator("body").press("ArrowRight")
    pg.locator("body").press("ArrowRight")
    pg.wait_for_timeout(200)
    cue = pg.inner_text(".gap-cue") if pg.locator(".gap-cue").is_visible() else ""
    check("gap: stepping across it shows how long the jump is", cue.endswith("years later") and int(cue.split()[0]) >= 14, cue)
    pg.screenshot(path=f"{IMG}/web-gap-cue.png")
    check("gap: console clean", not pg.msgs, pg.msgs)

    # 19. All-sky locator: renders on a fixture view and a real view, marker where the projection says,
    # context line, no console errors, only the site's own files requested, phone width, embed, keyboard
    def locator_checks(label, url, fixtures, slug, expect_text, others, manifest_path):
        pl = page(b, fixtures=fixtures, reduced=True)
        seen = []
        pl.on("request", lambda r: seen.append(r.url))
        pl.goto(BASE + url, wait_until="networkidle")
        pl.wait_for_selector(".locator-map")
        pl.wait_for_timeout(500)
        c = json.loads(Path(manifest_path).read_text())["center"]
        cx, cy, rx = pl.eval_on_selector(".lm-frame", "e => [+e.getAttribute('cx'), +e.getAttribute('cy'), +e.getAttribute('rx')]")
        hx, hy = hammer_chart(c["ra"], c["dec"])
        k = rx / (2 * math.sqrt(2))
        got = pl.eval_on_selector(".lm-here-dot", "e => [+e.getAttribute('cx'), +e.getAttribute('cy')]")
        err = math.hypot(got[0] - (cx + k * hx), got[1] - (cy - k * hy))
        check(f"locator: {label}: the marker is where the projection puts RA {c['ra']:.3f} Dec {c['dec']:.3f}", err < 0.1, f"off by {err:.3f} svg units")
        ctx_text = pl.inner_text(".locator-context")
        check(f"locator: {label}: context line has constellation, galactic latitude and scale", expect_text in ctx_text and "Galactic latitude" in ctx_text
              and "arcminutes across" in ctx_text and "the full Moon" in ctx_text, ctx_text)
        aria = pl.get_attribute(".locator-map", "aria-label")
        check(f"locator: {label}: the map has a text alternative", aria.startswith("Map of the whole sky") and "degrees" in aria, aria)
        check(f"locator: {label}: Milky Way band, ecliptic and stars drawn", pl.locator(".lm-band").count() == 2 and pl.locator(".lm-ecliptic").count() == 1
              and pl.locator(".lm-star").count() >= 20 and len(pl.get_attribute(".lm-band", "d")) > 500)
        check(f"locator: {label}: other targets linked", pl.locator("a.lm-target").count() == others, pl.locator("a.lm-target").count())
        if others:
            href = pl.get_attribute("a.lm-target", "href")
            check(f"locator: {label}: a marker links to that target", "target=" in href and slug not in href, href)
            pl.focus("a.lm-target")
            vis = pl.eval_on_selector("a.lm-target .lm-target-name", "e => getComputedStyle(e).opacity")
            check(f"locator: {label}: focusing a marker shows its name", vis == "1" and len(pl.text_content("a.lm-target .lm-target-name")) > 3, vis)
        check(f"locator: {label}: console clean", not pl.msgs, pl.msgs)
        origin = BASE.split("//")[1].split("/")[0]
        foreign = [u for u in seen if not u.startswith(("data:", "blob:")) and u.split("//")[1].split("/")[0] != origin]
        check(f"locator: {label}: no request leaves the site", not foreign, foreign)
        return pl

    fixture_m = FIX / "synthetic-fast-mover" / "manifest.json"
    n_others = len(json.loads((WEB / "gallery" / "index.json").read_text())["targets"]) - 1  # every other shipped target
    pl = locator_checks("fixture view", "?mode=full&target=synthetic-fast-mover", True, "synthetic-fast-mover", "In the constellation", 0, fixture_m)
    pl = locator_checks("real view (Barnard's Star)", "?mode=full&target=barnards-star", False, "barnards-star", "In the constellation Ophiuchus.", n_others,
                        WEB / "gallery" / "barnards-star" / "manifest.json")
    side = pl.eval_on_selector(".locator", "e => !!e.closest('#data') && e.getBoundingClientRect().top > document.querySelector('#spectrum').getBoundingClientRect().bottom")
    check("locator: desktop: sits in 'Check the data', after the spectrum", side)
    locator_checks("real view (2MASS 0415-0935)", "?mode=full&target=2mass-0415-0935", False, "2mass-0415-0935", "In the constellation Eridanus.", n_others,
                   WEB / "gallery" / "2mass-0415-0935" / "manifest.json")

    # phone width: the inset stacks below the player, stays legible, the page does not scroll sideways
    ph = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, reduced_motion="reduce")
    ph.route("**/js/config.js", lambda r: r.fulfill(body="export const API_BASE = '';\nexport const LIVE_TIMEOUT_MS = 150000;\n", content_type="text/javascript"))
    pp = ph.new_page()
    pp.msgs = []
    pp.on("console", lambda m: pp.msgs.append(m.text) if m.type in ("error", "warning") else None)
    pp.on("pageerror", lambda e: pp.msgs.append(str(e)))
    pp.goto(BASE + "?mode=full&target=barnards-star", wait_until="networkidle")
    pp.wait_for_selector(".locator-map")
    box = pp.eval_on_selector(".locator-map", "e => { const r = e.getBoundingClientRect(); return [r.width, r.height]; }")
    below = pp.eval_on_selector(".locator", "e => e.getBoundingClientRect().top > document.querySelector('canvas.stage').getBoundingClientRect().bottom")
    check("locator: phone: stacks below the player", below)
    check("locator: phone: map at least 220 px wide and within the screen", 220 <= box[0] <= 390, box)
    check("locator: phone: no sideways scroll", pp.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), pp.evaluate("document.documentElement.scrollWidth"))
    small = pp.eval_on_selector_all(".lm-label", "e => e.map(x => parseFloat(getComputedStyle(x).fontSize) * x.ownerSVGElement.getBoundingClientRect().width / x.ownerSVGElement.viewBox.baseVal.width)")
    check("locator: phone: labels at least 7 px tall on screen", small and min(small) >= 7, min(small) if small else None)
    check("locator: phone: console clean", not pp.msgs, pp.msgs)
    for slug in ("barnards-star", "2mass-0415-0935"):
        for tag, w, h, dsf in (("desktop", 1280, 900, 1), ("phone", 390, 844, 2)):
            ctxs = b.new_context(viewport={"width": w, "height": h}, device_scale_factor=dsf, reduced_motion="reduce")
            ctxs.route("**/js/config.js", lambda r: r.fulfill(body="export const API_BASE = '';\nexport const LIVE_TIMEOUT_MS = 150000;\n", content_type="text/javascript"))
            ps = ctxs.new_page()
            ps.goto(BASE + f"?mode=full&target={slug}", wait_until="networkidle")
            ps.wait_for_selector(".locator-map")
            ps.wait_for_timeout(400)
            ps.locator(".locator").screenshot(path=f"{IMG}/web-locator-{slug}-{tag}.png")
            ctxs.close()

    # embed: the sky inset belongs to "Check the data", which an embed leaves to the full page
    pe = page(b, reduced=True)
    pe.goto(BASE + "?mode=full&target=synthetic-fast-mover&embed=1", wait_until="networkidle")
    pe.wait_for_selector("canvas.stage")
    check("locator: embed on a wide frame leaves the inset to the full view, one link away",
          not pe.locator(".locator").is_visible() and pe.locator(".embed-link a").is_visible())
    pe2 = page(b, w=500, h=900, reduced=True)
    pe2.goto(BASE + "?mode=full&target=synthetic-fast-mover&embed=1", wait_until="networkidle")
    pe2.wait_for_selector("canvas.stage")
    check("locator: embed on a narrow frame hides the inset", not pe2.locator(".locator").is_visible())

    # 20. Solar System body mode, on the shipped Haumea view (built with python -m pxs.solarsystem)
    if (WEB / "gallery" / "haumea" / "manifest.json").exists():
        pb = page(b, fixtures=False, reduced=True)
        pb.goto(BASE, wait_until="networkidle")
        pb.wait_for_selector(".target-card")
        heads = pb.eval_on_selector_all(".group-h span:first-child", "e => e.map(x => x.textContent)")
        check("body: landing lists Haumea under its own heading, last", heads and heads[-1] == "Solar System objects", heads)
        check("body: the Haumea card does not claim a brown-dwarf type", "Ephemerix sees ice bands" in " ".join(pb.inner_text(".gallery a[href='?target=haumea']").split()))
        check("body: the hero is still a moving star or brown dwarf, not the body", "Haumea" not in pb.inner_text(".hero-visual"))
        pb.screenshot(path=f"{IMG}/web-body-landing.png", full_page=True)
        # The landing page with the shipped gallery: scoreboard strip, starters, marks on the rows
        val = json.loads((WEB / "data" / "validation.json").read_text())
        vs = val["summary"]
        pb.wait_for_selector(".scorestrip:not([hidden])")
        strip = " ".join(pb.inner_text(".scorestrip").split())
        check("landing: the scoreboard strip is computed from validation.json, failures beside the passes",
              f"Tested on {vs['targets']} known objects" in strip and f"{vs['motion']['passed']} of {vs['motion']['total']}" in strip
              and f"{vs['type']['passed']} of {vs['type']['total']}" in strip and pb.locator(".scorestrip a[href='validation.html']").count() == 1
              and (not vs["motion"]["failed"] or f"{vs['motion']['failed']} differ" in strip), strip)
        slugs = {t["slug"] for t in json.loads((WEB / "gallery" / "index.json").read_text())["targets"]}
        want = [s for s in ("2mass-0415-0935", "wise-0855-0714", "haumea") if s in slugs]
        got = pb.eval_on_selector_all(".starters a.starter", "e => e.map(a => a.getAttribute('href'))")
        check("landing: 'start with these three' links the starter views that are in the gallery", len(want) < 2 or got == [f"?target={s}" + ("&mode=full" if s == "wise-0855-0714" else "") for s in want], got)
        rows = {t["slug"]: t for t in val["targets"]}
        marked = pb.eval_on_selector_all(".gallery a.target-card", "e => e.map(a => [a.getAttribute('href').split('=')[1], [...a.querySelectorAll('.card-marks .vtag')].map(x => x.className.replace('vtag v-', ''))])")
        wrong = [(s, m) for s, m in marked if s in rows and (not m or m[1:2] != [rows[s]["type"]["verdict"]] or (rows[s]["motion"]["verdict"] in ("pass", "fail") and m[0] != rows[s]["motion"]["verdict"]))]
        check("landing: every validated row is marked with its motion and type verdicts", marked and not wrong, wrong)
        # More controls: closed until asked for
        pm = page(b, fixtures=False, reduced=True, more=False)
        pm.goto(BASE + "?mode=full&target=haumea", wait_until="networkidle")
        pm.wait_for_selector("details.more-controls")
        closed = pm.get_attribute("details.more-controls", "open") is None and not pm.locator("#zoom").is_visible() and pm.locator("#follow").is_visible() and pm.locator("#play").is_visible()
        pm.click("details.more-controls > summary")
        check("controls: zoom, image sets and overlays sit under 'More controls', closed by default; play, step, speed and Follow stay out",
              closed and pm.locator("#zoom").is_visible() and pm.locator(".layers input").first.is_visible())
        tiles = pm.eval_on_selector_all(".verdict-strip a.vtile", "e => e.map(a => [a.dataset.tile, a.getAttribute('href')])")
        check("body: the verdict strip has the same three tiles", tiles == [["motion", "#motion"], ["spectrum", "#spectrum"], ["data", "#data"]]
              and all(pm.locator(h).count() == 1 for h in ("#motion", "#spectrum", "#data")), tiles)
        pb.goto(BASE + "?mode=full&target=haumea", wait_until="networkidle")
        pb.wait_for_selector("#spectrum .seg")
        pb.wait_for_timeout(800)
        text = pb.inner_text("main")
        segs = pb.locator("#spectrum .seg")
        check("body: pass selector with all passes first, pressed", segs.count() == 4 and segs.nth(0).get_attribute("aria-pressed") == "true" and segs.nth(0).inner_text() == "All detected passes", segs.all_inner_texts())
        check("body: pass selector is a labelled group of buttons", pb.get_attribute("#spectrum .segmented", "aria-label") == "SPHEREx pass")
        check("body: the blink follows the body by default", pb.is_checked("#follow"))
        check("body: plain sentence on what SPHEREx sees", "SPHEREx sees Haumea’s water ice" in pb.inner_text("#spectrum .verdict-line"), pb.inner_text("#spectrum .verdict-line"))
        import re
        over = re.findall(r"\b(?:[1-9]\d{2,})%", text)
        check("body: no depth of 100% or more anywhere on the page", not over, over)
        check("body: saturated 3.0 µm band shown as a lower limit", "saturated: deeper than" in pb.inner_text(".depth-table"))
        check("body: ice-band windows shaded on the plot", pb.locator("#spectrum .spec-plot .shapelayer path").count() >= 6 or pb.locator("#spectrum .spec-plot").inner_text().count("2.3") >= 1)
        check("body: Planet X note is honest", "not a search and not a detection" in pb.inner_text(".planet-x") and "S/N 0.04" in pb.inner_text(".planet-x"), pb.inner_text(".planet-x"))
        check("body: brown-dwarf motion panel replaced", "How it moves" in text and "How fast is it moving?" not in text)
        check("body: no brown-dwarf vetting summary button", pb.get_by_role("button", name="Copy summary for Talk").count() == 0)
        imgs = pb.eval_on_selector_all(".body-cell img", "e => e.map(i => [i.complete && i.naturalWidth > 0, i.alt.length > 0, i.getAttribute('src')])")
        check("body: six body-centred images load, each with alt text", len(imgs) == 6 and all(a and t for a, t, _ in imgs), imgs)
        pb.locator("#spectrum .seg", has_text="2026-01-16").focus()
        pb.keyboard.press("Enter")
        pb.wait_for_timeout(500)
        srcs = pb.eval_on_selector_all(".body-cell img", "e => e.map(i => i.getAttribute('src'))")
        check("body: choosing a pass by keyboard updates the images, depths and URL",
              srcs and all("spx-2026a" in s for s in srcs) and "spec=spx-2026a" in pb.evaluate("location.search")
              and pb.locator("#spectrum .seg", has_text="2026-01-16").get_attribute("aria-pressed") == "true", (srcs, pb.evaluate("location.search")))
        check("body: still no impossible depth after switching pass", not re.findall(r"\b(?:[1-9]\d{2,})%", pb.inner_text("main")))
        pb.goto(BASE + "?mode=full&target=haumea&spec=spx-2026b", wait_until="networkidle")
        pb.wait_for_selector("#spectrum .seg")
        check("body: a link restores the chosen pass", pb.locator("#spectrum .seg", has_text="2026-06-21").get_attribute("aria-pressed") == "true")
        pb.goto(BASE + "?mode=full&target=haumea", wait_until="networkidle")
        pb.wait_for_selector("#spectrum .seg")
        pb.wait_for_timeout(800)
        pb.screenshot(path=f"{IMG}/web-body-haumea-desktop.png", full_page=True)
        check("body: console clean", not pb.msgs, pb.msgs)
        pp = page(b, w=390, h=844, reduced=True, fixtures=False)
        pp.goto(BASE + "?mode=full&target=haumea", wait_until="networkidle")
        pp.wait_for_selector("#spectrum .seg")
        pp.wait_for_timeout(800)
        check("body: phone: no sideways scroll", pp.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), pp.evaluate("document.documentElement.scrollWidth"))
        pp.screenshot(path=f"{IMG}/web-body-haumea-phone.png", full_page=True)
        check("body: phone: console clean", not pp.msgs, pp.msgs)
        if (WEB / "gallery" / "makemake" / "manifest.json").exists():
            pb.goto(BASE + "?mode=full&target=makemake", wait_until="networkidle")
            pb.wait_for_selector("#spectrum .seg")
            check("body: Makemake reads as methane ice, the contrast to Haumea", "SPHEREx sees Makemake’s methane ice" in pb.inner_text("#spectrum .verdict-line"), pb.inner_text("#spectrum .verdict-line"))
            check("body: Makemake: no impossible depth", not re.findall(r"\b(?:[1-9]\d{2,})%", pb.inner_text("main")))
            pb.wait_for_timeout(800)
            pb.screenshot(path=f"{IMG}/web-body-makemake-desktop.png", full_page=True)

    # 21. Gaia counterpart line in the motion panel
    pg = page(b, reduced=True)
    pg.goto(BASE + "?mode=full&target=synthetic-fast-mover", wait_until="networkidle")
    pg.wait_for_selector(".gaia-row")
    check("gaia: no source near a cold dwarf, said with radius, epoch and why", pg.text_content(".gaia-row").startswith("No Gaia star here")
          and "within 2″" in pg.inner_text(".gaia-row") and "Gaia epoch (2016)" in pg.inner_text(".gaia-row") and "cold brown dwarf" in pg.inner_text(".gaia-row"), pg.inner_text(".gaia-row"))

    def gaia_failed(r):
        m2 = _j.loads(_j.dumps(base_m))
        m2.update(degraded=True, warnings=m2["warnings"] + ["Gaia DR3 sources could not be fetched, so none are marked."])
        m2["overlays"]["gaia"] = []
        r.fulfill(body=_j.dumps(m2), content_type="application/json")
    pg = page(b, reduced=True)
    pg.route("**/synthetic-fast-mover/manifest.json", gaia_failed)
    pg.goto(BASE + "?mode=full&target=synthetic-fast-mover", wait_until="networkidle")
    pg.wait_for_selector(".gaia-row")
    check("gaia: a failed Gaia query says it could not be checked, never 'not in Gaia'", "could not be checked" in pg.inner_text(".gaia-row")
          and "Not in Gaia" not in pg.inner_text(".gaia-row"), pg.inner_text(".gaia-row"))
    if (WEB / "gallery" / "epsilon-indi-b" / "manifest.json").exists():
        pr = page(b, reduced=True, fixtures=False)
        pr.goto(BASE + "?mode=full&target=epsilon-indi-b", wait_until="networkidle")
        pr.wait_for_selector(".gaia-row")
        check("gaia: real ε Indi B is matched with its G magnitude", pr.text_content(".gaia-row").startswith("In Gaia DR3") and "G = 18.0" in pr.inner_text(".gaia-row"), pr.inner_text(".gaia-row"))
        pr.goto(BASE + "?mode=full&target=2mass-0415-0935", wait_until="networkidle")
        pr.wait_for_selector(".gaia-row")
        check("gaia: real 2MASS 0415 has no Gaia counterpart", pr.text_content(".gaia-row").startswith("No Gaia star here"), pr.inner_text(".gaia-row"))
        check("gaia: real views console clean", not pr.msgs, pr.msgs)
    if (WEB / "gallery" / "wise-0855-0714" / "manifest.json").exists():
        pr = page(b, reduced=True, fixtures=False)
        pr.goto(BASE + "?mode=full&target=wise-0855-0714&frame=spx-b5-2025c&bands=spx-b5", wait_until="networkidle")
        pr.wait_for_selector(".frame-warnings li")
        txt = pr.inner_text(".frame-card") + pr.eval_on_selector(".flag-tip", "e => e.textContent")
        check("labels: a pipeline note naming a band id is shown with the band's label", "spx-b" not in txt and "SPHEREx 4.42–5.0 µm" in txt, txt)

    # 22. Methane false colour in the band strip
    pg = page(b, reduced=True)
    pg.goto(BASE + "?mode=full&target=synthetic-fast-mover", wait_until="networkidle")
    pg.wait_for_selector("#fc-toggle")
    check("false colour: off by default", not pg.is_checked("#fc-toggle") and not pg.locator(".fc-figure").is_visible())
    pg.check("#fc-toggle")
    pg.wait_for_timeout(500)
    check("false colour: on puts fc=1 in the URL and shows the labelled picture", "fc=1" in pg.evaluate("location.search") and pg.locator(".fc-figure").is_visible()
          and pg.inner_text(".fc-figure figcaption").startswith("False colour, not true colour: red SPHEREx 4.42–5.0 µm"), pg.inner_text(".band-strip"))
    rgb = pg.evaluate("""() => { const c = document.querySelector('.fc-canvas'); const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
      let red = 0, neutral = 0; for (let i = 0; i < d.length; i += 4) { const [r, g, bl] = [d[i], d[i + 1], d[i + 2]];
        if (r > 120 && g < 0.6 * r && bl < 0.6 * r) red++; if (Math.min(r, g, bl) > 120) neutral++; } return [red, neutral]; }""")
    check("false colour: the injected methane dwarf comes out red, not grey", rgb[0] > 20, rgb)
    pg.uncheck("#fc-toggle")
    pg.wait_for_timeout(500)  # URL writes are coalesced over 250 ms
    check("false colour: off again drops fc from the URL", "fc=" not in pg.evaluate("location.search"), pg.evaluate("location.search"))
    pg.goto(BASE + "?mode=full&target=synthetic-fast-mover&fc=1", wait_until="networkidle")
    pg.wait_for_selector(".fc-figure:not([hidden])")
    check("false colour: restored from the URL", pg.is_checked("#fc-toggle"))
    check("false colour: console clean", not pg.msgs, pg.msgs)
    pg = page(b, reduced=True)
    pg.route("**/synthetic-fast-mover/frames/spherex-spx-b4*", lambda r: r.fulfill(status=404, body="gone"))
    pg.goto(BASE + "?mode=full&target=synthetic-fast-mover&fc=1", wait_until="networkidle")
    pg.wait_for_selector("#fc-toggle")
    check("false colour: a band image that failed to load disables it, with the reason", pg.is_disabled("#fc-toggle") and "did not load" in pg.inner_text(".fc-why")
          and not pg.locator(".fc-figure").is_visible(), pg.inner_text(".band-strip"))
    pg = page(b, reduced=True)
    pg.goto(BASE + "?mode=full&target=synthetic-faint&fc=1", wait_until="networkidle")
    pg.wait_for_selector("#fc-toggle")
    check("false colour: bands missing from the view disable it, with the reason", pg.is_disabled("#fc-toggle") and "not in this view" in pg.inner_text(".fc-why"), pg.inner_text(".band-strip"))

    # 23. "What the pipeline rejected" disclosure
    pg = page(b, reduced=True)
    pg.goto(BASE + "?mode=full&target=synthetic-fast-mover", wait_until="networkidle")
    pg.wait_for_selector("details.rejected")
    check("rejected: closed by default", pg.get_attribute("details.rejected", "open") is None)
    pg.click("details.rejected summary")
    rej = pg.inner_text("details.rejected")
    check("rejected: worst-flagged frame first, in plain words", "18% of pixels dropped" in rej.split("Object not found")[0] and "lost 10% or more" in rej, rej)
    check("rejected: frames where the object was not found, by set", "not found in 10 of 44 frames" in rej, rej)
    check("rejected: no raw ids", "spx-b" not in rej and "wise-w" not in rej, rej)
    first = pg.locator("details.rejected .linkish").first
    pg.evaluate("window.scrollTo(0, 0)")
    first.click()
    pg.wait_for_timeout(500)
    check("rejected: a listed frame opens paused in the blink", "frame=" in pg.evaluate("location.search") and pg.get_attribute(".controls .btn.primary", "aria-label") == "Play", pg.evaluate("location.search"))
    check("rejected: console clean", not pg.msgs, pg.msgs)

    # 24. Wide tables fit on a laptop, or scroll inside their card
    for w in (1280, 1440):
        pv = page(b, w=w, h=900, fixtures=False)
        pv.goto(BASE + "validation.html", wait_until="networkidle")
        pv.wait_for_selector(".val-scroll")
        over = pv.evaluate("[...document.querySelectorAll('.val-scroll')].filter(e => e.scrollWidth > e.clientWidth + 1).length")
        check(f"validation: every table fits at {w} px", over == 0, over)
    pv = page(b, w=390, h=844, fixtures=False)
    pv.goto(BASE + "validation.html", wait_until="networkidle")
    pv.wait_for_selector(".val-scroll")
    check("validation: on a phone wide tables scroll inside their card, keyboard-reachable, page does not",
          pv.evaluate("document.documentElement.scrollWidth <= innerWidth") and pv.evaluate("[...document.querySelectorAll('.val-scroll')].every(e => getComputedStyle(e).overflowX === 'auto' && e.tabIndex === 0)"))

    # 24b. Known bodies recovered: one row per covered V bin, the limit and both control rates
    rec = _j.loads((WEB / "data" / "body-recovery.json").read_text())
    pv = page(b, w=1280, h=900, fixtures=False)
    pv.goto(BASE + "validation.html", wait_until="networkidle")
    # Known bodies and variable stars sit in closed sections ("Solar System bodies", "Variable stars").
    pv.wait_for_selector("#bodies-h", state="attached")
    sec = pv.locator("details:has(#bodies-h)")
    txt = sec.text_content()
    n_bins = sum(1 for r in rec["by_predicted_v"] if r["n"])
    check("validation: known bodies section has a row per V bin, the limit and before/after control rates",
          sec.locator("tbody tr").count() == n_bins and f"V {rec['faintest_reliable_bin'].replace('-', '–')}" in txt
          and f"{rec['before']['false_detections']['passes']['k']} of 551" in txt
          and f"counts {rec['false_detections']['passes']['k']} of 551" in txt, txt[:400])

    # 24b2. Variable stars: what held, what failed, and the choices made after seeing data (data/variability.json)
    var = _j.loads((WEB / "data" / "variability.json").read_text())["stars"]
    pv.wait_for_selector("#var-h", state="attached")
    vt = " ".join(pv.text_content("details:has(#var-h)").split())
    check("validation: variable stars section gives the measured swings, the failures and the after-the-fact choices",
          all(f"{b['fit']['mag_pk']:.2f} mag" in vt for b in var["r-draconis"]["bands"])
          and all(x["band"] in vt for x in var["r-draconis"]["failed"])
          and "Choices made after seeing results" in vt and "RW Aurigae" in vt and "cannot tell" in vt, vt[:300])

    # 24b3. The answer first: a two-sentence lead, the five brief targets, the rest in closed sections
    rep = _j.loads((WEB / "data" / "validation.json").read_text())
    vs_, brief = rep["summary"], [t for t in rep["targets"] if t["group"] == "brief"]
    lead = " ".join(pv.inner_text("#val-answer").split())
    check("validation: the lead gives the motion and type counts from the report",
          f"{vs_['motion']['total']} of our {vs_['targets']} targets" in lead and f"{vs_['motion']['passed']} agree with the catalogue" in lead
          and f"{vs_['motion']['failed']} differ" in lead and f"we left {vs_['type']['refused']} unclassified" in lead, lead)
    rows = pv.locator("#brief tbody tr")
    names = rows.locator("th a").all_inner_texts()
    check("validation: five rows for the brief targets, each name linking to its view, only the typed ones marked as agreeing",
          names == [t["name"] for t in brief]
          and rows.locator("th a").evaluate_all("e => e.every(a => a.getAttribute('href').includes('target='))")
          and pv.locator("#brief td:nth-child(3) .vtag").count() == sum(t["type"]["verdict"] == "pass" for t in brief), names)
    bt = " ".join(pv.inner_text("#brief").split())
    check("validation: the five rows give the measured brightness change of the two variable stars",
          f"{round(var['r-draconis']['catalogue']['period_days'])}-day cycle" in bt and "RW Aurigae faded by a factor of about" in bt, bt[-400:])
    titles = pv.eval_on_selector_all(".val > details > summary", "e => e.map(x => x.innerText.trim())")
    n17 = len(rep["targets"])
    check("validation: the detail is in sections in the sceptic's order, the after-the-fact choices first",
          titles == ["What we chose after seeing results", f"All {n17} motions", f"All {n17} spectral types", "Where the measurements disagree or fall short",
                     "How the checks work", "Coverage and tracking", "Solar System bodies", "Variable stars"], titles)
    check("validation: Advanced, the default, opens every section",
          pv.locator(".val > details[open]").count() == len(titles), pv.locator(".val > details[open]").count())
    pv.goto(BASE + "validation.html?mode=simple", wait_until="networkidle")
    pv.wait_for_selector("#brief")
    check("validation: Simple leaves every section closed", pv.locator(".val > details[open]").count() == 0,
          pv.locator(".val > details[open]").count())
    pv.goto(BASE + "validation.html#choices", wait_until="networkidle")
    check("validation: a link to a closed section opens it", pv.evaluate("document.getElementById('choices').open")
          and "multiplied by 1.7" in pv.inner_text("#choices"))
    pv = page(b, w=390, h=844, fixtures=False)
    pv.goto(BASE + "validation.html", wait_until="networkidle")
    pv.wait_for_selector("#brief")
    pv.evaluate("document.querySelectorAll('.val details').forEach(d => d.open = true)")
    pv.wait_for_timeout(400)
    check("validation: phone: no horizontal scroll with every section open, the five rows stacked",
          pv.evaluate("document.documentElement.scrollWidth <= innerWidth")
          and pv.evaluate("getComputedStyle(document.querySelector('#brief tbody tr')).display") == "block",
          pv.evaluate("document.documentElement.scrollWidth"))

    # 24c. Pilot search of the predicted Planet Nine region: upper limits, in the report's words
    p9 = _j.loads((WEB / "data" / "p9-search.json").read_text())
    pp = page(b, w=1280, h=900, fixtures=False)
    pp.goto(BASE + "search.html?mode=simple", wait_until="networkidle")
    pp.wait_for_selector("#p9 .stat-grid")
    t9 = " ".join(pp.text_content("#p9").split())  # the peaks sit in a closed details inside the section
    snr7 = p9["pooled_snr7"]
    unexplained = [u for u in p9["unexplained_or_vetted_peaks_above_null_max"] if u["assessment"]["verdict"].startswith("unexplained")]
    check("pilot search: the statement, the area and the null-maximum limits, never the S/N 7 numbers as limits",
          pp.inner_text("#p9-h") == "A pilot search where Planet Nine is predicted"
          and "excludes none of the favoured Planet Nine cases" in t9 and f"{p9['area_deg2']:.1f} deg²" in t9 and f"{p9['n_fields']} fields" in t9
          and f"{round(p9['pooled']['flux50_ujy'])} µJy" in t9 and f"{round(p9['pooled']['flux90_ujy'])} µJy" in t9
          and f"{round(snr7['flux50_ujy'])} µJy" not in t9 and f"{round(snr7['flux90_ujy'])} µJy" not in t9, t9[:300])
    check("pilot search: an unexplained peak is described as the report does and never called a candidate",
          "candidate" not in t9.lower() and all("Most likely noise" in t9 and "another pass" in t9 for _ in unexplained)
          and pp.locator("#p9 .p9-peak").count() == len(unexplained), t9[-400:])
    pp.goto(BASE + "planetx.html?mode=simple", wait_until="networkidle")
    # The sentence sits in the closed "What earlier searches have ruled out" section.
    pp.wait_for_selector("#px-blind a[href='search.html#p9']", state="attached")
    check("planet x: one sentence points to the pilot search", "upper limits only" in pp.text_content("#px-blind"))

    # 24d. The answer first: a plain lead under the heading, the reach chart, the detail behind closed sections
    plx = _j.loads((WEB / "data" / "planetx-limits.json").read_text())
    se10 = next(c for c in plx["cases"] if c["key"] == "se10")["reach_au"]["spx_one_map_channel"]
    nom = max((v["nom"] for v in se10.values() if isinstance(v["nom"], (int, float))), default=None)
    lead = " ".join(pp.inner_text("#px-answer").split())
    check("planet x: the lead gives the reach, the predicted range and says it is not a detection",
          f"about {nom} au" in lead and "400 to 800 au" in lead and "not a detection" in lead, lead)
    check("planet x: what we found comes first, then the reach lead, then why we claim no Planet X",
          pp.evaluate("document.querySelector('main h1').nextElementSibling.id") == "px-found"
          and pp.locator("#px-found-list li").count() == 3 and "Haumea, Makemake and Eris" in pp.inner_text("#px-found")
          and pp.evaluate("[...document.querySelectorAll('#px-found, #px-answer, #px-why')].map(e => e.id).join()") == "px-found,px-answer,px-why"
          and "We claim no Planet X." in pp.inner_text("#px-why"), pp.inner_text("#px-found"))
    check("planet x: the reach chart is drawn with the predicted band named on it",
          pp.locator("#px-reach-plot .main-svg").count() > 0 and "Planet Nine predicted here" in pp.inner_text("#px-reach-plot"))
    check("planet x: the detail is in closed sections with plain titles, and nothing is lost",
          pp.eval_on_selector_all("main > details > summary", "e => e.map(x => x.innerText.trim())")
          == ["How we worked this out", "The numbers", "What earlier searches have ruled out", "What could be wrong", "Sources"]
          and pp.locator("main > details[open]").count() == 0 and pp.locator("#px-reach tbody tr").count() == len(plx["cases"])
          and pp.locator("#px-motion tbody tr").count() == len(plx["motion"]["rows"]))
    pp.click("#px-how > summary")
    pp.wait_for_selector(".px-plot .main-svg")
    check("planet x: opening 'How we worked this out' draws the band plot", pp.locator(".px-plot .main-svg").count() > 0)
    pp.goto(BASE + "search.html?mode=simple", wait_until="networkidle")
    mv = _j.loads((WEB / "data" / "movers.json").read_text())
    lead = " ".join(pp.inner_text("#sr-answer").split())
    check("search: the lead says what we tried, all known bodies found, nothing new, and the pilot cannot test Planet Nine",
          f"all {len(mv['known_bodies'])} known dwarf planets" in lead and "nothing new above the noise" in lead
          and "cannot test Planet Nine" in lead and f"V {p9['pooled']['vmag50']:.1f}" in lead and "none of the favoured cases" in lead
          and "short of the 400 to 800 au" in lead and "short of the 400 to 800 au" in pp.inner_text("#p9"), lead)
    check("search: the detail is in closed sections with plain titles, and nothing is lost",
          pp.eval_on_selector_all("main > details > summary", "e => e.map(x => x.innerText.trim())")
          == ["How we worked this out", "The numbers", "What could be wrong", "Sources"]
          and pp.locator("#sr-fields tbody tr").count() == len(mv["fields"]) + 1 and pp.locator("#sr-known tbody tr").count() == len(mv["known_bodies"]))
    pp.goto(BASE + "planetx.html#px-sources", wait_until="networkidle")
    check("planet x: a link to a closed section opens it", pp.evaluate("document.getElementById('px-sources').open"))
    for pth in ("planetx.html", "search.html"):
        ph = page(b, w=390, h=844, fixtures=False)
        ph.goto(BASE + pth, wait_until="networkidle")
        ph.evaluate("document.querySelectorAll('main details').forEach(d => d.open = true)")
        ph.wait_for_timeout(600)
        check(f"phone: no horizontal scroll on {pth}, every section open",
              ph.evaluate("document.documentElement.scrollWidth <= innerWidth"), ph.evaluate("document.documentElement.scrollWidth"))

    # 25. Site nav stays on one line on a phone, on every page
    for pth in ("", "validation.html", "planetx.html", "search.html", "status.html"):
        if pth and not (WEB / pth).exists():
            continue
        pn = page(b, w=390, h=844, fixtures=False)
        pn.goto(BASE + pth, wait_until="networkidle")
        r = pn.evaluate("""() => { const n = document.querySelector('header.site nav'); const tops = new Set([...n.querySelectorAll('a')].map(a => Math.round(a.getBoundingClientRect().top)));
          return [tops.size, n.scrollWidth - n.clientWidth]; }""")
        check(f"nav: one line, nothing cut off, at 390 px on {pth or 'index.html'}", r == [1, 0], r)

    # 26. No measured motion: the panel says so in its headline, in the pipeline's words when it has them
    def no_motion(r):
        m2 = _j.loads(_j.dumps(base_m))
        m2["measured_motion"] = None
        m2["warnings"] = m2["warnings"] + ["The target was not detected in any frame."]
        r.fulfill(body=_j.dumps(m2), content_type="application/json")
    pg = page(b, reduced=True)
    pg.route("**/synthetic-fast-mover/manifest.json", no_motion)
    pg.goto(BASE + "?mode=full&target=synthetic-fast-mover", wait_until="networkidle")
    pg.wait_for_selector(".motion")
    check("motion: headline says 'Not measured' with the pipeline's reason", pg.locator(".motion-headline").count() == 1
          and pg.inner_text(".motion-headline") == "Not measured: the target was not detected in any frame.", pg.inner_text(".motion"))

    # 27. Simple | Advanced: Advanced by default, mode=simple or the header switch for Simple, Back returns
    for w, h in ((1440, 900), (390, 844)):
        ps = page(b, w=w, h=h, reduced=True)
        ps.goto(BASE + "?target=synthetic-fast-mover", wait_until="networkidle")
        ps.wait_for_selector(".view-grid .motion")
        check(f"mode {w}: a bare link opens Advanced, the switch says so", ps.get_attribute(".mode-switch [data-mode=advanced]", "aria-pressed") == "true")
        sw = ps.evaluate("(() => { const r = document.querySelector('.mode-switch').getBoundingClientRect(); return [r.top, r.right, innerWidth]; })()")
        check(f"mode {w}: the switch sits in the header rail at the top right, on screen", sw[0] < 80 and sw[1] <= sw[2], sw)
        ps.goto(BASE + "?target=synthetic-fast-mover&mode=simple", wait_until="networkidle")
        ps.wait_for_selector(".view.simple .simple-answer")
        ps.screenshot(path=f"{IMG}/simple-{w}.png", full_page=True)
        ans = ps.inner_text(".simple-answer")
        check(f"simple {w}: the blink, its date and the plain answer, no tables or plots",
              ps.locator(".simple-blink canvas.stage").is_visible() and "image," in ps.inner_text(".simple-date")
              and ans.count("arcseconds") >= 1 and "It is moving" in ans and "spectrum" in ans
              and ps.locator(".simple table, .simple .js-plotly-plot, .simple .verdict-strip").count() == 0, ans[:300])
        check(f"simple {w}: no horizontal scroll", ps.evaluate("document.documentElement.scrollWidth <= innerWidth"))
        check(f"simple {w}: reduced motion leaves the blink paused", ps.get_attribute("#simple-play", "aria-label") == "Play")
    check("simple: SPHEREx only plays SPHEREx images", (ps.click(".simple-missions .seg >> nth=1"), ps.click("[aria-label='Next image']"),
          ps.get_attribute(".simple-date", "data-mission"))[-1] == "SPHEREx")
    ps.evaluate("window.scrollTo(0, 400)")
    ps.focus(".mode-switch [data-mode=advanced]")
    ps.keyboard.press("Enter")
    ps.wait_for_selector(".view-grid .motion")
    ps.wait_for_timeout(400)
    cv = ps.evaluate("(() => { const r = document.querySelector('canvas.stage').getBoundingClientRect(); return r.bottom > 0 && r.top < innerHeight; })()")
    check("switch: the keyboard switches to Advanced in place, the picture stays in view, the URL drops mode", "mode=" not in ps.url and cv, [ps.url, cv])
    ps.go_back()
    ps.wait_for_selector(".view.simple")
    check("switch: Back returns to Simple", "mode=simple" in ps.url, ps.url)
    ps.go_forward()
    ps.wait_for_selector(".view-grid .motion")
    check("switch: Forward returns to Advanced", ps.locator(".view.simple").count() == 0)
    for q, want in (("?target=synthetic-fast-mover&frame=wise-w2-2019p40", "full"), ("?target=synthetic-fast-mover&mode=full", "full"),
                    ("?target=synthetic-fast-mover&mode=advanced", "full"), ("?target=synthetic-fast-mover&mode=simple&bands=W2", "simple")):
        ps.goto(BASE + q, wait_until="networkidle")
        ps.wait_for_selector(".view")
        got = "simple" if ps.locator(".view.simple").count() else "full"
        check(f"mode: {q} opens the {want} view", got == want, got)
    check("simple: console clean", not ps.msgs, ps.msgs)

    # 27b. The choice lasts across pages and visits; the hint shows once and goes; text pages open in Advanced
    pm = page(b, fixtures=False, hint=True)
    pm.goto(BASE + "planetx.html", wait_until="networkidle")
    pm.wait_for_selector(".mode-hint:not([hidden])", timeout=5000)
    hint = pm.locator(".mode-hint")
    check("hint: appears on a first visit, beside the switch, announced politely", "Switch to Simple" in hint.inner_text() and hint.get_attribute("aria-live") == "polite")
    check("hint: no modal, nothing takes focus", pm.locator("dialog[open], [role=dialog]").count() == 0 and pm.evaluate("document.activeElement === document.body"))
    opened = pm.evaluate("[...document.querySelectorAll('main details.card')].map(d => d.open)")
    check("planetx: Advanced opens every section", opened and all(opened), opened)
    pm.click(".mode-hint-x")
    check("hint: dismissed on a click", pm.locator(".mode-hint").count() == 0)
    pm.reload(wait_until="networkidle")
    pm.wait_for_timeout(2500)
    check("hint: never returns once dismissed", pm.locator(".mode-hint").count() == 0)
    pm.click(".mode-switch [data-mode=simple]")
    closed = pm.evaluate("[...document.querySelectorAll('main details.card')].map(d => d.open)")
    check("planetx: Simple closes the sections", closed and not any(closed), closed)
    for pth, sel in (("search.html", "main details.card"), ("explore.html", "body"), ("validation.html", "body"), ("", ".landing")):
        pm.goto(BASE + pth, wait_until="networkidle")
        pm.wait_for_selector(".mode-switch")
        check(f"switch on {pth or 'index.html'}: present, and the Simple choice carried over",
              pm.get_attribute(".mode-switch [data-mode=simple]", "aria-pressed") == "true", pth)
    pm.goto(BASE + "search.html", wait_until="networkidle")
    pm.wait_for_timeout(500)
    check("search page: Simple leaves its sections closed", not any(pm.evaluate("[...document.querySelectorAll('main details.card')].map(d => d.open)")))
    pm.goto(BASE, wait_until="networkidle")
    check("landing Simple: the scoreboard strip and starter cards wait below or folded", not pm.locator(".scorestrip").is_visible() and not pm.locator(".start").is_visible())
    pm.click(".mode-switch [data-mode=advanced]")
    pm.goto(BASE + "search.html", wait_until="networkidle")
    pm.wait_for_timeout(500)
    check("search page: Advanced opens its sections", all(pm.evaluate("[...document.querySelectorAll('main details.card')].map(d => d.open)")))
    check("mode pages: console clean", not [m for m in pm.msgs if "404" not in m and "Failed to load resource" not in m], pm.msgs)

    # 28. Name search: suggestions from the offline index, a plain reading of a typed position, example chips
    pl = page(b, fixtures=False)
    pl.goto(BASE, wait_until="networkidle")
    check("landing: three or four example chips, the challenge's own targets", 3 <= pl.locator(".examples .chip").count() <= 4
          and "Barnard" in pl.inner_text(".examples"), pl.locator(".examples .chip").all_inner_texts())
    for q, want in (("barn", "Barnard's Star"), ("eps ind", "Epsilon Indi"), ("WISE 0855", "WISE 0855-0714"), ("Luhman", "Luhman 16"),
                    ("HD 209100", "Epsilon Indi A"), ("Gl 699", "Barnard's Star"), ("2MASS J0415", "2MASS J0415-0935")):
        pl.fill("#pos", q)
        pl.wait_for_selector("#pos-suggest li", timeout=3000)
        first = pl.inner_text("#pos-suggest li >> nth=0")
        check(f"suggest: '{q}' offers {want}", want in first and pl.get_attribute("#pos", "aria-expanded") == "true", first)
    check("suggest: a gallery view is marked as opening instantly", "Opens instantly" in pl.inner_text("#pos-suggest li >> nth=0"))
    pl.fill("#pos", "08h55m10.83s -07d14m42.5s")
    pl.wait_for_timeout(100)
    check("search: says plainly how a position was read", "We read this as RA 08 55 10.83 (hours)" in pl.inner_text(".understood"), pl.inner_text(".understood"))
    pl.fill("#pos", "eps ind")
    pl.wait_for_selector("#pos-suggest li")
    pl.press("#pos", "ArrowDown")
    pl.press("#pos", "Enter")
    pl.wait_for_url("**target=epsilon-indi-b*", timeout=5000)
    pl.wait_for_selector(".view")
    check("suggest: arrow and Enter open the chosen view", "target=epsilon-indi-b" in pl.url, pl.url)
    pl.goto(BASE, wait_until="networkidle")
    pl.fill("#pos", "Proxima")
    pl.wait_for_selector("#pos-suggest li")
    check("suggest: an object without a built view is marked as built live", "live" in pl.inner_text("#pos-suggest li >> nth=0").lower())
    # The brief's own text for WISE 0855 (its WISE-era position) opens the built view, not a live build.
    for q in ("Right Ascension 08h55m10.831s, declination -7d14m42.53s", "08h55m10.831s, -7d14m42.53s", "08h55m10.831s -7d14m42.53s",
              "08 55 10.831 -07 14 42.53", "133.7951 -7.2451"):
        pl.goto(BASE, wait_until="networkidle")
        pl.fill("#pos", q)
        pl.wait_for_selector("#pos-suggest li", timeout=3000)
        first, said = pl.inner_text("#pos-suggest li >> nth=0"), pl.inner_text(".understood")
        check(f"brief position '{q}': recognised as WISE 0855-0714, a built view",
              "WISE 0855-0714" in first and "Opens instantly" in first and "That is WISE 0855-0714, a built view." in said, [first, said])
    pl.click(".search button[type=submit]")
    pl.wait_for_url("**target=wise-0855-0714*", timeout=5000)
    pl.wait_for_selector(".view")
    check("brief position: the button opens the built view, which offers the Talk summary",
          pl.locator("button", has_text="Copy summary for Talk").count() >= 1, pl.url)
    check("suggest: console clean", not pl.msgs, pl.msgs)

    # 29. A live view opens simple too: partial data says so, and SPHEREx-only data has no mission switch
    def json_route(body):
        return lambda r: r.fulfill(body=body, content_type="application/json")
    for label, frames_of in (("partial", lambda fs: fs), ("SPHEREx only", lambda fs: [f for f in fs if f["mission"] == "SPHEREx"])):
        live_m = _j.dumps({**base_m, "degraded": True, "frames": frames_of(base_m["frames"])})
        pv = page(b, reduced=True)
        pv.route("**/js/config.js", lambda r: r.fulfill(body=cfg, content_type="text/javascript"))
        pv.route("**/api/view*", json_route(live_m))
        pv.route("**/api/frames/**", frames)
        pv.goto(BASE + "?ra=150.0123&dec=20.0046&mode=simple", wait_until="networkidle")
        pv.wait_for_selector(".view.simple .simple-answer", timeout=10000)
        ans = pv.inner_text(".simple-answer")
        check(f"live simple ({label}): opens simple and says the view is partial", "This view is partial" in ans and "position search" in pv.inner_text(".view-head").lower(), ans[:300])
        check(f"live simple ({label}): the mission switch only when both missions are there",
              pv.locator(".simple-missions").count() == (1 if label == "partial" else 0))
        check(f"live simple ({label}): console clean", not pv.msgs, pv.msgs)

    # 30. First screen: it plays on arrival, the answer is in view, a line says what to look for, few controls
    first_screen = """() => { const vis = (e) => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0 && r.top < innerHeight && r.bottom > 0 && r.right > 0 && !e.closest('details:not([open]) > :not(summary)'); };
      return [...document.querySelectorAll('a[href], button, input, select, summary')].filter(vis).length; }"""
    for w, h in ((1440, 900), (390, 844)):
        pa = page(b, w=w, h=h)
        pa.goto(BASE + "?target=synthetic-fast-mover&mode=simple", wait_until="networkidle")
        pa.wait_for_selector(".view.simple .simple-look")
        pa.wait_for_timeout(600)
        bottom = pa.evaluate("document.querySelector('.simple-pill').getBoundingClientRect().bottom")
        check(f"first screen {w}: the blink plays on arrival", pa.get_attribute("#simple-play", "aria-label") == "Pause")
        check(f"first screen {w}: the answer and both motions are visible without scrolling", bottom <= h, bottom)
        n = pa.evaluate(first_screen)
        check(f"first screen {w}: at most 18 controls in view, the header switch included", n <= 18, n)
        check(f"first screen {w}: no modal or tour", pa.locator("dialog[open], [role=dialog]").count() == 0)
        look, pill, scale = pa.inner_text(".simple-look"), pa.inner_text(".simple-pill"), pa.inner_text(".simple-scale")
        check(f"first screen {w}: what to look for, measured against catalogue, the patch against the Moon",
              look.startswith("Watch the ringed dot drift") and "Measured 2.98 arcsec a year. Catalogue" in pill and "full Moon" in scale, [look, pill, scale])
        check(f"first screen {w}: SPHEREx only says how many images and when", re.match(r"SPHEREx only: \d+ images, 20\d\d", pa.inner_text(".simple-missions .seg >> nth=1")) is not None,
              pa.inner_text(".simple-missions"))
    ph = page(b, fixtures=False)
    ph.goto(BASE, wait_until="networkidle")
    ph.wait_for_selector(".hero-play")
    check("landing: the featured blink plays on arrival", ph.get_attribute(".hero-play", "aria-label") == "Pause the blink")
    ph.click("#show-mover")
    ph.wait_for_selector(".view", timeout=10000)
    check("landing: 'Show me something that moves' opens a gallery target that clearly moves",
          "target=" in ph.url and not any(s in ph.url for s in ("r-draconis", "rw-aurigae", "haumea", "makemake")), ph.url)
    check("landing: mover console clean", not ph.msgs, ph.msgs)

    # 31. Defects from a cold test: counts that agree, no label past the newest image, the variable
    # stars lead with brightness, an insignificant motion is not a motion, and no HTTP codes
    TEXTS_JS = """(() => { window.__drawn = []; const f = CanvasRenderingContext2D.prototype.fillText;
      CanvasRenderingContext2D.prototype.fillText = function (t, ...a) { window.__drawn.push(String(t)); return f.call(this, t, ...a); }; })()"""
    pd = page(b, fixtures=False, reduced=True)
    pd.context.add_init_script(TEXTS_JS)
    pd.goto(BASE + "?target=wise-0855-0714&mode=simple", wait_until="networkidle")
    pd.wait_for_selector(".simple-missions-line")
    check("counts: the simple view says which of all the images it plays", "plays 27 of all 68 images" in pd.inner_text(".simple-missions-line"),
          pd.inner_text(".simple-missions-line"))
    pd.click(".simple-missions .seg >> nth=1")
    check("SPHEREx only: how many, which wavelength, and how often we find it", re.search(r"4 from SPHEREx 4\.42.5\.0 µm, 2025 to 2026\. We find the object in 3 of these 4", pd.inner_text(".simple-missions-line")) is not None,
          pd.inner_text(".simple-missions-line"))
    pd.goto(BASE + "?target=wise-0855-0714&mode=full", wait_until="networkidle")
    pd.wait_for_selector(".view-grid canvas.stage")
    pd.wait_for_timeout(800)
    drawn = pd.evaluate("window.__drawn")
    check("track: no year label past the newest image (2026)", "2026" in drawn and "2027" not in drawn, sorted({d for d in drawn if d.isdigit()}))
    pd.goto(BASE, wait_until="networkidle")
    pd.wait_for_selector(".hero-stage canvas")
    pd.wait_for_timeout(800)
    check("hero: the track labels end where its caption does", "2027" not in pd.evaluate("window.__drawn"))
    pd.goto(BASE + "?target=r-draconis&mode=simple", wait_until="networkidle")
    pd.wait_for_selector(".simple-bright:not([hidden])", timeout=10000)
    first = pd.evaluate("document.querySelector('.simple-answer h2').nextElementSibling.className")
    check("R Draconis: the answer leads with its brightness", first == "simple-bright" and "brightens and fades" in pd.inner_text(".simple-bright"), [first, pd.inner_text(".simple-answer")[:200]])

    def weak_motion(r):
        m2 = _j.loads(_j.dumps(base_m))
        m2["track"] = []
        m2["target"] = {**m2["target"], "pmra_masyr": None, "pmdec_masyr": None}
        m2["measured_motion"] = {**m2["measured_motion"], "pmra_masyr": 500.0, "pmdec_masyr": -350.0, "err_masyr": 950.0,
                                 "err_pmra_masyr": 950.0, "err_pmdec_masyr": 950.0, "baseline_years": 1.0, "n_detections": 3}
        r.fulfill(body=_j.dumps(m2), content_type="application/json")
    pw = page(b, reduced=True)
    pw.route("**/synthetic-fast-mover/manifest.json", weak_motion)
    pw.goto(BASE + "?target=synthetic-fast-mover&mode=full", wait_until="networkidle")
    pw.wait_for_selector(".verdict-strip")
    tile = pw.inner_text(".vtile[data-tile=motion]")
    check("insignificant motion: the strip says 'No motion we can measure', the figure and error below", "No motion we can measure" in tile and "0.61 ± 0.95" in tile and "within its error" in tile, tile)
    check("insignificant motion: no 'Use this motion'", pw.get_by_text("Use this motion").count() == 0)

    pn = page(b, fixtures=False)
    pn.route("**/js/config.js", lambda r: r.fulfill(body=cfg, content_type="text/javascript"))
    pn.route("**/api/**", lambda r: r.fulfill(status=404, body="not found"))
    pn.goto(BASE, wait_until="networkidle")
    pn.fill("#pos", "Teide 1")
    pn.click(".search button[type=submit]")
    pn.wait_for_selector(".form-msg:has-text('This copy of the site shows the built views only')", timeout=5000)
    check("no live server: a name outside the gallery says so in words, no HTTP code", "HTTP" not in pn.inner_text(".form-msg"), pn.inner_text(".form-msg"))
    pn.goto(BASE + "?ra=150.0123&dec=20.0046", wait_until="networkidle")
    pn.wait_for_selector(".banner", timeout=10000)
    check("no live server: a new position says so in words, no HTTP code", "built views only" in pn.inner_text(".banner") and "HTTP" not in pn.inner_text(".banner"), pn.inner_text(".banner"))
    pn.goto(BASE, wait_until="networkidle")
    pn.fill("#pos", "Right Ascension 08h55m10.831s, declination -7d14m42.53s")
    pn.wait_for_selector("#pos-suggest li", timeout=3000)
    pn.press("#pos", "Enter")
    pn.wait_for_url("**target=wise-0855-0714*", timeout=5000)
    check("brief position: Enter still opens WISE 0855-0714", "target=wise-0855-0714" in pn.url, pn.url)

    # 32. A view reached by name keeps the name, and ?name= (the sky map) asks the service exactly what the search box does
    unnamed = _j.dumps({**base_m, "target": {**base_m["target"], "name": None}})
    sesame = '{"resolved": true, "name": "* alf Ori", "ra": 88.79293899, "dec": 7.407064, "pmra": 27.54, "pmdec": 11.3, "epoch": 2000.0, "source": "CDS Sesame"}'
    asked = []

    def named_page():
        pq = page(b, fixtures=False, reduced=True)
        pq.route("**/js/config.js", lambda r: r.fulfill(body=cfg, content_type="text/javascript"))
        pq.route("**/api/resolve*", lambda r: r.fulfill(body=sesame, content_type="application/json"))
        pq.route("**/api/view*", lambda r: (asked.append(urllib.parse.urlparse(r.request.url).query), r.fulfill(body=unnamed, content_type="application/json")))
        pq.route("**/api/frames/**", frames)
        return pq
    pq = named_page()
    pq.goto(BASE, wait_until="networkidle")
    pq.fill("#pos", "betelgeuse")
    pq.click(".search button[type=submit]")
    pq.wait_for_selector(".form-msg:has-text('via CDS Sesame')", timeout=5000)
    pq.click(".search button[type=submit]")
    pq.wait_for_selector(".view h1", timeout=15000)
    check("by name (search box): the view is titled with the name, the position beneath it",
          pq.inner_text(".view h1") == "betelgeuse" and "label=betelgeuse" in pq.url and "RA " in pq.inner_text(".view-head"), [pq.inner_text(".view h1"), pq.url])
    pq.click(".mode-switch [data-mode=simple]")
    pq.wait_for_selector(".view.simple h1")
    check("by name: the simple view keeps the name", pq.inner_text(".view.simple h1") == "betelgeuse")
    pq2 = named_page()
    pq2.goto(BASE + "?name=betelgeuse", wait_until="networkidle")
    pq2.wait_for_selector(".view h1", timeout=15000)
    check("by name (?name=, the sky map): the same request to the service as the search box, and the same title",
          len(asked) == 2 and asked[0] == asked[1] and pq2.inner_text(".view h1") == "betelgeuse" and "name=" not in pq2.url.split("label=")[0], [asked, pq2.url])
    pq2.goto(BASE + "?ra=10&dec=5&label=%3Cimg%20src%3Dx%20onerror%3Dalert(1)%3E", wait_until="networkidle")
    pq2.wait_for_selector(".view h1", timeout=15000)
    check("a label is shown as text, never as markup", pq2.locator(".view h1 img").count() == 0 and "<img" in pq2.inner_text(".view h1"))

    # 33. Nothing found at a position: plain words, not our failure
    def blank(r):
        m2 = _j.loads(_j.dumps(base_m))
        m2["measured_motion"] = None
        m2["warnings"] = m2["warnings"] + ["The target was not detected in any frame."]
        for f in m2["frames"]:
            f["centroid_px"] = None
        r.fulfill(body=_j.dumps(m2), content_type="application/json")
    pz = page(b, reduced=True)
    pz.route("**/synthetic-fast-mover/manifest.json", blank)
    pz.goto(BASE + "?target=synthetic-fast-mover&mode=full", wait_until="networkidle")
    pz.wait_for_selector(".verdict-strip")
    tile = pz.inner_text(".vtile[data-tile=motion]")
    check("nothing found: the strip says nothing is visible here, and why that can happen", "Nothing visible here" in tile and "too faint or too blue" in tile, tile)
    pz.goto(BASE + "?target=synthetic-fast-mover&mode=simple", wait_until="networkidle")
    pz.wait_for_selector(".simple-answer")
    check("nothing found: the simple answer says it in plain words", pz.inner_text(".simple-motion").startswith("Nothing is visible at this position"), pz.inner_text(".simple-motion"))

    # 34. The landing in Advanced: a short first screen, and the hint never covers the nav or the switch
    pl2 = page(b, w=1440, h=900, fixtures=False)
    pl2.goto(BASE, wait_until="networkidle")
    n = pl2.evaluate(first_screen)
    check("landing (Advanced, 1440): at most 20 controls on the first screen", n <= 20, n)
    for w, h in ((1440, 900), (1024, 768), (768, 1024), (390, 844)):
        ph2 = page(b, w=w, h=h, fixtures=False, hint=True)
        ph2.goto(BASE, wait_until="networkidle")
        doc0 = ph2.evaluate("document.documentElement.scrollHeight")
        ph2.wait_for_selector(".mode-hint:not([hidden])", timeout=5000)
        r = ph2.evaluate("""() => { const h = document.querySelector('.mode-hint').getBoundingClientRect();
          const hit = (sel) => [...document.querySelectorAll(sel)].some((e) => { const q = e.getBoundingClientRect();
            return !(q.right <= h.left || q.left >= h.right || q.bottom <= h.top || q.top >= h.bottom); });
          return [hit('header.site nav a'), hit('.mode-switch > button'), h.right <= innerWidth, document.documentElement.scrollHeight]; }""")
        check(f"hint at {w}: covers neither the nav nor the switch, stays on screen, pushes nothing", r[:3] == [False, False, True] and r[3] == doc0, [r, doc0])
        if w == 1440:
            ph2.fill("#pos", "barn")
            ph2.wait_for_selector("#pos-suggest li")
            check("hint: steps aside while the suggestions are open", ph2.evaluate("getComputedStyle(document.querySelector('.mode-hint')).visibility") == "hidden")

    # 35. For the demo recording: the SPHEREx switch is in view at 1280x720, and ?frame= opens Simple on that image, paused
    pr = page(b, w=1280, h=720)
    pr.goto(BASE + "?target=synthetic-fast-mover&mode=simple", wait_until="networkidle")
    pr.wait_for_selector(".simple-missions")
    bot = pr.evaluate("document.querySelector('.simple-missions').getBoundingClientRect().bottom")
    check("simple 1280x720: the WISE and SPHEREx | SPHEREx only switch is visible with the picture", bot <= 720, bot)
    pr.goto(BASE + "?target=synthetic-fast-mover&mode=simple&frame=wise-w2-2019p40", wait_until="networkidle")
    pr.wait_for_selector(".simple-date")
    pr.wait_for_timeout(600)
    check("simple: ?frame= opens on that image, paused", "2019" in pr.inner_text(".simple-date") and pr.get_attribute("#simple-play", "aria-label") == "Play",
          pr.inner_text(".simple-date"))

    # 36. A hard field (docs/api.md `field`, `motion_not_measured`, `gaps_image`): glare leads, the thin
    # motion is "Not measured", and a frame with gaps is hatched in Advanced only.
    glare = ("This spot is so bright in the infrared that it overloads both WISE and SPHEREx: most of the images show glare and "
             "detector artefacts rather than the object itself, and the flat patches in them are where there is no usable measurement.")
    thin = "only 3 clean detections over 1.01 years; we need at least 4 over 3 years to tell motion from parallax and noise"
    gap_id = base_m["frames"][3]["id"]

    def hard_field(r):
        m2 = _j.loads(_j.dumps(base_m))
        m2.update(measured_motion=None, motion_not_measured={"reason": thin, "n_detections": 3, "baseline_years": 1.01},
                  field={"saturated": True, "saturated_missions": ["SPHEREx", "WISE"], "crowded": None},
                  warnings=[glare, f"Motion not measured: {thin}."] + m2["warnings"])
        m2["frames"][3].update(gaps_image=m2["frames"][3]["image"], no_data_fraction=0.3, no_data_near_target=1.0)
        r.fulfill(body=_j.dumps(m2), content_type="application/json")
    for w in (1440, 390):
        ph = page(b, w=w, h=900)
        ph.route("**/synthetic-fast-mover/manifest.json", hard_field)
        ph.goto(BASE + f"?mode=full&target=synthetic-fast-mover&frame={gap_id}", wait_until="networkidle")
        ph.wait_for_selector(".verdict-strip")
        ph.wait_for_timeout(300)
        order = ph.evaluate("""() => { const n = document.querySelector('.field-note'), s = document.querySelector('.verdict-strip');
          return !!n && !!(n.compareDocumentPosition(s) & Node.DOCUMENT_POSITION_FOLLOWING); }""")
        check(f"hard field {w}: the glare sentence is a banner above the verdict strip", order and ph.inner_text(".field-note") == glare, order)
        tile = ph.inner_text(".verdict-strip a.vtile[href='#motion']")
        check(f"hard field {w}: motion tile says Not measured, with the reason in a few words",
              "Not measured" in tile and "only 3 clean detections over 1.01 years" in tile and "parallax" not in tile, tile)
        check(f"hard field {w}: a frame with gaps is hatched, with one legend line", ph.locator(".hatch-legend").is_visible()
              and ph.inner_text(".hatch-legend") == "Hatched: no usable data here", ph.inner_text(".stage-wrap"))
        if w == 1440:
            box = ph.locator("fieldset.layers input").first
            check("hard field: the hatch layer is on by default and turns off", box.is_checked() and (box.uncheck() or True) and not ph.locator(".hatch-legend").is_visible())
        check(f"hard field {w}: console clean", not ph.msgs, ph.msgs)
        ps = page(b, w=w, h=900)
        ps.route("**/synthetic-fast-mover/manifest.json", hard_field)
        ps.goto(BASE + f"?mode=simple&target=synthetic-fast-mover&frame={gap_id}", wait_until="networkidle")
        ps.wait_for_selector(".simple-answer")
        first = ps.eval_on_selector(".simple-answer h2 + p", "e => e.textContent")
        check(f"hard field {w}: Simple's answer opens with the glare sentence", first == glare, first)
        check(f"hard field {w}: Simple says the motion was not measured, and draws no hatch",
              ps.inner_text(".simple-motion").startswith("We could not measure a motion: only 3 clean detections") and ps.locator(".hatch-legend").count() == 0,
              ps.inner_text(".simple-motion"))
        check(f"hard field {w}: Simple console clean", not ps.msgs, ps.msgs)
    pn = page(b)
    pn.goto(BASE + "?mode=full&target=synthetic-fast-mover", wait_until="networkidle")
    pn.wait_for_selector(".verdict-strip")
    check("hard field: a view without the new fields shows no banner, no hatch control turned on",
          pn.locator(".field-note").count() == 0 and not pn.locator(".hatch-legend").is_visible() and pn.locator("fieldset.layers input").first.is_disabled())
    check("field movers: absent block, no section", pn.locator(".field-movers").count() == 0)

    # 37. "What else moved in this patch?" from the field_movers block of a real WISE 0855 build
    # (web/tests/fixtures/fieldmovers), with a known Gaia mover and withheld candidates added.
    fm_real = _j.loads((WEB / "tests/fixtures/fieldmovers/wise-0855-0714.json").read_text())["field_movers"]
    fm_gaia = _j.loads(_j.dumps(fm_real))
    fm_gaia["movers"].append({**fm_gaia["movers"][0], "label": "gaia", "gaia_id": "5765384736386410240", "catwise_id": None,
                              "px": [60.0, 80.0], "epoch": 2016.0, "pmra_masyr": 150.2, "pmdec_masyr": -310.4, "err_masyr": 12.5,
                              "motion_arcsec_yr": 0.345})
    fm_gaia.update(n_known=1, n_candidates=2, candidates_withheld=True)

    def with_movers(block):
        def fulfil(r):
            m2 = _j.loads(_j.dumps(base_m))
            m2["field_movers"] = block
            r.fulfill(body=_j.dumps(m2), content_type="application/json")
        return fulfil
    for w in (1440, 390):
        pf = page(b, w=w, h=900)
        pf.route("**/synthetic-fast-mover/manifest.json", with_movers(fm_gaia))
        pf.goto(BASE + "?mode=full&target=synthetic-fast-mover", wait_until="networkidle")
        pf.wait_for_selector(".field-movers")
        txt = pf.inner_text(".field-movers")
        check(f"field movers {w}: the sentence, each known mover in plain words, the withheld count and the check line",
              fm_gaia["sentence"] in txt and "The target itself" in txt and "Gaia DR3 5765384736386410240, already known to move" in txt
              and "0.345 ± 0.01 arcsec a year towards the south-east" in txt
              and "2 tracks do not match any catalogue and are not shown" in txt and "shuffled the visit dates 10 times" in txt, txt)
        boxes = pf.locator(".field-movers input[type=checkbox]")
        before = pf.evaluate("document.querySelector('canvas.stage').toDataURL()")
        check(f"field movers {w}: rings are off by default", boxes.count() == 2 and not any(boxes.nth(i).is_checked() for i in range(2)))
        boxes.last.check()
        pf.wait_for_timeout(150)
        check(f"field movers {w}: a toggle rings the mover on the blink", pf.evaluate("document.querySelector('canvas.stage').toDataURL()") != before)
        check(f"field movers {w}: console clean", not pf.msgs, pf.msgs)
    ps = page(b, w=390, h=900)
    ps.route("**/synthetic-fast-mover/manifest.json", with_movers(fm_gaia))
    ps.goto(BASE + "?mode=simple&target=synthetic-fast-mover", wait_until="networkidle")
    ps.wait_for_selector(".simple-answer")
    check("field movers: Simple shows only the sentence", ps.locator(".field-movers").count() == 0
          and ps.locator(".field-movers-line").all_inner_texts() == [fm_gaia["sentence"]])
    pz = page(b)
    pz.route("**/synthetic-fast-mover/manifest.json", with_movers({"status": "not_searched", "reason": "fewer than 6 WISE visits",
                                                                  "movers": [], "sentence": "We could not search this patch for other movers."}))
    pz.goto(BASE + "?mode=full&target=synthetic-fast-mover", wait_until="networkidle")
    pz.wait_for_selector(".field-movers")
    check("field movers: not searched shows the reason in one line, no list", "Not searched: fewer than 6 WISE visits." in pz.inner_text(".field-movers")
          and pz.locator(".field-movers input").count() == 0, pz.inner_text(".field-movers"))

    # 37b. Surfacing the best parts: who it is for and the proof line on the home page, the fourth
    # verdict tile (search, or brightness on a variable star), the chance test high in the movers
    # block, Simple's share row in the answer card, and the nav's Archive uptime entry.
    vsum = _j.loads((WEB / "data" / "validation.json").read_text())["summary"]
    vm = vsum["motion"]
    proof = f"Checked on {vsum['targets']} objects with published values: {vm['passed']} of {vm['total']} motions agree" + (
        f", {vm['failed']} {'does' if vm['failed'] == 1 else 'do'} not." if vm["failed"] else ".")
    no_overflow = "document.documentElement.scrollWidth <= innerWidth"
    for mode in ("simple", "advanced"):
        for w in (1440, 390):
            tag = f"surface {mode} {w}"
            ph = page(b, w=w, h=900, fixtures=False)
            ph.goto(BASE + f"?mode={mode}", wait_until="networkidle")
            ph.wait_for_selector(".hero-proof:not([hidden])")
            who = ph.evaluate("(() => { const p = document.querySelector('.hero-who'); return [p.previousElementSibling.id, p.textContent]; })()")
            check(f"{tag}: one line on who it is for, straight under the question", who[0] == "hero-h" and "Backyard Worlds volunteers" in who[1]
                  and ph.locator(".hero-who").is_visible(), who)
            check(f"{tag}: the proof line, from validation.json, links to the results", ph.inner_text(".hero-proof") == proof
                  and ph.get_attribute(".hero-proof a", "href") == "validation.html" and ph.locator(".hero-proof").is_visible(), ph.inner_text(".hero-proof"))
            check(f"{tag}: home has no horizontal scroll", ph.evaluate(no_overflow))
            check(f"{tag}: home console clean", not ph.msgs, ph.msgs)
            ph.context.close()
    ph = page(b, fixtures=False)
    ph.route("**/data/validation.json", lambda r: r.fulfill(status=404, body="nope"))
    ph.goto(BASE, wait_until="networkidle")
    check("surface: no validation report, no proof line", not ph.locator(".hero-proof").is_visible())
    ph.context.close()
    for w in (1440, 390):
        pv = page(b, w=w, h=900, fixtures=False)
        pv.goto(BASE + "?mode=full&target=cwise-2029-7910", wait_until="networkidle")
        pv.wait_for_selector(".verdict-strip a.vtile[data-tile=search]")
        tiles = pv.eval_on_selector_all(".verdict-strip a.vtile", "e => e.map(a => [a.dataset.tile, a.getAttribute('href'), Math.round(a.getBoundingClientRect().top)])")
        check(f"search tile {w}: fourth, linked to the movers block, {'one row' if w > 600 else 'stacked'}",
              [t[:2] for t in tiles][3] == ["search", "#movers"] and pv.locator("#movers").count() == 1
              and (len({t[2] for t in tiles}) == 1 if w > 600 else len({t[2] for t in tiles}) == 4)
              and "blind search of this patch" in pv.inner_text(".vtile[data-tile=search]"), tiles)
        first = pv.evaluate("document.querySelector('#movers h2').nextElementSibling.nextElementSibling.className")
        check(f"search tile {w}: the chance test straight under the answer, at normal size", first == "movers-check"
              and "shuffled the visit dates" in pv.inner_text(".movers-check"), first)
        check(f"search tile {w}: no horizontal scroll", pv.evaluate(no_overflow))
        check(f"search tile {w}: console clean", not pv.msgs, pv.msgs)
        pv.goto(BASE + "?mode=full&target=r-draconis", wait_until="networkidle")
        pv.wait_for_selector(".verdict-strip a.vtile[data-tile=brightness]")
        tiles = pv.eval_on_selector_all(".verdict-strip a.vtile", "e => e.map(a => [a.dataset.tile, a.getAttribute('href')])")
        check(f"brightness tile {w}: the variable star's finding replaces the search tile", tiles[3:] == [["brightness", "#variability"]]
              and "246 days" in pv.inner_text(".vtile[data-tile=brightness]") and pv.locator("#variability").count() == 1, tiles)
        check(f"brightness tile {w}: no horizontal scroll", pv.evaluate(no_overflow))
        pv.goto(BASE + "?mode=simple&target=r-draconis", wait_until="networkidle")
        pv.wait_for_selector(".simple-answer")
        check(f"simple {w}: a variable star links to its brightness chart from the top",
              pv.get_attribute(".simple .view-head a[href='#variability']", "href") == "#variability")
        pv.goto(BASE + "?mode=simple&target=wise-0855-0714", wait_until="networkidle")
        pv.wait_for_selector(".simple-answer")
        btns = pv.locator(".simple-answer .simple-share button").all_inner_texts()
        check(f"simple {w}: the Talk summary and Copy link sit in the answer card", btns == ["Copy summary for Talk", "Copy link"], btns)
        check(f"simple {w}: the way into Advanced says what is there", "all bands, compare dates, overlays, embed" in pv.inner_text("#show-full"))
        check(f"simple {w}: no horizontal scroll", pv.evaluate(no_overflow))
        check(f"simple {w}: console clean", not pv.msgs, pv.msgs)
        pv.context.close()
    pc = page(b, fixtures=False, perms=True)
    pc.goto(BASE + "?mode=simple&target=wise-0855-0714", wait_until="networkidle")
    pc.click(".simple-share button:has-text('Copy link')")
    pc.wait_for_timeout(300)
    clip = pc.evaluate("navigator.clipboard.readText()")
    check("simple: Copy link copies this view's address", "target=wise-0855-0714" in clip and clip.startswith("http"), clip)
    pc.goto(BASE + "status.html", wait_until="networkidle")
    navs = pc.eval_on_selector_all("header.site nav a", "e => e.map(a => [a.getAttribute('aria-label'), a.getAttribute('href'), a.getAttribute('aria-current')])")
    check("nav: Archive uptime in place of Check a position, current on status.html",
          ["Archive uptime", "status.html", "page"] in navs and not any(n[0] == "Check a position" for n in navs) and len(navs) == 6, navs)
    pc.context.close()

    # 38. From the sky map with the name service down: a named star still opens (at the map's position, named),
    # and Back or "Back to the sky map" returns to the map exactly as it was, card open
    pe = page(b, fixtures=False, reduced=True)
    pe.route("**/js/config.js", lambda r: r.fulfill(body=cfg, content_type="text/javascript"))
    pe.route("**/api/resolve*", lambda r: r.fulfill(status=503, body='{"error": "The name service is down."}', content_type="application/json"))
    pe.route("**/api/body/resolve*", lambda r: r.fulfill(status=503, body='{"error": "The name service is down."}', content_type="application/json"))
    pe.route("**/api/view*", lambda r: r.fulfill(body=unnamed, content_type="application/json"))
    pe.route("**/api/frames/**", frames)
    pe.goto(BASE + "explore.html?ra=266.973&dec=2.707&zoom=12&pin=266.9730,2.7070", wait_until="networkidle")
    pe.wait_for_selector("#ex-card:not([hidden]) a.ex-go", timeout=10000)
    card_title = pe.inner_text("#ex-card .ex-card-title")
    go = pe.get_attribute("#ex-card a.ex-go", "href")
    check("map: a named star's card opens by name with the map's own position", card_title == "Muliphen" and go.startswith("index.html?name=Muliphen&at=266.9730,2.7070"), [card_title, go])
    pe.click("#ex-card a.ex-go")
    pe.wait_for_selector(".view h1", timeout=15000)
    check("name service down: the view opens at the map's position, named, never a dead end",
          pe.inner_text(".view h1") == "Muliphen" and "ra=266.973" in pe.url and "label=Muliphen" in pe.url and "name=" not in pe.url.split("label=")[0], pe.url)
    back = pe.get_attribute(".back-to-map", "href") or ""
    check("from the map: 'Back to the sky map' near the title, to the map as it was", back.startswith("explore.html?ra=266.973") and "pin=266.9730,2.7070" in back, back)
    pe.go_back()
    pe.wait_for_selector("#ex-card:not([hidden]) .ex-card-title", timeout=10000)
    check("browser Back: the map, same centre and zoom, the card open", "zoom=12" in pe.url and pe.inner_text("#ex-card .ex-card-title") == "Muliphen", pe.url)
    pe.go_forward()
    pe.wait_for_selector(".back-to-map", timeout=15000)
    pe.click(".mode-switch [data-mode=simple]")
    pe.wait_for_selector(".view.simple .back-to-map")
    pe.click(".back-to-map")
    pe.wait_for_selector("#ex-card:not([hidden]) .ex-card-title", timeout=10000)
    check("'Back to the sky map' (from Simple too): the same map and card", pe.inner_text("#ex-card .ex-card-title") == "Muliphen" and "zoom=12" in pe.url, pe.url)
    pe.goto(BASE + "?target=barnards-star", wait_until="networkidle")
    pe.wait_for_selector(".view h1", timeout=15000)
    check("a view not reached from the map has no way back to it", pe.locator(".back-to-map").count() == 0)

    # 39. The map by the nav opens its home view; Reset view returns there exactly
    for w, h in ((1440, 900), (390, 844)):
        pk = page(b, w=w, h=h, fixtures=False, reduced=True)
        pk.goto(BASE + "explore.html", wait_until="networkidle")
        pk.wait_for_function("window.__explore && window.__explore.state")
        home = pk.evaluate("window.__explore.state")
        pk.evaluate("document.querySelector('#ex-zoom-in, [aria-label=\"Zoom in\"]')?.click()")
        pk.mouse.move(w / 2, h / 2)
        pk.mouse.wheel(0, -600)
        pk.wait_for_timeout(300)
        pk.click("#ex-reset")
        pk.wait_for_timeout(600)
        again = pk.evaluate("window.__explore.state")
        same = all(abs(home[k] - again[k]) < 0.01 for k in ("ra", "dec", "fov"))
        check(f"map {w}: arriving by the nav opens the home view, and Reset view returns to it exactly", same, [home, again])

    # 40. Archive uptime (js/archivestatus.js, js/status.js; the saved checks at /api/archives, stubbed):
    # by the Check form, Simple shows a sentence only when one is down and Advanced a compact row
    # whose panel opens on hover, focus and tap; a failing route shows nothing; old checks show only
    # when they ran. status.html: 30 day blocks, a day opens its hours, an hour its checks. A degraded
    # live view gets the note; a gallery view does not, and makes no call.
    import datetime as _dt
    live_cfg = "export const API_BASE = '/';\nexport const LIVE_TIMEOUT_MS = 150000;\n"
    down_sentence = "NASA IRSA image search is not answering right now"

    def archives_body(sia, age_s=120):
        now = int(_dt.datetime.now(_dt.UTC).timestamp()) - age_s
        iso = lambda t: _dt.datetime.fromtimestamp(t, _dt.UTC).isoformat().replace("+00:00", "Z")
        times = [now - 300 * i for i in range(287, -1, -1)]
        codes = "".join("d" if 100 <= i < 110 else "s" if i == 5 else "u" for i in range(288))
        today = iso(now)[:10]
        yday = iso(now - 86400)[:10]
        rows = [("irsa_sia", "NASA IRSA image search", "WISE and SPHEREx images", sia, False),
                ("gaia", "ESA Gaia archive", "Gaia stars", "up", False),
                ("datalab", "NOIRLab Astro Data Lab", "backup copies of Gaia and CatWISE", "up", True),
                ("horizons", "JPL Horizons", "Solar System body positions", "up", False)]
        ids = [r[0] for r in rows]
        return json.dumps({
            "checked_at": iso(now),
            "archives": [{"id": i, "name": n, "used_for": u, "backup": bk, "status": s, "latency_ms": None if s == "down" else 400,
                          "detail": "HTTP 502" if s == "down" else None} for i, n, u, s, bk in rows],
            "history": {i: {"checks": 400, "answered": 390, "since": f"{yday}T00:00:00Z", "failed_last_hour": 0} for i in ids},
            "checks": {"times": times, "archives": {i: {"codes": codes if i == "irsa_sia" else "u" * 288, "ms": [400] * 288,
                                                         "fail": {str(k): "HTTP 502" for k in range(100, 110)} if i == "irsa_sia" else {}} for i in ids}},
            "days": {"dates": [yday, today], "archives": {i: [[288, 280, 2], [200, 190, 1]] for i in ids}}})

    def answer_with(body=None, status=200):
        return lambda r: r.fulfill(status=status, body=body if body is not None else "<html>oops</html>", content_type="application/json")

    def archives_page(w, answer, calls):
        pa = page(b, w=w, h=900)
        pa.route("**/js/config.js", lambda r: r.fulfill(body=live_cfg, content_type="text/javascript"))
        pa.route("**/api/archives*", lambda r: (calls.append(r.request.url), answer(r)))
        return pa

    def shown(pa, sel):
        loc = pa.locator(sel)
        return [loc.nth(i).inner_text() for i in range(loc.count()) if loc.nth(i).is_visible()]

    cases = (("all up", answer_with(archives_body("up"))), ("one down", answer_with(archives_body("down"))),
             ("route failing", answer_with(status=500)), ("stale", answer_with(archives_body("down", age_s=45 * 60))))
    for label, answer in cases:
        for mode in ("simple", "advanced"):
            for w in (1440, 390):
                calls = []
                pa = archives_page(w, answer, calls)
                pa.goto(BASE + f"?mode={mode}", wait_until="networkidle")
                pa.wait_for_timeout(300)
                tag = f"archives {label}, {mode} {w}"
                check(f"{tag}: the Check page asks once", len(calls) == 1, calls)
                simple_line, row = shown(pa, ".archives-simple"), shown(pa, ".arch-row")
                heads = shown(pa, ".archives-h")
                want = label != "route failing" and (mode == "advanced" or label == "one down")
                check(f"{tag}: the 'Archive uptime' heading {'over the row' if want else 'not shown'}",
                      len(heads) == (1 if want else 0) and all(h.lower() == "archive uptime" for h in heads), heads)
                if label == "route failing":
                    check(f"{tag}: nothing shown", not shown(pa, ".archives"))
                elif label == "stale":
                    lines = shown(pa, ".archives")
                    check(f"{tag}: old checks: no state, only when they ran (Advanced)",
                          not simple_line and not row and (mode == "simple" and not lines or mode == "advanced" and len(lines) == 1 and "Archive checks last ran at" in lines[0]), lines)
                elif mode == "simple":
                    check(f"{tag}: a sentence only when one is down, with its time and the status link, no row",
                          not row and (bool(simple_line) == (label == "one down"))
                          and all(t.startswith(down_sentence) and "Checked at" in t and t.endswith("Archive uptime") for t in simple_line), simple_line)
                else:
                    box = pa.locator(".arch-row").bounding_box()
                    text = row[0] if row else ""
                    check(f"{tag}: a compact row, {'one line' if w > 600 else 'two lines at most'}, the backup only when failing",
                          not simple_line and box and box["height"] <= (30 if w > 600 else 48) and "Data Lab" not in text
                          and (("down" in text) == (label == "one down")) and (w > 600 or "answering" in text), [text, box])
                    pa.screenshot(path=f"{IMG}/archives-{label.replace(' ', '-')}-{mode}-{w}.png", clip={"x": 0, "y": max(0, box["y"] - 260), "width": w, "height": 520})
                check(f"{tag}: no horizontal scroll", pa.evaluate("document.documentElement.scrollWidth") <= w)
                check(f"{tag}: console clean", not [m for m in pa.msgs if "500" not in m], pa.msgs)
                pa.context.close()

    # The panel: hover, focus and tap open it over the page; mouse-out, Escape and a tap elsewhere close it.
    for w in (1440, 390):
        calls = []
        pa = archives_page(w, answer_with(archives_body("down")), calls)
        pa.goto(BASE + "?mode=advanced", wait_until="networkidle")
        pa.wait_for_selector(".arch-row")
        below = pa.locator(".archives").evaluate("n => n.parentElement.getBoundingClientRect().height")
        pa.hover(".arch-row")
        opened = pa.locator(".arch-panel").is_visible()
        pbox = pa.locator(".arch-panel").bounding_box() if opened else None
        same = pa.locator(".archives").evaluate("n => n.parentElement.getBoundingClientRect().height") == below
        texts = shown(pa, ".arch-panel")
        check(f"archives panel {w}: hover opens it, over the page, inside the viewport, with names, uses, states and the time",
              opened and same and pbox and pbox["x"] >= 0 and pbox["x"] + pbox["width"] <= w
              and texts and "ESA Gaia archive" in texts[0] and "Used for Gaia stars" in texts[0] and "not answering" in texts[0] and "Checked at" in texts[0], [pbox, same, texts])
        pa.screenshot(path=f"{IMG}/archives-panel-{w}.png", clip={"x": 0, "y": max(0, pbox["y"] - 200) if pbox else 0, "width": w, "height": 640})
        pa.mouse.move(2, 2)
        check(f"archives panel {w}: mouse-out closes it", not pa.locator(".arch-panel").is_visible())
        pa.focus(".arch-row")
        check(f"archives panel {w}: keyboard focus opens it", pa.locator(".arch-panel").is_visible())
        pa.keyboard.press("Escape")
        check(f"archives panel {w}: Escape closes it", not pa.locator(".arch-panel").is_visible())
        pa.mouse.click(2, 2)
        pa.locator(".arch-row").dispatch_event("click")
        check(f"archives panel {w}: a tap opens it", pa.locator(".arch-panel").is_visible())
        pa.mouse.click(2, 2)
        check(f"archives panel {w}: a tap elsewhere closes it", not pa.locator(".arch-panel").is_visible())
        check(f"archives panel {w}: Learn more goes to the status page",
              pa.locator(".arch-panel a", has_text="Learn more").get_attribute("href") == "status.html")
        pa.context.close()

    # status.html: both modes, 1440 and 390; Advanced: a day opens its hours, an hour its checks.
    for mode in ("simple", "advanced"):
        for w in (1440, 390):
            calls = []
            pa = archives_page(w, answer_with(archives_body("down")), calls)
            pa.goto(BASE + f"status.html?mode={mode}", wait_until="networkidle")
            pa.wait_for_selector(".status-page")
            tag = f"status page {mode} {w}"
            lead = pa.inner_text(".status-page .answer")
            days = pa.locator(".status-row").first.locator(".arch-blocks .arch-block")
            check(f"{tag}: the state first, every archive listed", lead.startswith(down_sentence) and pa.locator(".status-row").count() == 4, lead)
            if mode == "simple":
                check(f"{tag}: no blocks in Simple", not days.first.is_visible())
            else:
                labels = [days.nth(i).get_attribute("aria-label") for i in range(days.count())]
                check(f"{tag}: 30 labelled day blocks, days before watching empty", len(labels) == 30 and labels[0].endswith("no checks") and "of 200 checks answered" in labels[-1], labels[-2:])
                summary = shown(pa, ".status-row:first-child .status-adv p.small")
                check(f"{tag}: the 30-day share and the longest gap", summary and summary[0].startswith("Since ") and ": answered 470 of 488 checks, 96%" in summary[0] and "longest gap" in summary[0], summary)
                days.nth(29).click()
                hours = pa.locator(".status-row").first.locator(".arch-hours-row .arch-block")
                check(f"{tag}: a day opens its 24 hours", hours.count() == 24, hours.count())
                full = next((i for i in range(24) if "12 of 12" in (hours.nth(i).get_attribute("aria-label") or "") or "of 12 checks" in (hours.nth(i).get_attribute("aria-label") or "")), None)
                if full is not None:
                    hours.nth(full).click()
                    items = pa.locator(".arch-checks li")
                    check(f"{tag}: an hour lists its checks with time, state and response", items.count() == 12 and re.match(r"\d\d:\d\d (answering|slow|not answering)", items.first.inner_text()), [items.count(), items.first.inner_text()])
                    pa.keyboard.press("Escape")
                    check(f"{tag}: Escape closes the hour", pa.locator(".arch-checks").count() == 0)
                else:
                    check(f"{tag}: an hour with 12 checks today", False, [hours.nth(i).get_attribute("aria-label") for i in range(24)])
            check(f"{tag}: no horizontal scroll", pa.evaluate("document.documentElement.scrollWidth") <= w)
            check(f"{tag}: console clean", not pa.msgs, pa.msgs)
            pa.screenshot(path=f"{IMG}/status-{mode}-{w}.png", full_page=True)
            pa.context.close()

    degraded_m = json.dumps({**json.loads((FIX / "synthetic-fast-mover/manifest.json").read_text()), "degraded": True})

    def fixture_frames(r):
        r.fulfill(path=FIX / "synthetic-fast-mover/frames" / r.request.url.split("/api/frames/")[-1])
    down = answer_with(archives_body("down"))
    for mode in ("full", "simple"):
        calls = []
        pa = archives_page(1280, down, calls)
        pa.route("**/api/view*", lambda r: r.fulfill(body=degraded_m, content_type="application/json"))
        pa.route("**/api/frames/**", fixture_frames)
        pa.goto(BASE + f"?mode={mode}&ra=150.0123&dec=20.0046", wait_until="networkidle")
        pa.wait_for_timeout(500)
        notes = shown(pa, ".archive-note")
        check(f"archives: degraded live view ({mode}) names the archive that is down, once, not JPL, with the status link",
              len(notes) == 1 and notes[0].startswith(down_sentence) and "JPL" not in notes[0] and notes[0].endswith("Archive uptime"), notes)
        pa.context.close()
        calls = []
        pa = archives_page(1280, down, calls)
        pa.route("**/synthetic-fast-mover/manifest.json", lambda r: r.fulfill(body=degraded_m, content_type="application/json"))
        pa.goto(BASE + f"?mode={mode}&target=synthetic-fast-mover", wait_until="networkidle")
        pa.wait_for_timeout(500)
        check(f"archives: degraded gallery view ({mode}) has no note and makes no call", not shown(pa, ".archive-note") and not calls, calls)
        pa.context.close()

    # 41. Usability from the relevance critique: the image comes back after a control under it,
    # compare opens on a pair that shows motion, the catalogue overlays sit by Follow, the hint covers nothing
    w0855 = json.loads((WEB / "gallery/wise-0855-0714/manifest.json").read_text())
    w2 = sorted((f for f in w0855["frames"] if f["band"] == "W2"), key=lambda f: f["mjd"])
    stage_seen = """() => { const r = document.querySelector('.stage-wrap').getBoundingClientRect();
      return (Math.min(r.bottom, innerHeight) - Math.max(r.top, 0)) / Math.min(r.height, innerHeight); }"""
    for w, h in ((1440, 900), (390, 844)):
        pu = page(b, w=w, h=h, fixtures=False, more=False, reduced=True)
        pu.goto(BASE + "?target=wise-0855-0714&mode=advanced", wait_until="networkidle")
        pu.wait_for_selector("canvas.stage")
        # Scrolled down to the set buttons, as a reader is when they reach for them: the image is off screen.
        pu.evaluate("window.scrollTo(0, document.querySelector('.presets-box').getBoundingClientRect().top + scrollY - 40)")
        pu.click("button[data-preset=spherex-all]")
        pu.wait_for_timeout(300)
        seen = pu.evaluate(stage_seen)
        check(f"keep in view at {w}: after an image-set click the image is back on screen", seen >= 0.95, seen)
        pu.evaluate("window.scrollTo(0, document.querySelector('.compare-box').getBoundingClientRect().top + scrollY - 40)")
        pu.click(".compare-box > button")
        pu.wait_for_timeout(300)
        seen = pu.evaluate(stage_seen)
        check(f"keep in view at {w}: after Compare two dates the image is back on screen", seen >= 0.95, seen)
        q = urllib.parse.parse_qs(urllib.parse.urlparse(pu.url).query)
        check(f"compare at {w}: from All SPHEREx bands it opens on one SPHEREx set, first against last",
              q["a"][0].startswith("spx-") and q["a"][0].split("-")[1] == q["b"][0].split("-")[1] and q["a"] != q["b"], q)
        quick = pu.locator(".blink .controls .quick-layers")
        check(f"overlays at {w}: Gaia stars and CatWISE sources beside Follow, with More controls closed",
              quick.is_visible() and pu.get_attribute("details.more-controls", "open") is None
              and quick.inner_text().split() == ["Gaia", "stars", "CatWISE", "sources"], quick.inner_text())
        pu.click(".quick-layers input[data-layer=gaia]")
        full = pu.locator("fieldset.layers input[data-layer=gaia]")
        check(f"overlays at {w}: the quick toggle and the full list stay in step", full.is_checked())
        pu.click("details.more-controls > summary")
        full.click()
        check(f"overlays at {w}: unticking in the full list unticks the quick toggle", not pu.locator(".quick-layers input[data-layer=gaia]").is_checked())
        check(f"usability at {w}: no horizontal scroll, console clean", pu.evaluate("document.documentElement.scrollWidth <= innerWidth") and not pu.msgs, pu.msgs)
        pu.context.close()

    pc = page(b, w=1440, h=900, fixtures=False)
    pc.goto(BASE + "?target=wise-0855-0714&mode=advanced", wait_until="networkidle")
    pc.wait_for_selector("canvas.stage")
    pc.click(".compare-box > button")
    pc.wait_for_timeout(300)
    q = urllib.parse.parse_qs(urllib.parse.urlparse(pc.url).query)
    msg = pc.inner_text(".cmp-msg")
    check("compare: the default blink opens on the first and last WISE W2 images (2010 against 2024)",
          q.get("a") == [w2[0]["id"]] and q.get("b") == [w2[-1]["id"]], q)
    check("compare: one line says what the two dates are", msg.startswith("B − A: A is ") and "2010" in msg and "2024" in msg and "14 years apart" in msg, msg)
    pc.context.close()

    pn = page(b, more=False)
    pn.goto(BASE + "?target=synthetic-no-motion&mode=advanced", wait_until="networkidle")
    pn.wait_for_selector("canvas.stage")
    cw = pn.locator(".quick-layers input[data-layer=catwise]")
    check("overlays: with no CatWISE sources the quick toggle is shown, disabled, with the reason",
          cw.is_visible() and cw.is_disabled() and "CatWISE sources (none)" in pn.inner_text(".quick-layers"), pn.inner_text(".quick-layers"))
    pn.context.close()

    covers = """() => { const h = document.querySelector('.mode-hint').getBoundingClientRect();
      const hits = (q) => !(q.right <= h.left || q.left >= h.right || q.bottom <= h.top || q.top >= h.bottom);
      const out = [];
      for (const e of document.querySelectorAll('header.site nav a, .mode-switch > button, main button, main a, main input, main select, main summary'))
        if (hits(e.getBoundingClientRect())) out.push(e.tagName + ' ' + e.textContent.trim().slice(0, 30));
      const walk = document.createTreeWalker(document.querySelector('main'), NodeFilter.SHOW_TEXT);
      for (let n = walk.nextNode(); n; n = walk.nextNode()) {
        if (!n.textContent.trim()) continue;
        const r = document.createRange(); r.selectNodeContents(n);
        if ([...r.getClientRects()].some(hits)) out.push('text ' + n.textContent.trim().slice(0, 30));
      }
      return out; }"""
    for w, h in ((1440, 900), (390, 844)):
        ph = page(b, w=w, h=h, fixtures=False, hint=True)
        ph.goto(BASE + "?target=wise-0855-0714", wait_until="networkidle")
        ph.wait_for_selector(".mode-hint:not([hidden])", timeout=5000)
        ph.wait_for_timeout(500)
        ph.screenshot(path=f"{IMG}/web-hint-{w}.png")
        covered = ph.evaluate(covers)
        check(f"hint at {w} on a view: covers no text and no control", covered == [], covered)
        ph.mouse.click(w // 2, h - 20)
        ph.wait_for_timeout(200)
        check(f"hint at {w}: a tap elsewhere sends it away", ph.locator(".mode-hint").count() == 0)
        ph.context.close()
    for w, h in ((1440, 900), (390, 844)):
        ps = page(b, w=w, h=h, fixtures=False, hint=True)
        ps.goto(BASE + "?target=wise-0855-0714&mode=simple", wait_until="networkidle")
        ps.wait_for_timeout(2500)
        check(f"hint at {w}: never shown in Simple", ps.locator(".mode-hint").count() == 0)
        ps.context.close()

    def pressed(p):
        return p.get_attribute(".mode-switch [aria-pressed=true]", "data-mode")
    ps = page(b, fixtures=False)
    ps.goto(BASE + "?mode=simple", wait_until="networkidle")
    ps.fill("#pos", "Barnard")
    ps.press("#pos", "Enter")
    ps.wait_for_selector(".view", timeout=15000)
    ps.wait_for_timeout(300)
    check("mode=simple sticks: a name search opens its result in Simple",
          ps.locator(".view.simple").count() == 1 and pressed(ps) == "simple", [ps.url, pressed(ps)])
    ps.click("header.site nav a[href*='explore']")
    ps.wait_for_load_state("networkidle")
    check("mode=simple sticks: a nav link keeps Simple", pressed(ps) == "simple", [ps.url, pressed(ps)])
    ps.goto(BASE, wait_until="networkidle")
    check("mode=simple sticks: the home page with no parameter stays Simple", pressed(ps) == "simple")
    ps.click(".mode-switch [data-mode=advanced]")
    ps.goto(BASE + "?target=wise-0855-0714", wait_until="networkidle")
    check("mode: switching to Advanced is remembered the same way", pressed(ps) == "advanced" and ps.locator(".view.simple").count() == 0)
    ps.goto(BASE + "?target=wise-0855-0714&mode=simple", wait_until="networkidle")
    ps.goto(BASE + "?target=barnards-star", wait_until="networkidle")
    check("mode: a later ?mode=simple link is a new choice, remembered", pressed(ps) == "simple")
    ps.context.close()
    pfresh = page(b, fixtures=False)
    pfresh.goto(BASE + "?target=wise-0855-0714", wait_until="networkidle")
    check("mode: a fresh visit with no parameter still opens Advanced", pressed(pfresh) == "advanced")
    pfresh.context.close()

    ph = page(b, w=390, h=844, fixtures=False, hint=True)
    ph.goto(BASE + "?target=wise-0855-0714", wait_until="networkidle")
    ph.wait_for_selector(".mode-hint:not([hidden])", timeout=5000)
    ph.wait_for_timeout(6500)
    check("hint: goes by itself after a few seconds", ph.locator(".mode-hint").count() == 0)
    ph.reload(wait_until="networkidle")
    ph.wait_for_timeout(2500)
    check("hint: shown once only", ph.locator(".mode-hint").count() == 0)
    ph.context.close()

    b.close()

for name, ok, info in results:
    print("PASS" if ok else "FAIL", name, "" if ok else info)
print(sum(r[1] for r in results), "/", len(results))
