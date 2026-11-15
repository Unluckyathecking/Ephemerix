"""Headless checks of web/explore.html (the sky map) against the real gallery.

Serve web/ first (python3 -m http.server 8847 --directory web), then:
  uv run --with playwright python web/tools/check_explore.py <screenshot_dir>
SITE_BASE picks another server; CHROMIUM points at a browser binary to skip Playwright's download.
"""

import os
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

EXE = os.environ.get("CHROMIUM") or None
BASE = os.environ.get("SITE_BASE", "http://localhost:8847/")
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
results = []



def NO_ARCHIVES(route):
    """The saved archive checks are not served by the static test server; answer as if none exist."""
    route.fulfill(body="{}", content_type="application/json")

def check(name, ok, info=""):
    results.append((name, bool(ok), info))


def state(page):
    return page.evaluate("window.__explore && window.__explore.state")


def wait_ready(page):
    page.wait_for_function("window.__explore && document.getElementById('ex-loading').hidden", timeout=15000)


def marker_point(page, slug):
    """Screen position (page coordinates) of a gallery marker in the current frame."""
    return page.evaluate(
        """(slug) => {
          const f = window.__explore.frame, list = [...document.querySelectorAll('#ex-list a')];
          const i = list.findIndex((a) => a.href.endsWith('target=' + slug));
          const p = f.targets[i];
          if (!p) return null;
          const r = document.getElementById('ex-sky').getBoundingClientRect();
          return { x: r.left + p.x, y: r.top + p.y };
        }""",
        slug,
    )


def p95(xs):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(0.95 * len(xs)))]


def drag_and_time(page, url):
    """Load a view, drag across it for 60 moves and return the redraw times (ms)."""
    page.goto(BASE + url)
    wait_ready(page)
    page.wait_for_timeout(200)
    box = page.locator("#ex-sky").bounding_box()
    cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    page.evaluate("window.__explore.drawTimes.length = 0")
    page.mouse.move(cx, cy)
    page.mouse.down()
    for i in range(60):
        page.mouse.move(cx - 5 * i, cy + 2 * (i % 20))
        page.wait_for_timeout(16)
    page.mouse.up()
    return page.evaluate("window.__explore.drawTimes.slice()")


def check_draw_times(page, label):
    """A redraw must fit well inside a 16.7 ms frame while panning, zoomed out and zoomed in."""
    budget = 10 if not label else 16
    for name, url in (("whole sky", "explore.html"), ("30 degrees", "explore.html?ra=83.8&dec=-5.4&zoom=12")):
        times = drag_and_time(page, url)
        check(f"redraw p95 under {budget} ms panning the {name}{label}", times and p95(times) < budget,
              f"p95 {p95(times):.1f} ms, max {max(times):.1f} ms over {len(times)} draws" if times else "no draws")


def known_point(page, label):
    """Screen position of a name-index marker (cyan diamond), or None."""
    return page.evaluate(
        """(label) => {
          const items = [...document.querySelectorAll('#ex-known .ex-known-name')].map((n) => n.textContent);
          const p = window.__explore.frame.known[items.indexOf(label)];
          if (!p) return null;
          const r = document.getElementById('ex-sky').getBoundingClientRect();
          return { x: r.left + p.x, y: r.top + p.y };
        }""",
        label,
    )


