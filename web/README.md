# Web frontend

A static site that reads view manifests (`docs/api.md`) and shows, for one sky position: the SPHEREx images over time (six detector bands, extended back to 2010 with WISE), the measured motion against the catalogue, the SPHEREx spectrum with a type or a refusal, and what to check before trusting any of it. Plain HTML, CSS and ES modules; no build step. Plotly (basic bundle) and the three typefaces are vendored in `vendor/` and nothing is loaded from another origin.

## Name and design system
- The site's name, tagline, navigation and credits live in `js/site.js` and nowhere else. `js/chrome.js` draws the header and footer of every page from it, and every page title comes from `pageTitle()`. A rename is one edit to `SITE.name` (a unit test fails if the name is typed anywhere else under `web/`).
- `styles.css` is the design system, top to bottom: fonts, tokens (colour, type scale, 4 px spacing), base, chrome, components (card, button, segmented control, status chip, disclosure, table, stat tile, frame for pixel data), then the landing page, the view, the long-form pages and the validation block. `planetx.css` and `search.css` hold only what is particular to those pages.
- `js/plottheme.js` is the one Plotly theme (and the one loader) used by the spectrum, Planet X and blind-search plots.
- Colour carries meaning: amber is SPHEREx, the predicted track and actions; cyan is WISE and measured positions; green, amber and red chips are agrees, refused and differs; a dashed neutral chip is a provisional type.

## Run
```
python3 -m http.server 8765 --directory web    # then open http://localhost:8765/
cd web && node --test tests/*.test.js          # unit tests for the pure modules
uv run --with playwright python web/tools/check_site.py build/site-check   # headless checks + screenshots (SITE_BASE picks the server)
```

## Security
No third-party script, style or font is loaded: Plotly 2.35.2 and the fonts are vendored in `vendor/` (versions, sources, licences and SHA-256 in `vendor/README.md`). A CSP meta tag limits scripts to the site itself. Manifest strings reach the DOM only through `textContent`, and are escaped before Plotly sees them.

## Data
- Gallery: `gallery/index.json` and `gallery/<slug>/manifest.json` with images beside each manifest. Drop real pipeline output here. An empty index shows "No gallery targets built yet".
- Live: the API is served from the site's own origin, where the host rewrites `/api/*` to the lookup service (`middleware.js`): position searches via `GET /api/view?...` and name lookup via `GET /api/resolve?name=`. On localhost, `?api=ORIGIN` points the page at another service (add that origin to the page's CSP `connect-src` and `img-src`; see `js/config.js`).
- `tools/make_fixture.py` writes the three `synthetic-*` targets to `tests/fixtures/gallery/` (never served or deployed: `.vercelignore` excludes `tests/`; the tests and `check_site.py` route `/gallery/` to it) (six SPHEREx bands over three passes, WISE W1/W2, a no-motion faint case, a null case). They are test data, not observations: `uv run --with pillow python web/tools/make_fixture.py`.

## Link-outs
Built from RA/Dec only, opened in a new tab with `rel="noopener noreferrer"`; no third-party script is loaded. Each pattern was checked on 14 Nov 2026 for WISE 0855-0714 (133.783556, -7.244052):
- Aladin Lite: `https://aladin.cds.unistra.fr/AladinLite/?ra=&dec=&fov=` (degrees). The page script reads these three keys; headless load reported `initialView` at that position.
- WiseView: `http://byw.tools/wiseview#ra=&dec=&size=` (arcsec). `fromUrl()` in its `flash3.js` reads them from the hash. HTTP only.
- IRSA SPHEREx Data Explorer: `https://irsa.ipac.caltech.edu/applications/spherex/?api=spectral-images&ra=&dec=&spatialRegionOperation=contains_point&execute=true`, from the app's own `?api` help; it listed 258 DR1 images.
- SIMBAD is left out: the CDS service answered "currently unavailable", and its coordinate query takes J2000 positions, so for a fast mover it lands on the wrong object.

