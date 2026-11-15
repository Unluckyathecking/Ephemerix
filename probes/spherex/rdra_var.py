"""Check 4b: does R Dra change between epochs? Outer-ring brightness at matched wavelengths.

R Dra saturates every detector (core masked out to r~4-6 px), so the only per-frame
measure is the zodi-subtracted surface brightness in a 9-13 px ring (relative).
Compares 14-day windows; pairs frames on the same detector within 15 nm.
"""
import numpy as np
from astropy.time import Time

from phot import frames, get_stamps
from spectrum import wing_flux

WINDOWS = ["2025-06-02", "2025-06-22", "2026-06-12"]
DETS = (2, 5)  # the detectors all three windows share


def measure(start: str) -> list[dict]:
    t0 = Time(start).mjd
    fs = [f for f in frames("r_dra") if t0 <= f["mjd"] < t0 + 14 and f["detector"] in DETS]
    out = []
    for d in get_stamps("r_dra", fs):
        # 9-13 px ring: outside every saturation footprint, so a brighter epoch
        # (bigger footprint) cannot bias the ring mean
        fl, _ = wing_flux(d, 9.0, 13.0, r_bkg=13.5, min_good=0.9)
        if np.isfinite(fl):
            out.append(dict(w=float(d["wave"]), det=int(d["det"]), f=fl, mjd=float(d["mjd"])))
    return out


def pair_ratios(a: list[dict], b: list[dict], tol: float = 0.015) -> np.ndarray:
    rat = []
    for x in a:
        cand = [y for y in b if y["det"] == x["det"] and abs(y["w"] - x["w"]) < tol and y is not x]
        if cand:
            y = min(cand, key=lambda y: abs(y["w"] - x["w"]))
            rat.append(y["f"] / x["f"])
    return np.array(rat)


def main() -> None:
    m = {w: measure(w) for w in WINDOWS}
    for w, rows in m.items():
        print(f"{w}: {len(rows)} frames measured")
    within = pair_ratios(m[WINDOWS[0]], m[WINDOWS[0]], tol=0.03)
    print(f"within {WINDOWS[0]} (repeat, <30 nm): n={len(within)} median ratio "
          f"{np.median(within):.2f}, scatter (MAD) {1.4826 * np.median(np.abs(within - np.median(within))):.2f}")
    for a, b in [(0, 1), (0, 2), (1, 2)]:
        for det in DETS:
            r = pair_ratios([x for x in m[WINDOWS[a]] if x["det"] == det],
                            [x for x in m[WINDOWS[b]] if x["det"] == det])
            if len(r):
                print(f"{WINDOWS[b]} / {WINDOWS[a]} D{det}: n={len(r)} median {np.median(r):.2f} "
                      f"(16-84%: {np.percentile(r, 16):.2f}-{np.percentile(r, 84):.2f}) "
                      f"= {-2.5 * np.log10(np.median(r)):+.2f} mag")


if __name__ == "__main__":
    main()
