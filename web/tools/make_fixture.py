"""Generate SYNTHETIC gallery fixtures for the frontend.

Nothing written here is a real observation. The two targets exist only to
exercise the viewer against docs/api.md before the pipeline delivers data:

- synthetic-fast-mover: a fast mover in WISE W1/W2 and the six SPHEREx detector
  bands (spx-b1 to spx-b6) over three passes, fading where methane absorbs; one
  undetected W1 frame, flagged frames with warnings, two SPHEREx epochs with
  different spectra plus a combined one, a template match with class and type
  range, and the optional `vetting` block.
- synthetic-faint: a mover with no proper motion given (track []) but a measured
  one, a spectrum too faint to classify (match null, reason in warnings), flagged
  spectrum points, and a partial `vetting` block.
- synthetic-no-motion: proper motion unknown (track []), no spectrum
  (match null), a single detection (measured_motion null).

Run from the repo root:  uv run --with pillow python web/tools/make_fixture.py

The pixel convention must match web/js/sky.js: the grid centre is at
(size_px/2, size_px/2) in edge-based pixel coordinates, x grows to the west
(RA decreasing), y grows to the south (Dec decreasing).
"""

import json
import math
import random
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

from PIL import Image

OUT = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "gallery"
NOTICE = ("Synthetic test data made by web/tools/make_fixture.py. "
          "Nothing in this view is a real observation.")


def mjd_from_year(year):
    return 51544.5 + (year - 2000.0) * 365.25


def iso_from_mjd(mjd):
    t = datetime(1858, 11, 17, tzinfo=UTC) + timedelta(days=mjd)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def propagate(ra, dec, pmra, pmdec, epoch, year):
    dt = year - epoch
    cosd = math.cos(math.radians(dec))
    return ra + pmra * dt / 3.6e6 / cosd, dec + pmdec * dt / 3.6e6


def sky_to_px(ra, dec, center, scale, size):
    ra0, dec0 = math.radians(center[0]), math.radians(center[1])
    a, d = math.radians(ra), math.radians(dec)
    cosc = math.sin(dec0) * math.sin(d) + math.cos(dec0) * math.cos(d) * math.cos(a - ra0)
    xi = math.cos(d) * math.sin(a - ra0) / cosc
    eta = (math.cos(dec0) * math.sin(d) - math.sin(dec0) * math.cos(d) * math.cos(a - ra0)) / cosc
    k = 180 / math.pi * 3600 / scale
    return [size / 2 - xi * k, size / 2 - eta * k]


def render(size, sources, sigma_px, block, noise, seed):
    """Sum Gaussian sources, add noise, pixelate by `block`, asinh-stretch to 8 bit."""
    rng = random.Random(seed)
    img = [[rng.gauss(0, noise) for _ in range(size)] for _ in range(size)]
    for (x, y, flux) in sources:
        r = int(4 * sigma_px) + 1
        for j in range(max(0, int(y) - r), min(size, int(y) + r + 1)):
            for i in range(max(0, int(x) - r), min(size, int(x) + r + 1)):
                d2 = (i + 0.5 - x) ** 2 + (j + 0.5 - y) ** 2
                img[j][i] += flux * math.exp(-d2 / (2 * sigma_px ** 2))
    if block > 1:
        for j0 in range(0, size, block):
            for i0 in range(0, size, block):
                cells = [(j, i) for j in range(j0, min(size, j0 + block))
                         for i in range(i0, min(size, i0 + block))]
                m = sum(img[j][i] for j, i in cells) / len(cells)
                for j, i in cells:
                    img[j][i] = m
    im = Image.new("L", (size, size))
    im.putdata([max(0, min(255, int(255 * math.asinh((v + 0.03) / 0.02) / math.asinh(0.6 / 0.02))))
                for row in img for v in row])
    return im


# ---- spectra -------------------------------------------------------------

def g(x, mu, s):
    return math.exp(-0.5 * ((x - mu) / s) ** 2)


