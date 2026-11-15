"""Comparison stars from the 2MASS PSC (IRSA TAP): similar Ks, 1-6 arcmin away, isolated, good photometry."""
import numpy as np
from tap import tap, IRSA


def pick(ra, dec, ks, n=3, dks=1.0, rmin=1.0, rmax=6.0, exclude_r=20.0):
    t = tap(IRSA, f"SELECT ra, dec, k_m, ph_qual, designation FROM fp_psc WHERE CONTAINS(POINT('ICRS', ra, dec), CIRCLE('ICRS', {ra}, {dec}, {rmax/60 + 0.01})) = 1 AND k_m < {ks + 4}")
    r = np.asarray(t["ra"], float); d = np.asarray(t["dec"], float); k = np.asarray(t["k_m"], float)
    q = np.asarray(t["ph_qual"]).astype(str)
    cosd = np.cos(np.radians(dec))
    sep = np.hypot((r - ra) * cosd, d - dec) * 60
    out = []
    for i in np.argsort(np.abs(k - ks)):
        if not (rmin <= sep[i] <= rmax and abs(k[i] - ks) <= dks and q[i] == "AAA"):
            continue
        nb = np.hypot((r - r[i]) * cosd, d - d[i]) * 3600
        if np.any((nb > 0.5) & (nb < exclude_r) & (k < k[i] + 3)):
            continue
        out.append((str(t["designation"][i]), float(r[i]), float(d[i]), float(k[i]), float(sep[i])))
        if len(out) == n:
            break
    return out

if __name__ == "__main__":
    import sys
    print(pick(float(sys.argv[1]), float(sys.argv[2]), float(sys.argv[3])))