def check_round_two(page):
    """Name-index markers, alias search, the mover button, the motion arrow, title and footer."""
    page.goto(BASE + "explore.html")
    wait_ready(page)
    page.wait_for_timeout(300)
    check("page title follows the site pattern", page.title().startswith("Explore the sky · "), page.title())
    check("34 objects we can build are listed", page.locator("#ex-known li").count() == 34)
    check("the mover button is visible on arrival", page.locator("#ex-move").is_visible())
    page.locator("#ex-move").click()
    page.wait_for_timeout(1800)
    card = page.locator("#ex-card")
    href = card.locator("a.ex-go").get_attribute("href") if card.is_visible() else None
    check("'something that moves' opens a built view's card", href and href.startswith("index.html?target="), href)
    check("after one press the button offers another", page.text_content("#ex-move").strip() == "Show me another", page.text_content("#ex-move"))
    page.locator(".ex-close").click()

    page.fill("#ex-q", "gj 551")
    opt = page.locator("#ex-results .ex-opt").first
    check("search finds Proxima Centauri by an alias", "Proxima Centauri" in opt.inner_text(), opt.inner_text())
    page.keyboard.press("Enter")
    page.wait_for_timeout(1800)
    href = card.locator("a.ex-go").get_attribute("href") if card.is_visible() else ""
    check("its card builds a live view with proper motion", (href or "").startswith("index.html?ra=") and "pmra=" in href, href)
    check("the card says about a minute", "about a minute" in card.inner_text())
    page.locator(".ex-close").click()
    page.wait_for_timeout(200)
    p = known_point(page, "Proxima Centauri")
    if p:
        page.mouse.click(p["x"], p["y"])
        page.wait_for_timeout(300)
    check("tapping a cyan diamond opens its card", p and "Proxima Centauri" in card.inner_text(), p)

    page.goto(BASE + "explore.html?target=barnards-star&zoom=180")
    wait_ready(page)
    page.wait_for_timeout(300)
    paths = page.evaluate("window.__explore.frame.paths")
    check("zoomed right in, Barnard's Star shows its 2010-2026 path", paths >= 1, paths)
    page.locator(".ex-close").click()
    page.wait_for_timeout(200)
    page.screenshot(path=str(OUT / "explore-1440-path.png"))

    page.goto(BASE + "index.html")
    page.wait_for_timeout(800)
    home_footer = page.locator("footer.site").inner_text()
    page.goto(BASE + "explore.html")
    wait_ready(page)
    check("footer matches the other pages", page.locator("footer.site").inner_text() == home_footer and len(home_footer) > 40)


def run_desktop(browser, errors):
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    page.route("**/api/archives", NO_ARCHIVES)
    page.on("console", lambda m: m.type in ("error", "warning") and errors.append(m.text))
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE + "explore.html")
    wait_ready(page)
    page.wait_for_timeout(300)
    s0 = state(page)
    check("whole sky at start", s0["fov"] > 300, s0)
    check("text list names all 19 views", page.locator("#ex-list a").count() == 19)
    page.screenshot(path=str(OUT / "explore-1440.png"))

    box = page.locator("#ex-sky").bounding_box()
    cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    page.mouse.move(cx, cy + 100)
    page.mouse.down()
    for i in range(1, 11):
        page.mouse.move(cx + 20 * i, cy + 100)
    page.mouse.up()
    s1 = state(page)
    check("drag pans in RA", abs(s1["ra"] - s0["ra"]) > 5, (s0["ra"], s1["ra"]))
    check("a drag does not drop a pin", page.locator("#ex-card").is_hidden())

    for _ in range(6):
        page.mouse.wheel(0, -300)
        page.wait_for_timeout(30)
    page.wait_for_timeout(300)
    s2 = state(page)
    check("wheel zooms in", s2["fov"] < s1["fov"] / 3, (s1["fov"], s2["fov"]))

    check_draw_times(page, "")
    cdp = page.context.new_cdp_session(page)
    cdp.send("Emulation.setCPUThrottlingRate", {"rate": 4})
    check_draw_times(page, " with the CPU slowed 4x")
    cdp.send("Emulation.setCPUThrottlingRate", {"rate": 1})

    page.goto(BASE + "explore.html?target=barnards-star")
    wait_ready(page)
    check("?target= opens its card", "Barnard" in page.locator("#ex-card").inner_text())
    page.locator(".ex-close").click()
    page.wait_for_timeout(200)
    p = marker_point(page, "barnards-star")
    check("Barnard's Star marker is on screen", p is not None, p)
    if p:
        page.mouse.click(p["x"], p["y"])
        page.wait_for_timeout(600)
        card = page.locator("#ex-card")
        check("marker tap shows the card", card.is_visible() and "Barnard" in card.inner_text())
        href = card.locator("a.ex-go").get_attribute("href")
        check("card links to the view", href == "index.html?target=barnards-star", href)
        check("card gives our measured motion", "We measured it moving" in card.inner_text(), card.inner_text())
        page.screenshot(path=str(OUT / "explore-1440-card.png"))

    page.mouse.click(box["x"] + 200, box["y"] + box["height"] - 120)
    page.wait_for_timeout(200)
    pin = page.locator("#ex-card a.ex-go")
    href = pin.get_attribute("href") or ""
    check("empty-sky tap drops a pin that builds a view", href.startswith("index.html?ra="), href)
    check("pin says about a minute", "about a minute" in pin.inner_text())

    page.fill("#ex-q", "vega")
    page.keyboard.press("Enter")
    page.wait_for_timeout(1800)
    s3 = state(page)
    check("search flies to Vega", abs(s3["ra"] - 279.23) < 1 and abs(s3["dec"] - 38.78) < 1, s3)

    page.locator("#ex-sky").focus()
    snap = "document.getElementById('ex-sky').toDataURL()"
    before, pixels = state(page), page.evaluate(snap)
    page.keyboard.press("ArrowLeft")
    page.wait_for_timeout(100)
    moved, pixels_moved = state(page), page.evaluate(snap)
    page.keyboard.press("+")
    page.wait_for_timeout(100)
    after, pixels_zoomed = state(page), page.evaluate(snap)
    check("keyboard pans and zooms", moved["ra"] != before["ra"] and after["fov"] < moved["fov"], (before, after))
    check("arrow and plus visibly redraw the map", pixels != pixels_moved and pixels_moved != pixels_zoomed)

    check_round_two(page)

    page.goto(BASE + "explore.html?ra=83.82&dec=-5.39&zoom=10")
    wait_ready(page)
    page.wait_for_timeout(200)
    page.screenshot(path=str(OUT / "explore-1440-orion.png"))
    page.goto(BASE + "explore.html?ra=83.82&dec=-5.39&zoom=36")
    wait_ready(page)
    s4 = state(page)
    check("?ra=&dec=&zoom= centres the map", abs(s4["ra"] - 83.82) < 0.01 and abs(s4["fov"] - 10) < 0.01, s4)
    page.close()


