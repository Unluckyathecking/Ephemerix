"""Approximate deep-field coverage: frames whose centre lies within 1.6 deg of a point (frame is ~3.5 deg square)."""
import numpy as np
from pathlib import Path
C = Path(__file__).resolve().parents[2] / "cache" / "variables"
P = np.vstack([np.load(C / f"spherex_{c}_deep_pos.npy") for c in ("dr1", "qr3")])

def unit(ra, dec):
    ra, dec = np.radians(ra), np.radians(dec)
    return np.c_[np.cos(dec)*np.cos(ra), np.cos(dec)*np.sin(ra), np.sin(dec)]

U = unit(P[:, 0], P[:, 1])

def coverage(ra, dec, r=1.6):
    v = unit(np.atleast_1d(ra), np.atleast_1d(dec))
    cos_r = np.cos(np.radians(r))
    return (v @ U.T > cos_r).sum(axis=1)

if __name__ == "__main__":
    for name, (ra0, dec0) in {"north": (270, 66.56), "south": (80, -64)}.items():
        print(name)
        decs = np.arange(dec0 - 12, dec0 + 12.1, 2)
        for d in decs:
            if abs(d) > 89.9: continue
            ras = (ra0 + np.arange(-40, 41, 8) / max(np.cos(np.radians(d)), 0.2)) % 360
            print(f"{d:6.1f} " + " ".join(f"{c:5d}" for c in coverage(ras, np.full_like(ras, d))))
    print("LMC 80.9,-69.75:", coverage(80.9, -69.75), " R Dra:", coverage(248.17, 66.76), " NEP:", coverage(270, 66.56))
