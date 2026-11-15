"""Follow-up to verify.py (15 Nov): background as starlight, period from D1+D6 only, single-pass templates dropped,
pass-bootstrap amplitudes, and RW Aur split by collection with min_n=4. Cached files only.

Usage (from probes/variables): uv run python verify_followup.py
"""
import json

import numpy as np

from analysis import LC, relative, robust_std, sine_fit
from verify import P_VSX, T0, arrays, fit, periodogram

HEAD = (1, 6)


def single_pass_mask(a):
    bad = np.zeros(len(a["mjd"]), bool)
    for i in np.where(np.isfinite(a["rel"]))[0]:
        near = np.isfinite(a["wing"]) & (a["det"] == a["det"][i]) & (np.abs(a["wl"] - a["wl"][i]) <= a["wl"][i] / 60)
        bad[i] = len(np.unique(a["pass"][near])) == 1
    return bad


def rel_of(a, key):
    r, _ = relative(a["wl"], a["det"], key, np.ones_like(key), frac=1 / 60, min_n=4)
    return r


def boot_amp(a, k, rng, n=300):
    s = (a["det"] == k) & np.isfinite(a["rel"])
    passes = np.unique(a["pass"][s])
    out = []
    for _ in range(n):
        idx = np.concatenate([np.where(s & (a["pass"] == p))[0] for p in rng.choice(passes, len(passes))])
        if len(np.unique(np.round(a["mjd"][idx]))) < 4:
            continue
        try:
            amp, _, ph, *_ = fit(a["mjd"][idx], a["rel"][idx], P_VSX)
        except np.linalg.LinAlgError:
            continue
        out.append((amp, ph))
    return np.array(out)


def main():
    rng = np.random.default_rng(2)
    periods = np.exp(np.linspace(np.log(60), np.log(1500), 600))
    for name in ("r-dra", "control-2m1640", "control-2m1628"):
        a = arrays(json.loads((LC / f"{name}-diag.json").read_text()))
        bad = single_pass_mask(a)
        a["rel"] = np.where(bad, np.nan, a["rel"])
        raw = rel_of(a, a["wing"] + a["bkg"])
        bkg = rel_of(a, a["bkg"])
        print(f"== {name} (dropped {bad.sum()} single-pass-template points)")
        for k in HEAD:
            s = (a["det"] == k) & np.isfinite(a["rel"])
            amp, _, ph, sig, d2 = fit(a["mjd"][s], a["rel"][s], P_VSX)
            c, *_ = sine_fit(a["mjd"][s] - T0, a["rel"][s], np.full(s.sum(), sig), P_VSX)
            line = f"  D{k} n{s.sum()} mean {c[0]:.3f} semi-amp {amp:.3f} phase {ph:+.3f} dchi2 {d2:.0f}"
            for lab, y in (("ring not bkg-subtracted", raw), ("bkg annulus alone", bkg)):
                m = (a["det"] == k) & np.isfinite(y)
                ra, _, rp, _, rd = fit(a["mjd"][m], y[m], P_VSX)
                line += f" | {lab}: amp {ra:.3f} phase {rp:+.2f} dchi2 {rd:.0f}"
            print(line)
            if name == "r-dra":
                b = boot_amp(a, k, rng)
                lo, hi = np.percentile(b[:, 0], [16, 84])
                plo, phi = np.percentile(b[:, 1], [16, 84])
                print(f"     pass bootstrap: semi-amp 16-84% {lo:.3f}-{hi:.3f}, phase {plo:+.3f} to {phi:+.3f} (n={len(b)})")
        pg = periodogram(a, HEAD, periods)
        best = periods[np.argmax(pg)]
        bs = []
        passes = np.unique(a["pass"][np.isfinite(a["rel"])])
        for _ in range(200):
            idx = np.concatenate([np.where(a["pass"] == p)[0] for p in rng.choice(passes, len(passes))])
            b = {q: v[idx] for q, v in a.items()}
            b["mjd"] = b["mjd"] + rng.normal(0, 1e-3, len(idx))
            try:
                bs.append(periods[np.argmax(periodogram(b, HEAD, periods))])
            except np.linalg.LinAlgError:
                pass
        q = np.percentile(bs, [2.5, 16, 50, 84, 97.5])
        print(f"  period D1+D6: best {best:.0f} d dchi2 {pg.max():.0f} (at 246 d {np.interp(P_VSX, periods, pg):.0f});"
              f" bootstrap 2.5/16/50/84/97.5% = {np.round(q).astype(int).tolist()}")
    print("\n== RW Aur and bright control, per pass and collection, min_n=4")
    for name in ("rw-aur", "control-2m0507bright"):
        rows = json.loads((LC / f"{name}-wing.json").read_text())["rows"]
        mjd, det, wl = (np.array([r[k] for r in rows], float) for k in ("mjd", "det", "wl"))
        f = np.array([np.nan if r["wing"] is None else r["wing"] for r in rows], float)
        coll = np.array([r["coll"] for r in rows])
        rel, _ = relative(wl, det, f, np.ones_like(f), frac=1 / 60, min_n=4)
        print(name, "finite", int(np.isfinite(rel).sum()))
        for k in range(1, 7):
            s = (det == k) & np.isfinite(rel)
            parts = []
            for c in np.unique(coll[s]):
                for g in np.split(np.where(s & (coll == c))[0], np.where(np.diff(mjd[s & (coll == c)]) > 20)[0] + 1):
                    if len(g):
                        parts.append(f"{c[-3:]}@{mjd[g].mean():.0f}:{np.median(rel[g]):.3f}±{robust_std(rel[g]) / np.sqrt(len(g)):.3f}(n{len(g)})")
            print(f"  D{k}: " + "  ".join(parts))


if __name__ == "__main__":
    main()
