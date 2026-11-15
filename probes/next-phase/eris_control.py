"""Eris: (1) combined one-pass S/N per detector band with empty-aperture-scaled errors;
(2) control: same sky positions measured in the next pass (Eris ~7' away) should give ~0;
(3) per-band one-pass 5-sigma depth (mJy, AB) from the empty-aperture scatter."""
import sys, numpy as np
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from astroquery.ipac.irsa import Most
sys.path.insert(0, "src")
from pxs.spherex import config
from pxs.spherex.net import BlockStore
from pxs.spherex.read import read_stamp
from pxs.spherex.photometry import measure
OFF = [(10,0),(-10,0),(0,10),(0,-10),(7,7),(-7,7),(7,-7),(-7,-7)]
BANDS = [(0.75,1.1),(1.1,1.65),(1.65,2.42),(2.42,3.82),(3.82,5.0)]
r = Most.query_object(output_mode="Regular", obj_name="136199", obs_begin="2025-04-01", obs_end="2026-10-30", catalog="spherex")["results"]
mjd = np.asarray(r["mjd_obs"], float); o = np.argsort(mjd)
cuts = np.split(o, np.where(np.diff(mjd[o]) > 20)[0] + 1)
p1, p2 = cuts[0], cuts[1]
print("passes:", [(round(mjd[c].min()), round(mjd[c].max()), len(c)) for c in cuts])
store = BlockStore(root=Path("cache/next-phase"))
key = lambda row: str(row["image_url"]).split("?")[0].split("/ibe/data/spherex/")[-1]
def phot(job):
    k, ra, dec = job
    try: s = read_stamp(store, k, ra, dec, half=15)
    except Exception: return None
    if s is None: return None
    return s.wave_um, measure(s), [measure(s, dx, dy) for dx, dy in OFF]
def run(jobs):
    with ThreadPoolExecutor(8) as ex: return [x for x in ex.map(phot, jobs) if x is not None]
def summarise(label, res):
    print(label)
    for lo, hi in BANDS:
        rows = [(m, offs) for w, m, offs in res if lo <= w < hi and m.ok]
        if not rows: continue
        f = np.array([m.flux_mjy for m, _ in rows]); e = np.array([m.err_mjy for m, _ in rows])
        offz = np.array([q.flux_mjy / q.err_mjy for _, offs in rows for q in offs if q.ok and q.err_mjy > 0])
        scale = max(1.0, 1.4826 * np.median(np.abs(offz - np.median(offz))))
        w = 1 / (e * scale) ** 2; mean = np.sum(w * f) / np.sum(w); err = 1 / np.sqrt(np.sum(w))
        ab5 = -2.5 * np.log10(5 * err * 1e-3 / 3631)
        print(f"  {lo:4.2f}-{hi:4.2f} um n={len(f):2d} err_scale={scale:4.2f} combined {mean*1e3:7.1f} +- {err*1e3:5.1f} uJy  S/N {mean/err:5.1f}  one-pass 5sig {5*err*1e3:5.1f} uJy = AB {ab5:5.2f}")
res1 = run([(key(r[i]), float(r["ra_obj"][i]), float(r["dec_obj"][i])) for i in p1])
summarise("PASS 1, at Eris ephemeris:", res1)
# control: pass-2 frames, at the pass-1 positions (cycle through them)
pos1 = [(float(r["ra_obj"][i]), float(r["dec_obj"][i])) for i in p1]
res2 = run([(key(r[i]), *pos1[j % len(pos1)]) for j, i in enumerate(p2)])
d = np.hypot((np.median([p[0] for p in pos1]) - np.median(r["ra_obj"][p2])) * np.cos(np.radians(-1.5)), np.median([p[1] for p in pos1]) - np.median(r["dec_obj"][p2])) * 60
print(f"Eris moved {d:.1f} arcmin between passes")
summarise("CONTROL, pass-2 frames at pass-1 positions (Eris absent):", res2)
