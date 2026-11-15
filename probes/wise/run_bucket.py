"""End to end: position in -> one stacked W1/W2 stamp per visit out, from s3://nasa-irsa-wise.

Run: uv run --with reproject python probes/wise/run_bucket.py <target> [bands=1,2] [workers=16]
Writes cache/wise/<target>/bucket-w<band>.fits (one HDU per visit) and bucket-timings.json.
"""
from __future__ import annotations

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from astropy.io import fits
from astropy.time import Time

sys.path.insert(0, str(Path(__file__).parent))
from targets import CACHE, REF_EPOCH, position_at  # noqa: E402
from l1b_bucket import Frame, Stamp, find_frames, read_stamp  # noqa: E402
from visits import PIX_ARCSEC, group_visits, north_up_grid, stack_visit  # noqa: E402

STAMP_ARCMIN = 4.0
RADIUS_PIX = int(np.ceil(STAMP_ARCMIN * 60 / 2 * np.sqrt(2) / PIX_ARCSEC)) + 2  # any rotation


def read_all(frames: list[Frame], ra: float, dec: float, workers: int) -> tuple[dict, dict]:
    """Read every frame's stamp; one retry on failure. Returns {key: Stamp} and stats."""
    lat, errors = [], []

    def one(f: Frame) -> tuple[Frame, Stamp | None]:
        for attempt in range(2):
            t0 = time.time()
            try:
                s = read_stamp(f, ra, dec, RADIUS_PIX)
                lat.append(time.time() - t0)
                return f, s
            except Exception as e:  # network or parse error: record, retry once
                errors.append(f"{type(e).__name__}: {str(e)[:80]}")
        return f, None

    t0 = time.time()
    with ThreadPoolExecutor(workers) as ex:
        res = list(ex.map(one, frames))
    stamps = {f.key: s for f, s in res if s is not None}
    nbytes = sum(s.nbytes for s in stamps.values())
    return stamps, {"frames": len(frames), "ok": len(stamps), "errors": len(errors),
                    "error_samples": errors[:3], "wall_s": round(time.time() - t0, 1),
                    "lat_median_s": round(float(np.median(lat)), 2) if lat else None,
                    "lat_p90_s": round(float(np.percentile(lat, 90)), 2) if lat else None,
                    "MB": round(nbytes / 1e6, 1), "kB_per_frame": round(nbytes / 1e3 / max(len(stamps), 1), 0)}


def pick4(stamps: list[Stamp]) -> list[Stamp]:
    if len(stamps) <= 4:
        return stamps
    return [stamps[i] for i in np.linspace(0, len(stamps) - 1, 4).round().astype(int)]


def run(key: str, bands: tuple[int, ...], workers: int) -> dict:
    t = json.load(open(CACHE / "targets.json"))[key]
    ra, dec = position_at(t, REF_EPOCH)
    grid = north_up_grid(ra, dec, STAMP_ARCMIN)
    t0 = time.time()
    frames = [f for f in find_frames(ra, dec) if f.band in bands]
    t_find = time.time() - t0
    stamps, read_stats = read_all(frames, ra, dec, workers)
    t_read = time.time() - t0 - t_find
    report = {"target": key, "workers": workers, "find_s": round(t_find, 1), "read": read_stats,
              "bands": {}}
    for band in bands:
        hdus, rows = [fits.PrimaryHDU()], []
        for visit in group_visits([f for f in frames if f.band == band]):
            got = [stamps[f.key] for f in visit if f.key in stamps]
            vs = stack_visit(got, grid, len(visit))
            v4 = stack_visit(pick4(got), grid, len(visit))
            hdr = grid.to_header()
            hdr.update(MJDMEAN=vs.mjd, NFRAMES=vs.n_used, NAVAIL=vs.n_avail, NSAT=vs.n_saturated)
            hdus.append(fits.ImageHDU(vs.image.astype(np.float32), header=hdr))
            rows.append({"year": round(float(Time(vs.mjd, format="mjd").decimalyear), 2),
                         "n_avail": vs.n_avail, "n_used": vs.n_used, "rejected": vs.rejected,
                         "noise_all": round(vs.noise, 2), "noise_4": round(v4.noise, 2),
                         "depth_gain_mag": round(2.5 * np.log10(v4.noise / vs.noise), 2)})
        fits.HDUList(hdus).writeto(CACHE / key / f"bucket-w{band}.fits", overwrite=True)
        report["bands"][band] = {"visits": rows, "n_visits": len(rows),
                                 "median_used": float(np.median([r["n_used"] for r in rows])),
                                 "median_depth_gain_mag": float(np.median([r["depth_gain_mag"] for r in rows]))}
    report["stack_s"] = round(time.time() - t0 - t_find - t_read, 1)
    report["total_s"] = round(time.time() - t0, 1)
    json.dump(report, open(CACHE / key / "bucket-timings.json", "w"), indent=1)
    return report


if __name__ == "__main__":
    bands = tuple(int(b) for b in sys.argv[2].split(",")) if len(sys.argv) > 2 else (1, 2)
    workers = int(sys.argv[3]) if len(sys.argv) > 3 else 16
    rep = run(sys.argv[1], bands, workers)
    print(json.dumps({k: v for k, v in rep.items() if k != "bands"}, indent=1))
    for b, d in rep["bands"].items():
        print(f"W{b}: visits={d['n_visits']} median used={d['median_used']} "
              f"median depth gain vs 4 frames={d['median_depth_gain_mag']} mag")
        print("  ", [(r["year"], r["n_used"], r["n_avail"]) for r in d["visits"]])
        rej = {k: sum(r["rejected"][k] for r in d["visits"]) for k in ("moon", "edge", "noise")}
        print("   rejected:", rej)
