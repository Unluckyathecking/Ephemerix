"""Centroid the target in every epoch of a stack file and draw a contact sheet.

Input: a multi-HDU FITS from irsa_l1b.py (stack-w<b>.fits) or wiseview.py (wiseview-w<b>.fits).
For each epoch: predict the position from SIMBAD J2000 + proper motion at MJDMEAN, find the
brightest pixel within SEARCH_ARCSEC of the prediction, then take an intensity-weighted
centroid in a BOX x BOX window (background-subtracted, clipped at 0). Saturated cores are
fine at this level: the motions are ~100" against a ~6" PSF.

Run: uv run --with matplotlib python probes/wise/hero.py <target> <stack-file-name> [png-name]
"""
import json, sys
from pathlib import Path

import numpy as np
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.time import Time
from astropy.wcs import WCS
import astropy.units as u

sys.path.insert(0, str(Path(__file__).parent))
from irsa_l1b import CACHE, position_at  # noqa: E402

SEARCH_ARCSEC = 20.0
BOX = 9  # pixels (~25")


def centroid(img: np.ndarray, w: WCS, ra: float, dec: float) -> tuple[float, float] | None:
    x0, y0 = w.world_to_pixel_values(ra, dec)
    ny, nx = img.shape
    r = SEARCH_ARCSEC / 2.75
    yy, xx = np.mgrid[:ny, :nx]
    sel = np.hypot(xx - x0, yy - y0) <= r
    good = sel & np.isfinite(img)
    if good.sum() < 5:
        return None
    k = np.nanargmax(np.where(good, img, -np.inf))
    cy, cx = divmod(k, nx)
    cy, cx = float(cy), float(cx)
    bg = np.nanmedian(img)
    filled = np.clip(np.nan_to_num(img, nan=bg) - bg, 0, None)
    h = BOX // 2
    # Iterate: re-centre the box on the last centroid, so flat saturated plateaus
    # (clipped PNG or saturated L1b cores) converge to their middle, not an edge.
    for _ in range(10):
        py, px = int(round(cy)), int(round(cx))
        y0_, x0_ = max(py - h, 0), max(px - h, 0)
        sub = filled[y0_:py + h + 1, x0_:px + h + 1]
        if sub.sum() <= 0:
            return None
        sy, sx = np.mgrid[:sub.shape[0], :sub.shape[1]]
        ncx = (sx * sub).sum() / sub.sum() + x0_
        ncy = (sy * sub).sum() / sub.sum() + y0_
        if abs(ncx - cx) < 0.01 and abs(ncy - cy) < 0.01:
            break
        cx, cy = ncx, ncy
    return tuple(float(v) for v in w.pixel_to_world_values(cx, cy))


BRIGHT = {"barnard", "rwaur", "rdra"}  # saturated in W1/W2: use the blob centroid
BRIGHT_RADIUS_ARCSEC = 40.0


def blob_centroid(img: np.ndarray, w: WCS, ra: float, dec: float) -> tuple[float, float] | None:
    """Centroid of the hole-filled half-max blob around the prediction (for saturated stars,
    whose cores are flat, clipped or blanked and so bias a flux-weighted centroid)."""
    from scipy import ndimage
    x0, y0 = w.world_to_pixel_values(ra, dec)
    ny, nx = img.shape
    yy, xx = np.mgrid[:ny, :nx]
    sel = (np.hypot(xx - x0, yy - y0) <= BRIGHT_RADIUS_ARCSEC / 2.75) & np.isfinite(img)
    if sel.sum() < 5:
        return None
    bg = np.nanmedian(img)
    peak = np.nanmax(np.where(sel, img, -np.inf))
    mask = sel & (np.nan_to_num(img, nan=-np.inf) >= bg + 0.5 * (peak - bg))
    mask = ndimage.binary_fill_holes(mask)
    lab, _ = ndimage.label(mask)
    k = np.nanargmax(np.where(sel, img, -np.inf))
    blob = lab == lab.flat[k]
    cy, cx = ndimage.center_of_mass(blob)
    return tuple(float(v) for v in w.pixel_to_world_values(cx, cy))


FIXED_RADIUS_ARCSEC = 90.0
FIXED_BOX = 15  # pixels (~41")


def fixed_prior_centroid(img: np.ndarray, w: WCS, ra0: float, dec0: float) -> tuple[float, float] | None:
    """Prior-independent centroid for bright stars in unclipped stamps: brightest pixel within
    FIXED_RADIUS of ONE fixed position (the 2017 stamp centre, same for every epoch), then an
    iterated flux-weighted centroid in a FIXED_BOX window. Never uses the per-epoch prediction."""
    global SEARCH_ARCSEC, BOX
    saved = SEARCH_ARCSEC, BOX
    SEARCH_ARCSEC, BOX = FIXED_RADIUS_ARCSEC, FIXED_BOX
    try:
        return centroid(img, w, ra0, dec0)
    finally:
        SEARCH_ARCSEC, BOX = saved


