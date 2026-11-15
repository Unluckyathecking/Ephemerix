"""Probe: WiseView's backend (time-resolved unWISE coadds served as 8-bit PNGs).

Endpoint found in byw.tools/static/flash3.js (14 Nov 2026):
  GET https://moo23y1au0.execute-api.us-west-2.amazonaws.com/default/png-animation
returns JSON {ims: [S3 keys], all_mjds, mjds, epochs, CRPIX1/2, CRVAL1/2, NAXIS1/2, min, max};
each PNG is then fetched from https://amnh-citsci-public.s3-us-west-2.amazonaws.com/<key>.
No documented API or terms of use; it is a volunteer-run service.

Run: uv run python probes/wise/wiseview.py wise0855 [band]
Writes cache/wise/<target>/wiseview-w<band>.fits (one HDU per epoch, TAN WCS at 2.75"/px).
"""
import io, json, sys, time
from pathlib import Path

import numpy as np
import requests
from astropy.io import fits
from astropy.wcs import WCS

sys.path.insert(0, str(Path(__file__).parent))
from irsa_l1b import CACHE, REF_EPOCH, UA, position_at  # noqa: E402

API = "https://moo23y1au0.execute-api.us-west-2.amazonaws.com/default/png-animation"
S3 = "https://amnh-citsci-public.s3-us-west-2.amazonaws.com/"
SIZE_PX = 88  # ~4 arcmin at 2.75"/px
MINB, MAXB = -50.0, 500.0  # fixed linear stretch (Vega nanomaggie-ish units of unWISE)


def png_to_array(b: bytes) -> np.ndarray:
    from PIL import Image
    return np.asarray(Image.open(io.BytesIO(b)), dtype=float)


def run(key: str, band: int = 2, maxb: float = MAXB, tag: str = "") -> dict:
    t = json.load(open(CACHE / "targets.json"))[key]
    ra, dec = position_at(t, REF_EPOCH)
    params = {"ra": ra, "dec": dec, "band": band, "size": SIZE_PX, "max_dyr": 0,
              "minbright": MINB, "maxbright": maxb, "invert": 0, "stretch": 1, "diff": 0,
              "scandir": 0, "outer": 0, "neowise": 0, "window": 0, "diff_window": 1,
              "unique": 1, "smooth_scan": 0, "shift": 0, "pmx": 0, "pmy": 0,
              "synth_a": 0, "synth_a_sub": 0, "synth_b": 0, "synth_b_sub": 0}
    t0 = time.time()
    r = requests.get(API, params=params, headers=UA, timeout=120)
    r.raise_for_status()
    meta = r.json()
    t_api = time.time() - t0
    lat, sizes, hdus = [], [], [fits.PrimaryHDU()]
    for key_s3, mjds in zip(meta["ims"], meta["mjds"]):
        t1 = time.time()
        p = requests.get(S3 + key_s3, headers=UA, timeout=60)
        p.raise_for_status()
        lat.append(time.time() - t1)
        sizes.append(len(p.content))
        arr = png_to_array(p.content)[::-1]  # PNG rows run top-down; FITS bottom-up
        w = WCS(naxis=2)
        w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
        w.wcs.crval = [meta["CRVAL1"], meta["CRVAL2"]]
        w.wcs.crpix = [meta["CRPIX1"], meta["CRPIX2"]]
        w.wcs.cdelt = [-2.75 / 3600, 2.75 / 3600]
        hdr = w.to_header()
        hdr["MJDMEAN"] = float(np.mean(mjds))
        hdus.append(fits.ImageHDU(arr.astype(np.float32), header=hdr))
        time.sleep(0.2)
    (CACHE / key).mkdir(parents=True, exist_ok=True)
    fits.HDUList(hdus).writeto(CACHE / key / f"wiseview{tag}-w{band}.fits", overwrite=True)
    return {"target": key, "band": band, "api_s": round(t_api, 2), "n_epochs": len(meta["ims"]),
            "png_median_s": round(float(np.median(lat)), 2), "png_median_kB": round(float(np.median(sizes)) / 1024, 1),
            "total_s": round(time.time() - t0, 1), "data_min": meta["min"], "data_max": meta["max"], "maxbright": maxb, "naxis": [meta["NAXIS1"], meta["NAXIS2"]],
            "mjd_first": min(meta["all_mjds"]), "mjd_last": max(meta["all_mjds"])}


if __name__ == "__main__":
    # optional: maxbright (unclipped stretch for saturated stars) and an output tag
    band = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    maxb = float(sys.argv[3]) if len(sys.argv) > 3 else MAXB
    print(json.dumps(run(sys.argv[1], band, maxb, sys.argv[4] if len(sys.argv) > 4 else ""), indent=1))