def run_phone(browser, errors):
    ctx = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, has_touch=True, is_mobile=True)
    ctx.route("**/api/archives", NO_ARCHIVES)
    page = ctx.new_page()
    page.on("console", lambda m: m.type in ("error", "warning") and errors.append(m.text))
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE + "explore.html")
    wait_ready(page)
    page.wait_for_timeout(300)
    sw = page.evaluate("document.documentElement.scrollWidth")
    check("no horizontal scroll at 390 px", sw <= 390, sw)
    page.screenshot(path=str(OUT / "explore-390.png"))
    check_phone_first_screen(page)
    page.goto(BASE + "explore.html?target=wise-0855-0714")
    wait_ready(page)
    page.wait_for_timeout(600)
    page.screenshot(path=str(OUT / "explore-390-card.png"))
    page.locator(".ex-close").tap()
    p = marker_point(page, "wise-0855-0714")
    if p:
        page.touchscreen.tap(p["x"], p["y"])
        page.wait_for_timeout(300)
    check("a finger tap on a marker opens its card", p and "WISE 0855" in page.locator("#ex-card").inner_text(), p)
    sw = page.evaluate("document.documentElement.scrollWidth")
    check("no horizontal scroll with a card open", sw <= 390, sw)
    page.screenshot(path=str(OUT / "explore-390-full.png"), full_page=True)
    pinch(page)
    ctx.close()


def boxes_overlap(a, b):
    return a["x"] < b["x"] + b["width"] and b["x"] < a["x"] + a["width"] and a["y"] < b["y"] + b["height"] and b["y"] < a["y"] + a["height"]


