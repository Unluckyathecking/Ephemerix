"""Adversarial check of the R Dra wing light curve (15 Nov 2026). Cached stamps only.

Written down before looking at any output, the analysis FAILS if any of these hold:
  F1 the re-run per-exposure wing series differs from the 14 Nov series by more than 1% (median |ratio-1|);
  F2 a control star under the identical procedure shows a fitted semi-amplitude more than a third of R Dra's
     on the same detector, or the control's best period has a fit as strong as R Dra's;
  F3 R Dra's relative brightness tracks zodiacal level, local background or detector position more
     strongly than it tracks time (|r| with a nuisance > |r| with the time model);
  F4 an unconstrained period search does not find a period consistent with 246 d (best period outside the
     bootstrap interval, or interval wider than 100-1000 d, i.e. no period measured);
  F5 dropping any one pass changes the semi-amplitude by more than 50% or the phase of maximum by more
     than 0.15 cycles on a detector carrying the headline;
  F6 a "relative" point is built from a template that only contains exposures from its own pass (then it
     is 1 by construction and the curve is a colour effect, not a time effect).

Usage (from probes/variables): PXS_CACHE=<cache with the 14 Nov SIA lists> uv run python verify.py
Writes cache/variables/lc/<name>-diag.json and prints a verdict table.
"""
from __future__ import annotations

import json
import sys

import numpy as np

from analysis import LC, relative, robust_std, sine_fit
from lightcurve import ALL, STORE_ROOT, subsample
from pxs.spherex.net import BlockStore
from pxs.spherex.photometry import good_mask, radius
from pxs.spherex.query import find_frames
from pxs.spherex.stamps import read_many

P_VSX, T0 = 246.12, 2457370.0 - 2400000.5
STARS = {"r-dra": (248.16761, 66.75498), "control-2m1640": (250.229708, 64.589027),
         "control-2m1628": (247.087918, 67.044052)}
PASS_GAP = 5.0  # days between exposure groups that start a new pass


def diag(s) -> dict:
    """Wing flux exactly as rdra_lc.wing, plus the nuisances it could be tracking."""
    img = s.image - s.zodi
    good = good_mask(s)
    r = radius(s, s.xpix, s.ypix)
    bk, ring, full = good & (r >= 13.5), good & (r >= 9) & (r < 13), (r >= 9) & (r < 13)
    out = {"mjd": s.mjd, "det": s.detector, "wl": s.wave_um, "x": s.xpix, "y": s.ypix,
           "zodi": float(np.nanmedian(s.zodi)), "wing": np.nan, "bkg": np.nan, "good": float(ring.sum() / full.sum())}
    if bk.sum() >= 20 and ring.sum() >= 0.9 * full.sum():
        out["bkg"] = float(np.median(img[bk]))
        out["wing"] = float(np.mean(img[ring]) - out["bkg"])
    return out


def collect(name: str) -> list[dict]:
    path = LC / f"{name}-diag.json"
    if path.exists():
        return json.loads(path.read_text())
    ra, dec = STARS[name]
    use = subsample(find_frames(ra, dec, collections=ALL), 400)
    b = read_many([(f, ra, dec) for f, in zip(use)], 17, with_psf=False, store=BlockStore(root=STORE_ROOT), workers=8)
    rows = [diag(s) | {"coll": f.collection} for f, s in b.stamps]
    path.write_text(json.dumps(rows, default=float))
    return rows


def arrays(rows: list[dict]) -> dict[str, np.ndarray]:
    a = {k: np.array([r[k] for r in rows], float) for k in ("mjd", "det", "wl", "x", "y", "zodi", "wing", "bkg")}
    o = np.argsort(a["mjd"])
    a = {k: v[o] for k, v in a.items()}
    a["pass"] = np.concatenate([[0], np.cumsum(np.diff(a["mjd"]) > PASS_GAP)])
    a["rel"], _ = relative(a["wl"], a["det"], a["wing"], np.ones_like(a["wing"]), frac=1 / 60, min_n=4)
    return a


def fit(t, y, period):
    """Two-pass fit with the residual scatter as the error. Returns (semi-amp, amp err, phase of max, sigma, dchi2)."""
    s = np.isfinite(y)
    t, y = t[s], y[s]
    _, _, m, *_ = sine_fit(t - T0, y, np.full(len(y), 0.1), period)
    sig = robust_std(y - m(t - T0))
    c, cov, m, chi2, chi2c, n = sine_fit(t - T0, y, np.full(len(y), sig), period)
    ph = (np.arctan2(c[2], c[1]) / (2 * np.pi)) % 1
    return np.hypot(c[1], c[2]), np.sqrt(np.mean(np.diag(cov)[1:])), (ph + 0.5) % 1 - 0.5, sig, chi2c - chi2


def periodogram(a, dets, periods):
    """Summed per-detector delta chi2 (each detector its own amplitude and phase, own scatter at P_VSX)."""
    tot = np.zeros(len(periods))
    for k in dets:
        s = (a["det"] == k) & np.isfinite(a["rel"])
        if s.sum() < 8 or len(np.unique(np.round(a["mjd"][s]))) < 4:
            continue
        sig = fit(a["mjd"][s], a["rel"][s], P_VSX)[3]
        for i, p in enumerate(periods):
            _, _, _, chi2, chi2c, _ = sine_fit(a["mjd"][s] - T0, a["rel"][s], np.full(s.sum(), sig), p)
            tot[i] += chi2c - chi2
    return tot


