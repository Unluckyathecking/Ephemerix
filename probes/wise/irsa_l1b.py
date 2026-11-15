"""Probe: per-visit WISE/NEOWISE W1/W2 stamps from IRSA L1b frames via IBE cutouts.

For one target: IBE metadata search over the 2010 cryo/post-cryo and NEOWISE-R
tables, group frames into visits (~every 6 months), fetch a 4' cutout of up to
MAX_PER_VISIT frames per visit and band, reproject them onto one fixed
tangent-plane grid (2.75"/px, north up) and median-stack per visit.

Run:  uv run --with reproject python probes/wise/irsa_l1b.py wise0855 [bands] [max_per_visit] [first_n_visits]
Writes cache/wise/<target>/stack-w<band>.fits (one HDU per visit) + timings.json.
"""
import gzip, io, json, sys, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import requests
from astropy.io import ascii, fits
from astropy.time import Time
from astropy.wcs import WCS
from reproject import reproject_interp

UA = {"User-Agent": "planet-x-spherex-probe"}
IBE = "https://irsa.ipac.caltech.edu/ibe"
COLLECTIONS = [  # (ibe path, data path)
    ("wise/allsky/4band_p1bm_frm", "wise/allsky/4band_p1bm_frm"),
    ("wise/cryo_3band/3band_p1bm_frm", "wise/cryo_3band/3band_p1bm_frm"),
    ("wise/postcryo/2band_p1bm_frm", "wise/postcryo/2band_p1bm_frm"),
    ("wise/neowiser/p1bm_frm", "wise/neowiser/p1bm_frm"),
]
STAMP_ARCMIN = 4.0
PIX_ARCSEC = 2.75
MAX_PER_VISIT = 8      # frames stacked per visit per band (keeps request count polite)
WORKERS = 2            # concurrent cutout requests
VISIT_GAP_DAYS = 20.0
REF_EPOCH = 2017.0     # stamp centre = target position at this epoch (fixed for all visits)
CACHE = Path("cache/wise")


def position_at(t: dict, year: float) -> tuple[float, float]:
    """Linear proper-motion propagation from J2000 (fine at the arcsec level here)."""
    dt = year - 2000.0
    dec = t["dec"] + t["pmdec"] / 3.6e6 * dt
    ra = t["ra"] + t["pmra"] / 3.6e6 * dt / np.cos(np.radians(t["dec"]))
    return ra, dec


def search(ra: float, dec: float) -> list[dict]:
    rows, timings = [], {}
    for path, data in COLLECTIONS:
        t0 = time.time()
        r = requests.get(f"{IBE}/search/{path}", params={"POS": f"{ra},{dec}"}, headers=UA, timeout=180)
        r.raise_for_status()
        timings[path] = round(time.time() - t0, 2)
        tab = ascii.read(r.text, format="ipac") if "|" in r.text else []
        for row in tab:
            if int(row["band"]) in (1, 2) and int(row["qual_frame"]) > 0:
                rows.append({"data": data, "band": int(row["band"]), "mjd": float(row["mjd_obs"]),
                             "scan_id": str(row["scan_id"]), "scangrp": str(row["scangrp"]),
                             "frame_num": int(row["frame_num"])})
        time.sleep(0.5)
    return rows, timings


def group_visits(rows: list[dict]) -> list[list[dict]]:
    rows = sorted(rows, key=lambda r: r["mjd"])
    visits, cur = [], []
    for r in rows:
        if cur and r["mjd"] - cur[-1]["mjd"] > VISIT_GAP_DAYS:
            visits.append(cur)
            cur = []
        cur.append(r)
    visits += [cur] if cur else []
    # Near the ecliptic poles coverage is near-continuous: split long groups into half-years.
    out = []
    for v in visits:
        if v[-1]["mjd"] - v[0]["mjd"] <= 60:
            out.append(v)
            continue
        halves: dict[int, list[dict]] = {}
        for r in v:
            halves.setdefault(int(Time(r["mjd"], format="mjd").decimalyear * 2), []).append(r)
        out += [halves[k] for k in sorted(halves)]
    return out


def target_wcs(ra: float, dec: float) -> WCS:
    n = int(round(STAMP_ARCMIN * 60 / PIX_ARCSEC)) | 1
    w = WCS(naxis=2)
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.wcs.crval = [ra, dec]
    w.wcs.crpix = [(n + 1) / 2, (n + 1) / 2]
    w.wcs.cdelt = [-PIX_ARCSEC / 3600, PIX_ARCSEC / 3600]
    w.pixel_shape = (n, n)
    return w