def template(kind, wl):
    """Toy brown-dwarf shapes. Colder types have weaker near-IR peaks."""
    nir = {"T8": 0.45, "Y0": 0.22, "Y1": 0.12}[kind]
    ch4 = {"T8": 0.75, "Y0": 0.9, "Y1": 0.95}[kind]
    f = (nir * (0.5 * g(wl, 1.07, 0.04) + 1.0 * g(wl, 1.27, 0.05) + 0.5 * g(wl, 1.58, 0.05)
                + 0.25 * g(wl, 2.08, 0.08))
         + 0.05 * g(wl, 3.9, 0.25) + 1.0 * g(wl, 4.15, 0.32))
    f *= (1 - ch4 * g(wl, 3.3, 0.18)) * (1 - 0.45 * g(wl, 4.28, 0.05)) * (1 - 0.3 * g(wl, 4.65, 0.09))
    return 0.5 * f


def channel_grid():
    wl, out = 0.75, []
    while wl < 5.0:
        r = 41 if wl < 2.4 else 35 if wl < 3.8 else 110 if wl < 4.4 else 130
        out.append((round(wl, 4), round(wl / r, 4)))
        wl += wl / r
    return out


def detector(wl):
    edges = [1.10, 1.63, 2.42, 3.83, 4.42]
    return 1 + sum(wl >= e for e in edges)


def make_spectrum(sid, label, start, end, scale, seed, noise=1.0):
    rng = random.Random(seed)
    pts = []
    for wl, bw in channel_grid():
        err = noise * (0.012 + 0.04 * template("Y0", wl))
        flux = scale * template("Y0", wl) + rng.gauss(0, err)
        pts.append({"wl_um": wl, "bw_um": bw, "flux": round(flux, 4), "err": round(err, 4),
                    "detector": detector(wl), "flagged": rng.random() < 0.05})
    return {"id": sid, "label": label, "date_start": start, "date_end": end,
            "unit": "mJy", "points": pts}


def combine(a, b):
    pts = []
    for p, q in zip(a["points"], b["points"]):
        wp, wq = 1 / p["err"] ** 2, 1 / q["err"] ** 2
        pts.append({**p, "flux": round((p["flux"] * wp + q["flux"] * wq) / (wp + wq), 4),
                    "err": round((wp + wq) ** -0.5, 4), "flagged": p["flagged"] and q["flagged"]})
    return {"id": "spx-all", "label": "Both epochs", "date_start": a["date_start"],
            "date_end": b["date_end"], "unit": "mJy", "points": pts}


def fit(spec):
    good = [p for p in spec["points"] if not p["flagged"] and p["wl_um"] >= 1.0]
    rows = []
    for kind in ("T8", "Y0", "Y1"):
        t = [template(kind, p["wl_um"]) for p in good]
        w = [1 / p["err"] ** 2 for p in good]
        a = sum(wi * ti * p["flux"] for wi, ti, p in zip(w, t, good)) / sum(wi * ti * ti for wi, ti in zip(w, t))
        chi2 = sum(wi * (p["flux"] - a * ti) ** 2 for wi, ti, p in zip(w, t, good))
        rows.append((chi2, kind, a))
    rows.sort()
    dof = len(good) - 1
    models = {k: [[round(x / 100, 3), round(a * template(k, x / 100), 4)] for x in range(100, 500, 2)]
              for _, k, a in rows[:2]}
    (c1, k1, _), (c2, k2, _) = rows[0], rows[1]
    near = [k for c, k, _ in rows if c - c1 <= 4]
    order = ["T8", "Y0", "Y1"]
    span = sorted(near, key=order.index)
    return {
        "class": "brown dwarf",
        "type_range": [span[0], span[-1]],
        "range_open_cold": span[-1] == "Y1",
        "pair": None,
        "spectrum_id": spec["id"],
        "best": {"type": k1, "chi2": round(c1, 1), "dof": dof},
        "runner_up": {"type": k2, "chi2": round(c2, 1), "dof": dof},
        "delta_chi2": round(c2 - c1, 1),
        "verdict": f"Synthetic test: the injected shape is recovered as a cold brown dwarf ({k1}).",
        "confidence": "high" if c2 - c1 > 25 else "medium" if c2 - c1 > 9 else "low",
        "candidates": [{"type": k, "chi2": round(c, 1)} for c, k, _ in rows],
        "models": models,
        "method": "Chi-square with a free scale factor against three toy templates (synthetic stand-ins).",
    }