def main() -> None:
    rng = np.random.default_rng(1)
    periods = np.exp(np.linspace(np.log(60), np.log(1500), 600))
    orig = {(round(r["mjd"], 6), r["det"]): r["wing"] for r in json.loads((LC.parent / "lc_orig" / "r-dra-wing.json").read_text())["rows"]}
    new = {(round(r["mjd"], 6), r["det"]): r["wing"] for r in json.loads((LC / "r-dra-wing.json").read_text())["rows"]}
    rat = np.array([new[k] / orig[k] for k in orig if k in new and orig[k] and new[k] and np.isfinite(orig[k] / new[k])])
    print(f"F1 reproduction: {len(rat)} matched exposures of {len(orig)}, median |ratio-1| = {np.median(np.abs(rat - 1)):.2e}")
    res = {}
    for name in STARS:
        a = arrays(collect(name))
        ok = np.isfinite(a["rel"])
        print(f"\n== {name}: {len(a['mjd'])} exposures, {ok.sum()} with relative brightness, passes {a['pass'].max() + 1}")
        # F6: passes contributing to each template
        selfonly = 0
        for i in np.where(ok)[0]:
            near = np.isfinite(a["wing"]) & (a["det"] == a["det"][i]) & (np.abs(a["wl"] - a["wl"][i]) <= a["wl"][i] / 60)
            selfonly += len(np.unique(a["pass"][near])) == 1
        print(f"  F6 templates from a single pass: {selfonly} of {ok.sum()}")
        dets = [k for k in range(1, 7) if ((a["det"] == k) & ok).sum() >= 15]
        res[name] = {}
        for k in dets:
            s = (a["det"] == k) & ok
            amp, ae, ph, sig, d2 = fit(a["mjd"][s], a["rel"][s], P_VSX)
            t, y = a["mjd"][s], a["rel"][s]
            _, _, m, *_ = sine_fit(t - T0, y, np.full(len(y), sig), P_VSX)
            r_time = np.corrcoef(m(t - T0), y)[0, 1]
            nuis = {q: np.corrcoef(a[q][s], y)[0, 1] for q in ("zodi", "bkg", "x", "y") if np.isfinite(a[q][s]).all()}
            # nuisance after removing the time model: does it explain the residual?
            nres = {q: np.corrcoef(a[q][s], y - m(t - T0))[0, 1] for q in nuis}
            drops = []
            for p in np.unique(a["pass"][s]):
                keep = a["pass"][s] != p
                if keep.sum() >= 12:
                    da, _, dp, *_ = fit(t[keep], y[keep], P_VSX)
                    drops.append((int(p), int((~keep).sum()), da, dp))
            res[name][k] = (amp, ph)
            frac = a["bkg"][s] / a["wing"][s]
            _, _, mf, *_ = sine_fit(t - T0, frac, np.full(len(y), 0.1), P_VSX)
            print(f"     bkg/wing median {np.nanmedian(frac):.2f}, r(bkg/wing, time model) {np.corrcoef(m(t - T0), frac)[0, 1]:+.2f}")
            print(f"  D{k} n={s.sum():3d} semi-amp {amp:.3f}±{ae:.3f} phase {ph:+.2f} scatter {sig:.3f} dchi2 {d2:.0f}"
                  f"  r(time model) {r_time:+.2f}  r(nuisance) " + " ".join(f"{q}{v:+.2f}" for q, v in nuis.items())
                  + "  r(nuis, resid) " + " ".join(f"{q}{v:+.2f}" for q, v in nres.items()))
            if drops:
                amps = np.array([d[2] for d in drops]); phs = np.array([d[3] for d in drops])
                print(f"     F5 drop-one-pass: amp {amps.min():.3f}-{amps.max():.3f} (max change {np.max(np.abs(amps / amp - 1)):.0%}),"
                      f" phase {phs.min():+.2f} to {phs.max():+.2f}  [passes dropped: {[(d[0], d[1]) for d in drops]}]")
        pg = periodogram(a, dets, periods)
        best = periods[np.argmax(pg)]
        # bootstrap over passes (errors within a pass are correlated)
        bs = []
        passes = np.unique(a["pass"][ok])
        for _ in range(150):
            pick = rng.choice(passes, len(passes))
            idx = np.concatenate([np.where(a["pass"] == p)[0] for p in pick])
            b = {q: v[idx] for q, v in a.items()}
            b["mjd"] = b["mjd"] + rng.normal(0, 1e-3, len(idx))
            bs.append(periods[np.argmax(periodogram(b, dets, periods))])
        lo, hi = np.percentile(bs, [16, 84])
        print(f"  F4 free period: best {best:.0f} d (dchi2 {pg.max():.0f}; at 246 d {np.interp(P_VSX, periods, pg):.0f}),"
              f" pass bootstrap 16-84%: {lo:.0f}-{hi:.0f} d, 2.5-97.5%: {np.percentile(bs, 2.5):.0f}-{np.percentile(bs, 97.5):.0f} d")
        top = np.argsort(pg)[::-1]
        print("     periodogram peaks:", [(round(periods[i]), round(pg[i])) for i in top[:40:8]])
        np.save(LC / f"{name}-pgram.npy", np.c_[periods, pg])
    print("\nF2 control / R Dra semi-amplitude per detector:")
    for k, (amp, _) in res["r-dra"].items():
        print(f"  D{k}: " + "  ".join(f"{c} {res[c][k][0] / amp:.2f}" for c in res if c != "r-dra" and k in res[c]))


if __name__ == "__main__":
    sys.exit(main())