def fetch(row: dict, ra: float, dec: float) -> tuple[dict, bytes | None, float, str]:
    f = f"{row['frame_num']:03d}"
    url = (f"{IBE}/data/{row['data']}/{row['scangrp']}/{row['scan_id']}/{f}/"
           f"{row['scan_id']}{f}-w{row['band']}-int-1b.fits")
    t0 = time.time()
    try:
        r = requests.get(url, params={"center": f"{ra},{dec}", "size": f"{STAMP_ARCMIN}arcmin"},
                         headers=UA, timeout=120)
        r.raise_for_status()
        return row, r.content, time.time() - t0, ""
    except requests.RequestException as e:
        return row, None, time.time() - t0, str(e)[:120]


def pick(frames: list[dict], k: int) -> list[dict]:
    if len(frames) <= k:
        return frames
    idx = np.linspace(0, len(frames) - 1, k).round().astype(int)
    return [frames[i] for i in idx]


def stack(blobs: list[bytes], wout: WCS) -> tuple[np.ndarray, int]:
    layers = []
    for b in blobs:
        if b[:2] == b"\x1f\x8b":  # IBE returns gzipped FITS
            b = gzip.decompress(b)
        with fits.open(io.BytesIO(b)) as h:
            data = h[0].data.astype(float)
            if data.size < 100:  # edge-of-frame slivers
                continue
            img, fp = reproject_interp((data, WCS(h[0].header)), wout, shape_out=wout.pixel_shape[::-1])
            img[fp < 0.99] = np.nan
            img -= np.nanmedian(img)
            layers.append(img)
    if not layers:
        return np.full(wout.pixel_shape[::-1], np.nan), 0
    return np.nanmedian(np.array(layers), axis=0), len(layers)


def run(key: str, bands: tuple[int, ...] = (1, 2)) -> dict:
    t = json.load(open(CACHE / "targets.json"))[key]
    ra, dec = position_at(t, REF_EPOCH)
    out = CACHE / key
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    rows, search_t = search(ra, dec)
    wout = target_wcs(ra, dec)
    report = {"target": key, "centre": [ra, dec], "search_s": search_t, "bands": {}}
    for band in bands:
        visits = group_visits([r for r in rows if r["band"] == band])
        hdus, lat, sizes, errors, per_visit = [fits.PrimaryHDU()], [], [], [], []
        for v in visits:
            chosen = pick(v, MAX_PER_VISIT)
            with ThreadPoolExecutor(WORKERS) as ex:
                res = list(ex.map(lambda r: fetch(r, ra, dec), chosen))
            blobs = [b for _, b, _, _ in res if b]
            lat += [dt for _, b, dt, _ in res if b]
            sizes += [len(b) for b in blobs]
            errors += [e for *_, e in res if e]
            img, n = stack(blobs, wout)
            mjd = float(np.mean([r["mjd"] for r in v]))
            hdr = wout.to_header()
            hdr["MJDMEAN"] = mjd
            hdr["NFRAMES"] = (n, "frames stacked")
            hdr["NAVAIL"] = (len(v), "frames available in visit")
            hdus.append(fits.ImageHDU(img.astype(np.float32), header=hdr))
            per_visit.append({"mjd": round(mjd, 2), "year": round(float(Time(mjd, format="mjd").decimalyear), 2),
                              "n_avail": len(v), "n_stacked": n})
        fits.HDUList(hdus).writeto(out / f"stack-w{band}.fits", overwrite=True)
        report["bands"][band] = {
            "n_visits": len(visits), "visits": per_visit,
            "cutouts": len(lat), "errors": errors[:5], "n_errors": len(errors),
            "latency_median_s": round(float(np.median(lat)), 2) if lat else None,
            "latency_p90_s": round(float(np.percentile(lat, 90)), 2) if lat else None,
            "size_median_kB": round(float(np.median(sizes)) / 1024, 1) if sizes else None,
        }
    report["wall_s"] = round(time.time() - t0, 1)
    json.dump(report, open(out / "timings.json", "w"), indent=1)
    return report


if __name__ == "__main__":
    bands = tuple(int(b) for b in sys.argv[2].split(",")) if len(sys.argv) > 2 else (1, 2)
    if len(sys.argv) > 3:
        MAX_PER_VISIT = int(sys.argv[3])
    if len(sys.argv) > 4:  # smoke test: only the first N visits
        _gv = group_visits
        group_visits = lambda rows: _gv(rows)[: int(sys.argv[4])]  # noqa: E731
    rep = run(sys.argv[1], bands)
    print(json.dumps({k: v for k, v in rep.items() if k != "bands"}, indent=1))
    for b, d in rep["bands"].items():
        print(f"W{b}: visits={d['n_visits']} cutouts={d['cutouts']} err={d['n_errors']} "
              f"lat_med={d['latency_median_s']}s p90={d['latency_p90_s']}s size={d['size_median_kB']}kB")
        print("   years:", [v["year"] for v in d["visits"]])
        print("   stacked:", [v["n_stacked"] for v in d["visits"]])