FEATURES = [
    {"label": "H2O", "wl_um": [1.33, 1.5]}, {"label": "CH4", "wl_um": [1.6, 1.8]},
    {"label": "CH4", "wl_um": [2.2, 2.45]}, {"label": "H2O", "wl_um": [2.6, 3.0]},
    {"label": "CH4", "wl_um": [3.15, 3.6]}, {"label": "CO2", "wl_um": [4.2, 4.35]},
    {"label": "CO", "wl_um": [4.5, 4.8]},
]


# ---- targets -------------------------------------------------------------

WISE_YEARS = [2010.37, 2010.87] + [y + 0.4 for y in range(2014, 2025)]  # no WISE data 2011-2013
SPX_PASSES = [2025.36, 2025.86, 2026.36]
SPX_JITTER = 0.006  # years between bands within one pass (about two days), so passes cluster
BANDS = {  # band: (mission, passband, native pixscale, psf sigma px, block, mover flux, star scale)
    "W1": ("WISE", [2.8, 3.8], 2.75, 1.7, 1, 0.10, 1.0),
    "W2": ("WISE", [4.0, 5.2], 2.75, 1.8, 1, 0.9, 0.7),
    # The six SPHEREx detector bands. The injected cold object fades where methane absorbs.
    "spx-b1": ("SPHEREx", [0.75, 1.10], 6.15, 2.2, 4, 0.02, 1.3),
    "spx-b2": ("SPHEREx", [1.10, 1.65], 6.15, 2.2, 4, 0.20, 1.1),
    "spx-b3": ("SPHEREx", [1.65, 2.42], 6.15, 2.2, 4, 0.04, 1.0),
    "spx-b4": ("SPHEREx", [2.42, 3.82], 6.15, 2.2, 4, 0.03, 0.8),
    "spx-b5": ("SPHEREx", [3.82, 4.42], 6.15, 2.2, 4, 0.55, 0.65),
    "spx-b6": ("SPHEREx", [4.42, 5.00], 6.15, 2.2, 4, 0.8, 0.6),
}
SPX_BANDS = [b for b in BANDS if b.startswith("spx-")]


def spx_year(pass_year, band):
    return pass_year + SPX_BANDS.index(band) * SPX_JITTER


def field_stars(rng, center, n, half_deg):
    stars = []
    cosd = math.cos(math.radians(center[1]))
    for k in range(n):
        ra = center[0] + rng.uniform(-half_deg, half_deg) / cosd
        dec = center[1] + rng.uniform(-half_deg, half_deg)
        pm = (420.0, -260.0) if k == 0 else (rng.gauss(0, 6), rng.gauss(0, 6))
        stars.append({"id": f"SYNTH-G{k:03d}", "ra": round(ra, 7), "dec": round(dec, 7), "epoch": 2016.0,
                      "pmra_masyr": round(pm[0], 1), "pmdec_masyr": round(pm[1], 1),
                      "g_mag": round(rng.uniform(13, 20), 2)})
    return stars


