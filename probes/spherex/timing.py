"""Check 7: cold end-to-end timing, position in -> one pass of stamps + spectrum out.

Usage: uv run python timing.py rw_aur 2026-09-01 20
Steps timed: SIA (dr1 + qr3 in parallel) -> stamps for one pass (8 threads, no cache)
-> photometry. Counts S3 GETs to separate latency from bytes.
"""
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from astropy.time import Time

import phot
import stamp
from query import sia_frames
from targets import coord_at

GETS = {"n": 0}
_orig_init = stamp._CountingFile.__init__


def _counting_init(self, f):
    _orig_init(self, f)
    inner = f._fetch_range

    def counted(a, b):
        GETS["n"] += 1
        return inner(a, b)

    f._fetch_range = counted
    f.cache.fetcher = counted


stamp._CountingFile.__init__ = _counting_init


def main(target: str, start: str, days: float) -> None:
    t_all = time.time()
    c = coord_at(target, Time(start))
    with ThreadPoolExecutor(2) as ex:
        res = list(ex.map(lambda col: sia_frames(col, c.ra.deg, c.dec.deg),
                          ["spherex_dr1", "spherex_qr3"]))
    t_sia = time.time() - t_all
    t0 = Time(start).mjd
    fs = [f for r in res for f in r if t0 <= f["mjd"] < t0 + days]
    print(f"SIA dr1+qr3: {sum(map(len, res))} frames in {t_sia:.1f}s; pass has {len(fs)} frames")
    t1 = time.time()
    with ThreadPoolExecutor(phot.WORKERS) as ex:
        sts = list(ex.map(lambda f: stamp.read_stamp(f["s3_key"], *(lambda p: (p.ra.deg, p.dec.deg))(
            coord_at(target, f["mjd"])), psf=True), fs))
    t_st = time.time() - t1
    nb = sum(s.bytes_read for s in sts)
    print(f"stamps: {len(sts)} in {t_st:.1f}s with {phot.WORKERS} threads; {GETS['n']} GETs "
          f"({GETS['n'] / len(sts):.1f}/frame), {nb / 1e6:.0f} MB ({nb / len(sts) / 1e6:.1f} MB/frame)")
    t2 = time.time()
    n_ok = 0
    for s in sts:
        d = dict(image=s.image, flags=s.flags, variance=s.variance, zodi=s.zodi, psf=s.psf[0],
                 x0=s.x0, y0=s.y0, xpix=s.xpix, ypix=s.ypix, wave=s.wave_um, band=s.band_um,
                 mjd=s.mjd, det=s.detector)
        n_ok += np.isfinite(phot.photometry(d)["flux"])
    print(f"photometry: {time.time() - t2:.2f}s ({n_ok}/{len(sts)} unmasked)")
    print(f"total {time.time() - t_all:.1f}s; per-frame thread time {t_st * phot.WORKERS / len(sts):.2f}s")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], float(sys.argv[3]))
