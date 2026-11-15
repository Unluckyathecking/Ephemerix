"""Does R Dra's SPHEREx wing brightness follow the VSX ephemeris? Fit a sinusoid at P=246.12 d per detector."""
import json, numpy as np
from analysis import relative, sine_fit, robust_std, bin_epochs, LC
P, T0 = 246.12, 2457370.0 - 2400000.5
d = json.loads((LC / "control-2m1640-wing.json").read_text())
R = d["rows"]
mjd = np.array([r["mjd"] for r in R]); det = np.array([r["det"] for r in R]); wl = np.array([r["wl"] for r in R])
f = np.array([r["wing"] if r["wing"] is not None else np.nan for r in R], float); e = np.array([r["err"] if r["err"] is not None else np.nan for r in R], float)
coll = np.array([r["coll"] for r in R])
rel, rerr = relative(wl, det, f, e, frac=1/60, min_n=4)
print("frames", len(R), "finite rel", np.isfinite(rel).sum(), "time span", mjd.min(), mjd.max())
print("MJD range per collection:", {c: (round(mjd[coll==c].min()), round(mjd[coll==c].max()), int((coll==c).sum())) for c in np.unique(coll)})
res = {}
for k in range(1, 7):
    s = (det == k) & np.isfinite(rel)
    if s.sum() < 15: print(f"D{k}: n={s.sum()} too few"); continue
    # empirical error: robust scatter of residuals after the fit, iterate once
    ee = np.full(s.sum(), 0.1)
    coef, cov, model, chi2, chi2c, n = sine_fit(mjd[s] - T0, rel[s], ee, P)
    resid = rel[s] - model(mjd[s] - T0)
    sig = robust_std(resid)
    coef, cov, model, chi2, chi2c, n = sine_fit(mjd[s] - T0, rel[s], np.full(s.sum(), sig), P)
    amp = np.hypot(coef[1], coef[2]); amp_err = np.sqrt(np.mean(np.diag(cov)[1:]))
    phmax = (np.arctan2(coef[2], coef[1]) / (2*np.pi)) % 1  # phase of maximum (0 = VSX max)
    phmax = phmax if phmax < 0.5 else phmax - 1
    lo, hi = coef[0] - amp, coef[0] + amp
    res[k] = dict(n=int(n), amp=amp, amp_err=amp_err, phmax=phmax, scatter=sig, mag_range=2.5*np.log10(hi/lo) if lo > 0 else np.nan, dchi2=chi2c-chi2)
    print(f"D{k}: n={n:3d} rel semi-amp {amp:.2f}±{amp_err:.2f} (={res[k]['mag_range']:.2f} mag pk-pk)  phase of max {phmax:+.2f} cycles ({phmax*P:+.0f} d)  resid scatter {sig:.2f}  dchi2 {chi2c-chi2:.0f}")
json.dump({"fit": res, "P": P, "T0": T0}, open(LC / "control-fold.json", "w"), default=float)
# combine all detectors (relative units) for a time plot dataset
np.save(LC / "control-rel.npy", np.c_[mjd, det, wl, rel])