def frames_for(slug, target, center, scale, size, stars, plan, rng, true_pm=None):
    """plan: list of (band, year, warnings, detected[, flag_fraction]).
    true_pm: the motion used to place the object when the target's own is unknown."""
    out_dir = OUT / slug / "frames"
    out_dir.mkdir(parents=True, exist_ok=True)
    frames = []
    has_pm = target["pmra_masyr"] is not None
    for band, year, warnings, detected, *flag in plan:
        mission, passband, native, sigma, block, mover_flux, star_scale = BANDS[band]
        mjd = mjd_from_year(year)
        pmra, pmdec = true_pm or (target["pmra_masyr"] or 0.0, target["pmdec_masyr"] or 0.0)
        ra, dec = propagate(target["ra"], target["dec"], pmra, pmdec, target["epoch"], year)
        truth = sky_to_px(ra, dec, center, scale, size)
        srcs = [(*truth, mover_flux)]
        for s in stars:
            sra, sdec = propagate(s["ra"], s["dec"], s["pmra_masyr"], s["pmdec_masyr"], s["epoch"], year)
            x, y = sky_to_px(sra, sdec, center, scale, size)
            srcs.append((x, y, star_scale * 10 ** (-0.4 * (s["g_mag"] - 13))))
        fid = f"{mission.lower()}-{band.lower()}-{year:.2f}".replace(".", "p")
        render(size, srcs, sigma, block, 0.012, sum(map(ord, fid))).save(out_dir / f"{fid}.png", optimize=True)
        err = 0.35 if mission == "WISE" else 1.2
        centroid = [round(truth[0] + rng.gauss(0, err / scale), 2),
                    round(truth[1] + rng.gauss(0, err / scale), 2)] if detected else None
        frames.append({
            "id": fid, "mission": mission, "band": band, "wavelength_um": passband,
            "date": iso_from_mjd(mjd), "mjd": round(mjd, 3),
            "date_span_days": 1.2 if mission == "WISE" else 9.0,
            "n_exposures": 12 if mission == "WISE" else 4,
            "native_pixscale_arcsec": native, "image": f"frames/{fid}.png",
            "predicted_px": [round(v, 3) for v in truth] if has_pm else None,
            "centroid_px": centroid, "centroid_err_arcsec": err if detected else None,
            "flag_fraction": flag[0] if flag else (0.18 if warnings else 0.0), "warnings": warnings,
        })
    frames.sort(key=lambda f: f["mjd"])
    return frames


def measured_motion(frames, center_px, scale):
    pts = [(2000 + (f["mjd"] - 51544.5) / 365.25, f["centroid_px"]) for f in frames if f["centroid_px"]]
    if len(pts) < 2:
        return None
    ts = [t for t, _ in pts]
    tm = sum(ts) / len(ts)
    stt = sum((t - tm) ** 2 for t in ts)

    def slope(vals):
        vm = sum(vals) / len(vals)
        b = sum((t - tm) * (v - vm) for t, v in zip(ts, vals)) / stt
        resid = sum((v - vm - b * (t - tm)) ** 2 for t, v in zip(ts, vals)) / max(1, len(ts) - 2)
        return b, math.sqrt(resid / stt)

    bx, ex = slope([(center_px - c[0]) * scale * 1000 for _, c in pts])
    by, ey = slope([(center_px - c[1]) * scale * 1000 for _, c in pts])
    return {"pmra_masyr": round(bx, 1), "pmdec_masyr": round(by, 1), "err_masyr": round(math.hypot(ex, ey), 1),
            "baseline_years": round(max(ts) - min(ts), 2), "n_detections": len(pts)}


def track_for(target, center, scale, size, years):
    if target["pmra_masyr"] is None:
        return []
    out = []
    for y in range(years[0], years[1] + 1):
        ra, dec = propagate(target["ra"], target["dec"], target["pmra_masyr"], target["pmdec_masyr"],
                            target["epoch"], float(y))
        out.append({"year": float(y), "px": [round(v, 3) for v in sky_to_px(ra, dec, center, scale, size)]})
    return out


def base_manifest(target, center, fov, size):
    return {"schema": 1, "generated": "2026-11-14T12:00:00Z", "target": target,
            "center": {"ra": center[0], "dec": center[1]}, "fov_arcsec": fov, "size_px": size}


