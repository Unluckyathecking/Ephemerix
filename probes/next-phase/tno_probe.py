"""Go/no-go: is a known TNO detected in single SPHEREx frames at the MOST-predicted position?
Forced PSF photometry at the ephemeris position vs at 8 offset positions (60" away)."""
import sys, time, numpy as np
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from astroquery.ipac.irsa import Most
sys.path.insert(0, "src")
from pxs.spherex import config
from pxs.spherex.net import BlockStore
from pxs.spherex.read import read_stamp
from pxs.spherex.photometry import measure
name = sys.argv[1]; nmax = int(sys.argv[2]) if len(sys.argv) > 2 else 40
t0 = time.time()
r = Most.query_object(output_mode="Regular", obj_name=name, obs_begin="2025-04-01", obs_end="2026-10-30", catalog="spherex")
res = r["results"]
print(f"{name}: {len(res)} frames, MOST {time.time()-t0:.1f}s, V {np.min(res['vmag']):.1f}-{np.max(res['vmag']):.1f}, "
      f"r_helio {np.mean(res['sun_dist']):.1f} au, mjd {res['mjd_obs'].min():.0f}-{res['mjd_obs'].max():.0f}")
mjd = np.asarray(res["mjd_obs"], float)
# take the frames of the first pass (gap > 20 d splits passes)
order = np.argsort(mjd); cut = np.where(np.diff(mjd[order]) > 20)[0]
first = order[: (cut[0] + 1) if len(cut) else len(order)]
sel = first[np.linspace(0, len(first) - 1, min(nmax, len(first))).astype(int)]
store = BlockStore(root=Path("cache/next-phase"))
pfx = config.IBE_PREFIX
def one(i):
    row = res[i]; key = str(row["image_url"]).split("?")[0]
    key = key[len(pfx):] if key.startswith(pfx) else key.split("/ibe/data/spherex/")[-1]
    try:
        s = read_stamp(store, key, float(row["ra_obj"]), float(row["dec_obj"]), half=15)
    except Exception as e:
        return None
    if s is None: return None
    on = measure(s)
    offs = [measure(s, dx, dy) for dx, dy in [(10,0),(-10,0),(0,10),(0,-10),(7,7),(-7,7),(7,-7),(-7,-7)]]
    return s.wave_um, s.detector, on, offs
t1 = time.time()
with ThreadPoolExecutor(8) as ex: out = [o for o in ex.map(one, sel) if o is not None]
print(f"read {len(out)} stamps in {time.time()-t1:.0f}s; pass span {mjd[first].min():.1f}-{mjd[first].max():.1f}")
on = np.array([(w, d, o.flux_mjy, o.err_mjy) for w, d, o, _ in out if o.ok])
off = np.array([m.flux_mjy for *_, offs in out for m in offs if m.ok])
offsig = 1.4826 * np.median(np.abs(off - np.median(off)))
print(f"on-target ok: {len(on)}; median flux {np.median(on[:,2]):.3f} mJy; median var-err {np.median(on[:,3]):.3f}; "
      f"offset-position robust sigma per frame {offsig:.3f} mJy")
print(f"frames with on/offset_sigma > 5: {np.sum(on[:,2]/offsig>5)} / {len(on)}")
for lo, hi in [(0.75,1.1),(1.1,1.65),(1.65,2.42),(2.42,3.82),(3.82,5.0)]:
    m = (on[:,0]>=lo)&(on[:,0]<hi)
    if m.any(): print(f"  {lo}-{hi} um: n={m.sum():2d} median flux {np.median(on[m,2]):.3f} mJy, S/N(offset) per frame {np.median(on[m,2])/offsig:.1f}")