## Sky locator
The view page shows a small all-sky map (Hammer-Aitoff, equatorial, RA increasing to the left) with the Milky Way band, the ecliptic, the brightest stars and this view's position, plus a plain-language line: constellation, galactic latitude in words, ecliptic latitude when within 5 degrees, and the field against the full Moon. It is computed in the browser from the manifest centre and `fov_arcsec`; nothing is fetched except the site's own `gallery/index.json`, which supplies the other targets' markers (index entries need `ra` and `dec`).
- Galactic frame: J2000 pole RA 192.85948, Dec +27.12825, l of the north celestial pole 122.93192 (Hipparcos, ESA 1997). Ecliptic: obliquity 23.4393 degrees at J2000.
- Constellations: Roman (1987) boundary table (357 rows, B1875.0, the Delporte boundaries; VizieR VI/42) in `js/constellation-data.js`, with J2000 to B1875 IAU 1976 precession. The rows are identical to VI/42 (diffed against the VizieR mirror at Harvard); the names come from astropy, with two misspellings corrected (Ophiuchus, Chamaeleon). Against astropy on 4000 random positions it disagreed once, 0.005 degrees from a boundary.
- Bright stars (`js/brightstars.js`): 29 stars to magnitude 1.7 plus Polaris, from the table in PyEphem 4.2.1 and checked against Hipparcos (VizieR I/239) to 0.007 degrees.

## Modules
`app.js` routing and loading · `site.js` name, tagline, nav, credits · `chrome.js` header and footer · `manifest.js` validation · `urlstate.js` page URL · `coords.js` RA/Dec parsing · `sky.js` sky/pixel math (matches `src/pxs/astrometry.py`) · `framesets.js` band sets, presets, pass grouping · `labels.js` set names from mission and wavelength · `bandpicker.js` presets and toggles · `bandstrip.js` six bands of one pass · `compare.js` difference/sum arithmetic · `compareview.js` compare mode · `player.js` blink state and preloading · `icons.js` player icons (inline SVG) · `stage.js` canvas · `overlays.js` drawing · `timeline.js` · `spectrum.js` · `plottheme.js` Plotly theme and loader · `matchtext.js` match wording · `flags.js` quality notes · `vetting.js` W1-W2 and H_W2 · `framing.js` view transform, default zoom, follow rules · `notes.js`/`notesview.js` the collapsed notes · `gaps.js` time gaps · `hero.js` landing target rule · `herovisual.js` the landing blink and its readout · `scoreboard.js` scoreboard strip and gallery marks from `data/validation.json` · `links.js` link-outs · `resolve.js` name lookup · `gallery.js` landing · `search.js` the check form · `verdict.js` (pure) and `viewhead.js` the title, share actions and verdict strip of a view · `panels.js` · `summary.js` motion wording and the Talk summary · `skymath.js` frame conversions and projection · `allskypaths.js` locator geometry · `constellation.js` and `constellation-data.js` · `brightstars.js` · `locatortext.js` · `locator.js` the inset · `bodytext.js` (pure) and `bodymode.js` the Solar System body mode (manifests with `solar_system`: pass selector, reflectance with ice bands, band depths, body-centred images, Planet X note) · `view.js` wiring · `validation.js`/`validationtext.js`/`validationbodies.js`, `planetx.js`/`planetxdata.js`, `searchpage.js`/`searchdata.js` the three long-form pages · `p9data.js` (pure) and `p9view.js` the pilot search of the predicted Planet Nine region on the blind-search page (`data/p9-search.json`).

Ids the demo tooling and the checks rely on: `canvas.stage`, `#play`, `#prev-frame`, `#next-frame`, `#speed`, `#follow`, `#zoom`, `.band-strip`, `#fc-toggle`, `#spectrum .spec-plot`, `#spectrum .verdict-line`, `.verdict-strip [data-tile]`, `#motion`, `#data`, `.val-summary`.

## AI use
All of the code in this folder, including the fixture generator and tests, was written with Claude Code (Anthropic's AI coding tool), as was the rest of the entry's code.