def fast_mover():
    rng = random.Random(7)
    slug, size, fov = "synthetic-fast-mover", 120, 180.0
    scale = fov / size
    target = {"name": "SYNTHETIC fast mover (test data)", "slug": slug,
              "ra": 150.0123456, "dec": 20.0045678, "epoch": 2018.0,
              "pmra_masyr": -2600.0, "pmdec_masyr": 1400.0,
              "blurb": "Synthetic test object, not a real star: a cold brown dwarf injected into a fake field."}
    center = (target["ra"], target["dec"])
    stars = field_stars(rng, center, 26, fov / 3600 * 0.48)
    plan = []
    for y in WISE_YEARS:
        plan.append(("W1", y, [], abs(y - 2010.87) > 0.01))   # undetected in one W1 frame
        warn = ["partial coverage", "saturated star nearby"] if abs(y - 2019.4) < 0.01 else []
        plan.append(("W2", y, warn, True))
    detected = {"spx-b1": False, "spx-b2": True, "spx-b3": False, "spx-b4": False, "spx-b5": True, "spx-b6": True}
    for i, y in enumerate(SPX_PASSES):
        for b in SPX_BANDS:
            warn = ["saturated star nearby"] if (i, b) == (1, "spx-b2") else []
            plan.append((b, spx_year(y, b), warn, detected[b], 0.07 if warn else 0.0))
    frames = frames_for(slug, target, center, scale, size, stars, plan, rng)
    a = make_spectrum("spx-2025a", "May 2025", "2025-05-04T00:00:00Z", "2025-05-18T00:00:00Z", 1.0, 11)
    b = make_spectrum("spx-2025b", "Nov 2025", "2025-11-06T00:00:00Z", "2025-11-20T00:00:00Z", 0.82, 12)
    both = combine(a, b)
    cw_ra, cw_dec = propagate(*center, -2600, 1400, 2018.0, 2015.4)
    catwise = [{"id": "SYNTH-CW-MOVER", "ra": round(cw_ra, 7), "dec": round(cw_dec, 7), "epoch": 2015.4,
                "pmra_masyr": -2580.0, "pmdec_masyr": 1390.0, "w1_mag": 17.9, "w2_mag": 14.6}]
    m = base_manifest(target, center, fov, size)
    m.update({
        "frames": frames, "track": track_for(target, center, scale, size, (2010, 2026)),
        "spectra": [a, b, both], "match": fit(both), "features": FEATURES,
        "overlays": {"gaia": stars, "catwise": catwise},
        "measured_motion": measured_motion(frames, size / 2, scale),
        "vetting": {"w1_mag": 17.9, "w2_mag": 14.6, "w1_w2": 3.3,
                    "reduced_pm_w2": round(14.6 + 5 * math.log10(math.hypot(2600, 1400) / 1000) + 5, 2),
                    "catalogue": "CatWISE2020 (synthetic values)"},
        "warnings": [NOTICE, "W1 frame of Nov 2010: the object was not detected (it is faint at 3.4 µm).",
                     "Spectrum points near a saturated star were flagged (synthetic)."],
        "credits": ["Synthetic fixture generated for testing; no archive data used."],
    })
    return m


def no_motion():
    rng = random.Random(3)
    slug, size, fov = "synthetic-no-motion", 96, 192.0
    scale = fov / size
    target = {"name": "SYNTHETIC static source (test data)", "slug": slug,
              "ra": 210.5, "dec": -35.25, "epoch": 2016.0, "pmra_masyr": None, "pmdec_masyr": None,
              "blurb": "Synthetic test case with no known motion and no usable spectrum."}
    center = (target["ra"], target["dec"])
    stars = field_stars(rng, center, 18, fov / 3600 * 0.48)
    plan = [("W2", y, [], abs(y - 2015.4) < 0.01) for y in WISE_YEARS[::3]]  # one detection only
    plan.append(("spx-b6", SPX_PASSES[0], [], False))
    frames = frames_for(slug, target, center, scale, size, stars, plan, rng)
    m = base_manifest(target, center, fov, size)
    m.update({
        "frames": frames, "track": [], "spectra": [], "match": None, "features": [],
        "overlays": {"gaia": stars, "catwise": []}, "measured_motion": measured_motion(frames, size / 2, scale),
        "warnings": [NOTICE, "No SPHEREx spectrum could be extracted at this position."],
        "credits": ["Synthetic fixture generated for testing; no archive data used."],
    })
    return m


