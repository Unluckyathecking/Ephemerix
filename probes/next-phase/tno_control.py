import sys, numpy as np
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from astroquery.ipac.irsa import Most
sys.path.insert(0, "src")
from pxs.spherex.net import BlockStore
from pxs.spherex.query import find_frames
from pxs.spherex.read import read_stamp
from pxs.spherex.photometry import measure
BLO, BHI = float(sys.argv[2]), float(sys.argv[3])
OFF = [(10,0),(-10,0),(0,10),(0,-10),(7,7),(-7,7),(7,-7),(-7,-7)]
r = Most.query_object(output_mode="Regular", obj_name=sys.argv[1], obs_begin="2025-04-01", obs_end="2026-10-30", catalog="spherex")["results"]
mjd = np.asarray(r["mjd_obs"], float); o = np.argsort(mjd)
p1 = np.split(o, np.where(np.diff(mjd[o]) > 20)[0] + 1)[0]
t1lo, t1hi = mjd[p1].min() - 1, mjd[p1].max() + 1
pos = [(float(r["ra_obj"][i]), float(r["dec_obj"][i])) for i in p1[::4]]   # ~29 positions along the pass-1 track
store = BlockStore(root=Path("cache/next-phase"))
jobs = []
for ra, dec in pos[::3]:   # ~10 positions, SIA per position
    fr = [f for f in find_frames(ra, dec) if not (t1lo <= f.mjd <= t1hi)]
    jobs += [(f.s3_key, ra, dec) for f in fr if f.em_min_um < BHI]   # D1/D4-pair? keep 0.75-1.1 frames
print("control jobs (frames from other passes, D1 range):", len(jobs))
def phot(job):
    k, ra, dec = job
    try: s = read_stamp(store, k, ra, dec, half=15)
    except Exception: return None
    if s is None or not (BLO <= s.wave_um < BHI): return None
    return measure(s), [measure(s, dx, dy) for dx, dy in OFF]
with ThreadPoolExecutor(8) as ex: res = [x for x in ex.map(phot, jobs[:120]) if x is not None]
rows = [(m, offs) for m, offs in res if m.ok]
f = np.array([m.flux_mjy for m, _ in rows]); e = np.array([m.err_mjy for m, _ in rows])
offz = np.array([q.flux_mjy / q.err_mjy for _, offs in rows for q in offs if q.ok and q.err_mjy > 0])
scale = max(1.0, 1.4826 * np.median(np.abs(offz - np.median(offz))))
w = 1 / (e * scale) ** 2
print(f"CONTROL {BLO}-{BHI} um at Eris pass-1 track positions, other passes: n={len(f)} combined {np.sum(w*f)/np.sum(w)*1e3:.1f} +- {1e3/np.sqrt(np.sum(w)):.1f} uJy; "
      f"per-frame z: median {np.median(f/(e*scale)):.2f}, max {np.max(f/(e*scale)):.1f}")

from pxs.spherex.read import read_stamp as _rs
jobs1=[(str(r["image_url"][i]).split("?")[0].split("/ibe/data/spherex/")[-1], float(r["ra_obj"][i]), float(r["dec_obj"][i])) for i in p1]
with ThreadPoolExecutor(8) as ex: res1=[x for x in ex.map(phot, jobs1) if x is not None]
rows=[(m,offs) for m,offs in res1 if m.ok]
f=np.array([m.flux_mjy for m,_ in rows]); e=np.array([m.err_mjy for m,_ in rows])
offz=np.array([q.flux_mjy/q.err_mjy for _,offs in rows for q in offs if q.ok and q.err_mjy>0])
sc=max(1.0,1.4826*np.median(np.abs(offz-np.median(offz)))); w=1/(e*sc)**2
print(f"ON-TRACK pass 1 {BLO}-{BHI} um: n={len(f)} combined {np.sum(w*f)/np.sum(w)*1e3:.1f} +- {1e3/np.sqrt(np.sum(w)):.1f} uJy")