def check_phone_first_screen(page):
    """A cold visitor on a phone: markers to tap on arrival, nothing on top of the search box, touch works."""
    shown = page.evaluate("""() => { const c = document.getElementById('ex-sky').getBoundingClientRect();
      return window.__explore.frame.targets.filter((p) => p && p.x > 0 && p.y > 0 && p.x < c.width && p.y < c.height).length; }""")
    check("phone arrival shows at least 10 of our views", shown >= 10, shown)
    status = page.locator("#ex-status").inner_text()
    check("phone arrival says how many more there are", "of our 19 built views" in status, status)
    cap, box, move = (page.locator(s).bounding_box() for s in (".ex-caption", "#ex-q", "#ex-move"))
    check("caption clear of the search box and the button", not boxes_overlap(cap, box) and not boxes_overlap(cap, move), (cap, box))
    sky = page.locator("#ex-sky").bounding_box()
    # Tap empty sky by touch, away from every marker.
    spot = page.evaluate("""() => { const f = window.__explore.frame, c = document.getElementById('ex-sky').getBoundingClientRect();
      const all = [...f.targets, ...f.known, ...f.stars].filter(Boolean);
      for (let y = c.height * 0.55; y < c.height - 90; y += 13) for (let x = 30; x < c.width - 30; x += 17)
        if (all.every((p) => Math.hypot(p.x - x, p.y - y) > 40)) return { x: c.left + x, y: c.top + y };
      return null; }""")
    if spot:
        page.touchscreen.tap(spot["x"], spot["y"])
        page.wait_for_timeout(300)
    href = page.locator("#ex-card a.ex-go").get_attribute("href") if page.locator("#ex-card").is_visible() else ""
    check("a finger tap on empty sky drops a pin", spot and (href or "").startswith("index.html?ra="), (spot, href))
    p = marker_point(page, "wise-0855-0714")
    if p and p["y"] > sky["y"] + 150:
        page.locator(".ex-close").tap()
        page.touchscreen.tap(p["x"], p["y"])
        page.wait_for_timeout(300)
        page.locator("#ex-card a.ex-go").tap()
        page.wait_for_url("**/index.html?target=*", timeout=8000)
        check("'Watch it move' opens the view by touch", "target=wise-0855-0714" in page.url, page.url)
        page.goto(BASE + "explore.html")
        wait_ready(page)
    else:
        page.locator("#ex-list a").first.tap()
        page.wait_for_url("**/index.html?target=*", timeout=8000)
        check("'Watch it move' opens the view by touch", "target=" in page.url, page.url)


def pinch(page):
    """Two fingers spreading apart on the canvas should zoom in."""
    page.goto(BASE + "explore.html")
    wait_ready(page)
    page.wait_for_timeout(200)
    before = state(page)["fov"]
    box = page.locator("#ex-sky").bounding_box()
    cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    cdp = page.context.new_cdp_session(page)

    def touch(kind, d):
        pts = [] if kind == "touchEnd" else [{"x": cx - d, "y": cy, "id": 1}, {"x": cx + d, "y": cy, "id": 2}]
        cdp.send("Input.dispatchTouchEvent", {"type": kind, "touchPoints": pts})

    touch("touchStart", 30)
    for d in range(35, 130, 5):
        touch("touchMove", d)
    touch("touchEnd", 0)
    page.wait_for_timeout(300)
    after = state(page)["fov"]
    check("pinch zooms in", after < before / 2, (before, after))


def run_reduced(browser, errors):
    ctx = browser.new_context(viewport={"width": 1200, "height": 800}, reduced_motion="reduce")
    ctx.route("**/api/archives", NO_ARCHIVES)
    page = ctx.new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE + "explore.html")
    wait_ready(page)
    page.fill("#ex-q", "vega")
    page.keyboard.press("Enter")
    page.wait_for_timeout(50)
    s = state(page)
    check("reduced motion: search jumps straight to Vega", abs(s["ra"] - 279.23) < 1, s)
    ctx.close()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    errors = []
    t0 = time.time()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=EXE)
        run_desktop(browser, errors)
        run_phone(browser, errors)
        run_reduced(browser, errors)
        browser.close()
    check("console clean", not errors, errors[:5])
    for name, ok, info in results:
        shown = not ok or str(info).startswith("p95")
        print(("PASS " if ok else "FAIL ") + name + (f"  [{info}]" if shown else ""))
    failed = sum(1 for _, ok, _ in results if not ok)
    print(f"{len(results) - failed}/{len(results)} passed in {time.time() - t0:.0f} s")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