def faint():
    """A mover whose proper motion is not given: the frames measure one; the spectrum is too faint."""
    rng = random.Random(5)
    slug, size, fov = "synthetic-faint", 96, 192.0
    scale = fov / size
    target = {"name": "SYNTHETIC faint mover, no motion given (test data)", "slug": slug,
              "ra": 45.25, "dec": -12.5, "epoch": 2016.0, "pmra_masyr": None, "pmdec_masyr": None,
              "blurb": "Synthetic test case: an object that moves but has no catalogue motion, too faint to type."}
    center = (target["ra"], target["dec"])
    stars = field_stars(rng, center, 16, fov / 3600 * 0.48)
    plan = [("W2", y, [], True) for y in WISE_YEARS[::2]]
    for y in SPX_PASSES:
        plan += [("spx-b5", spx_year(y, "spx-b5"), [], False), ("spx-b6", spx_year(y, "spx-b6"), [], True)]
    frames = frames_for(slug, target, center, scale, size, stars, plan, rng, true_pm=(900.0, -1500.0))
    spec = make_spectrum("spx-all", "All passes", "2025-05-04T00:00:00Z", "2026-05-20T00:00:00Z", 0.25, 21, noise=2.5)
    for k, p in enumerate(spec["points"]):
        p["flagged"] = k % 23 == 5
    m = base_manifest(target, center, fov, size)
    m.update({
        "frames": frames, "track": [], "spectra": [spec], "match": None, "features": FEATURES,
        "overlays": {"gaia": stars, "catwise": []}, "measured_motion": measured_motion(frames, size / 2, scale),
        "vetting": {"w1_mag": None, "w2_mag": 15.9, "w1_w2": None, "reduced_pm_w2": None, "catalogue": "CatWISE2020"},
        "warnings": [NOTICE, "Detected, but too faint to classify: the spectrum's signal-to-noise ratio is below 5 (synthetic).",
                     "Spectrum points hit by cosmic rays were flagged (synthetic)."],
        "credits": ["Synthetic fixture generated for testing; no archive data used."],
    })
    return m


def thumb(slug, manifest):
    frame = next(f for f in reversed(manifest["frames"]) if f["band"] in ("W2", "spx-b6"))
    Image.open(OUT / slug / frame["image"]).resize((192, 192), Image.NEAREST).save(OUT / slug / "thumb.png")


GROUP_BRIEF = "Synthetic stand-ins for brief targets"
GROUP_EDGE = "Synthetic edge cases"


def main():
    for old in OUT.glob("synthetic-*"):
        shutil.rmtree(old)
    index = []
    for build, known, group in ((fast_mover, "Y0 (injected)", GROUP_BRIEF), (faint, "T9 (injected)", GROUP_EDGE),
                                (no_motion, None, GROUP_EDGE)):
        m = build()
        slug = m["target"]["slug"]
        (OUT / slug / "manifest.json").write_text(json.dumps(m, indent=1) + "\n")
        thumb(slug, m)
        index.append({"slug": slug, "name": m["target"]["name"], "blurb": m["target"]["blurb"],
                      "manifest": f"{slug}/manifest.json", "thumb": f"{slug}/thumb.png",
                      "known_type": known, "tool_type": m["match"]["best"]["type"] if m["match"] else None,
                      "group": group})
    (OUT / "index.json").write_text(json.dumps({"schema": 1, "targets": index}, indent=1) + "\n")


if __name__ == "__main__":
    main()
