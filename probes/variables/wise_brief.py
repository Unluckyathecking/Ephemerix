"""WISE/NEOWISE single-exposure photometry for R Dra and RW Aur (IRSA TAP), grouped per ~6-month visit."""
import numpy as np
from tap import tap, IRSA

STARS = {"R Dra": (248.16761, 66.75498), "RW Aur": (76.95653, 30.40144)}
COLS = {"neowiser_p1bs_psd": "mjd, w1mpro, w1sigmpro, w2mpro, w2sigmpro, w1sat, w2sat, qual_frame, nb, na",
        "allwise_p3as_mep": "mjd, w1mpro_ep AS w1mpro, w1sigmpro_ep AS w1sigmpro, w2mpro_ep AS w2mpro, w2sigmpro_ep AS w2sigmpro, w1rchi2_ep AS w1sat, w2rchi2_ep AS w2sat, nb, na"}


def get(name):
    ra, dec = STARS[name]
    cone = f"CONTAINS(POINT('ICRS', ra, dec), CIRCLE('ICRS', {ra}, {dec}, 0.0014)) = 1"
    out = []
    for table in ("allwise_p3as_mep", "neowiser_p1bs_psd"):
        cols = COLS[table]
        t = tap(IRSA, f"SELECT {cols} FROM {table} WHERE {cone}")
        t["table"] = table
        out.append(t)
    return out


if __name__ == "__main__":
    for name in STARS:
        for t in get(name):
            if not len(t):
                print(name, t["table"] if len(t) else "", "no rows"); continue
            m = np.asarray(t["mjd"], float); order = np.argsort(m)
            m = m[order]
            w1 = np.asarray(t["w1mpro"], float)[order]; w2 = np.asarray(t["w2mpro"], float)[order]
            s1 = np.asarray(t["w1sat"], float)[order]; s2 = np.asarray(t["w2sat"], float)[order]
            q = np.asarray(t["qual_frame"], float)[order] if "qual_frame" in t.colnames else np.ones(len(m))
            # visits
            cut = np.where(np.diff(m) > 30)[0] + 1
            print(f"== {name} {t['table'][0]}: {len(t)} rows")
            for g in np.split(np.arange(len(m)), cut):
                good = g[(q[g] > 0)]
                if not len(good): good = g
                print(f"  {m[g].min():.1f} n={len(g):3d}  W1 med {np.nanmedian(w1[good]):6.3f} rms {np.nanstd(w1[good]):.3f} sat {np.nanmedian(s1[good]):.2f} | "
                      f"W2 med {np.nanmedian(w2[good]):6.3f} rms {np.nanstd(w2[good]):.3f} sat {np.nanmedian(s2[good]):.2f}")