def measure(key: str, fname: str) -> dict:
    t = json.load(open(CACHE / "targets.json"))[key]
    rows = []
    with fits.open(CACHE / key / fname) as hl:
        for h in hl[1:]:
            mjd = h.header["MJDMEAN"]
            yr = float(Time(mjd, format="mjd").decimalyear)
            pra, pdec = position_at(t, yr)
            if "unclipped" in fname or ("bucket" in fname and key in BRIGHT):  # bright star, prior-free: fixed 2017 centre for every epoch
                c = fixed_prior_centroid(h.data.astype(float), WCS(h.header), *position_at(t, 2017.0))
            else:
                fn = blob_centroid if key in BRIGHT else centroid
                c = fn(h.data.astype(float), WCS(h.header), pra, pdec)
            off = None
            if c:
                off = SkyCoord(*c, unit="deg").separation(SkyCoord(pra, pdec, unit="deg")).arcsec
            rows.append({"year": round(yr, 3), "pred": [pra, pdec], "meas": c,
                         "meas_minus_pred_arcsec": None if off is None else round(off, 2),
                         "nframes": h.header.get("NFRAMES")})
    ok = [r for r in rows if r["meas"]]
    first, last = ok[0], ok[-1]
    a = SkyCoord(*first["meas"], unit="deg")
    b = SkyCoord(*last["meas"], unit="deg")
    pa_, pb_ = SkyCoord(*first["pred"], unit="deg"), SkyCoord(*last["pred"], unit="deg")
    return {"target": key, "file": fname, "epochs": len(rows), "measured_epochs": len(ok),
            "first_year": first["year"], "last_year": last["year"],
            "shift_measured_arcsec": round(a.separation(b).arcsec, 1),
            "shift_expected_arcsec": round(pa_.separation(pb_).arcsec, 1),
            "pa_measured_deg": round(a.position_angle(b).to(u.deg).value, 1),
            "pa_expected_deg": round(pa_.position_angle(pb_).to(u.deg).value, 1),
            "median_abs_resid_arcsec": round(float(np.median([r["meas_minus_pred_arcsec"] for r in ok])), 2),
            "method": "fixed-prior" if ("unclipped" in fname or ("bucket" in fname and key in BRIGHT)) else ("blob" if key in BRIGHT else "weighted"), "rows": rows}


def contact_sheet(key: str, fname: str, png: Path, title: str) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    with fits.open(CACHE / key / fname) as hl:
        ims = [(h.data.astype(float), h.header["MJDMEAN"], WCS(h.header)) for h in hl[1:]]
    t = json.load(open(CACHE / "targets.json"))[key]
    allpix = np.concatenate([np.ravel(i[np.isfinite(i)]) for i, _, _ in ims])
    lo, hi = np.percentile(allpix, [30, 99.7])  # one stretch for every epoch
    n = len(ims)
    ncol = min(n, 12)
    nrow = int(np.ceil(n / ncol))
    fig, axs = plt.subplots(nrow, ncol, figsize=(ncol * 1.1, nrow * 1.25 + 0.3), squeeze=False)
    for ax in axs.flat:
        ax.axis("off")
    for ax, (im, mjd, w) in zip(axs.flat, ims):
        ax.imshow(np.arcsinh((im - lo) / (hi - lo) * 10), origin="lower", cmap="gray_r",
                  vmin=0, vmax=np.arcsinh(10))
        px, py = w.world_to_pixel_values(*position_at(t, float(Time(mjd, format="mjd").decimalyear)))
        ax.add_patch(plt.Circle((px, py), 5, fill=False, color="red", lw=0.6))  # SIMBAD PM prediction
        ax.set_title(f"{Time(mjd, format='mjd').decimalyear:.1f}", fontsize=7)
    fig.suptitle(title, fontsize=8)
    fig.tight_layout(pad=0.2)
    png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(png, dpi=90)
    plt.close(fig)


if __name__ == "__main__":
    key, fname = sys.argv[1], sys.argv[2]
    res = measure(key, fname)
    print(json.dumps({k: v for k, v in res.items() if k != "rows"}, indent=1))
    for r in res["rows"]:
        print(r["year"], r["nframes"], r["meas_minus_pred_arcsec"])
    json.dump(res, open(CACHE / key / f"hero-{fname}.json", "w"), indent=1)
    if len(sys.argv) > 3:
        contact_sheet(key, fname, Path(sys.argv[3]), f"{key} {fname} (4' stamp, N up E left, fixed stretch, red ring = predicted position)")
