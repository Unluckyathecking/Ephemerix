"""Checks of the all-frames motion fit (trackfit) on real W2 visits.

    uv run python probes/astro/planted_movers.py sky|pass|both|controls|shuffle <slug> [...]

The numbers quoted in src/pxs/trackfit.py come from one command (four fields; a field
without a bright isolated star to take the PSF from, such as WISEA 1101-5400, adds nothing):

    uv run python probes/astro/planted_movers.py both cwise-0411-4714 cwise-0623-0715 \
        wise-1541-2250 cwise-2112-0529

sky      movers of a faint target's brightness planted at random places, random direction
         and speed (0.3-1.0"/yr), recovered with the catalogued neighbours in the model.
pass     movers that pass PASS_PX from a real static source RATIO times brighter, closest at
         the mean epoch: the geometry of CWISE J0623+0715 and its neighbour.
controls real static CatWISE sources within 0.8 mag of the target, fitted the same way:
         their motion should be zero.
shuffle  the target itself with the epochs of the visits shuffled: the fit should be worse
         than with the true order.

Planted sources use the real PSF: in each frame a stamp of a bright isolated star of the same
frame, scaled down and shifted (cubic spline). sky and pass print the motion error along and
across the track and its ratio to the stated error; `trackfit.ERR_SCALE` is the rms of that
ratio with ERR_SCALE set to 1. Needs cache/astro/<slug>.pkl. Written with Claude Code.
"""

from __future__ import annotations

import math
import sys
from dataclasses import replace

import numpy as np
from scipy import ndimage
from stacks import load, robust_rms, w2_visits

from pxs import blend, centroid, trackfit, trackmotion
from pxs.astrometry import propagate

RNG = np.random.default_rng(7)
PASS_PX, RATIO, SPEED, STAMP = 9.0, 1.55, 0.98, 14


def psf_star(fr):
    """Brightest unsaturated star of the frame with no comparable source within 18 px."""
    ny, nx = fr.snr.shape
    pk = centroid._peaks(fr, (nx / 2, ny / 2), nx, 5.0)
    ok = [p for p in pk if np.isfinite(p[2]) and p[2] >= 20 and 30 < p[0] < nx - 30
          and 30 < p[1] < ny - 30
          and all(q is p or math.hypot(q[0] - p[0], q[1] - p[1]) > 18 or q[2] < 0.15 * p[2]
                  for q in pk)]
    return max(ok, key=lambda p: p[2]) if ok else None


def stamps(prep, star):
    """Per frame: the star as a unit-amplitude PSF centred on the stamp's middle pixel."""
    out = []
    for fr in prep:
        f = centroid._fit(fr, star)
        if f is None:
            out.append(None)
            continue
        i, j = int(f[1]), int(f[0])
        cut = fr.resid[i - STAMP: i + STAMP + 1, j - STAMP: j + STAMP + 1] / f[4]
        out.append(ndimage.shift(cut, (i + 0.5 - f[1], j + 0.5 - f[0]), order=3))
    return out


def frames_of(prep, years, resid=None) -> trackfit.Frames:
    return trackfit.Frames(np.array([f.resid for f in prep]) if resid is None else resid,
                           np.array([f.usable for f in prep]),
                           np.array([f.noise for f in prep]), years, np.zeros((len(prep), 2)))


def plant(prep, psfs, years, xy0, v, amp) -> trackfit.Frames:
    tau = years - years.mean()
    cube = []
    for fr, s, t in zip(prep, psfs, tau):
        img = fr.resid.copy()
        if s is not None:
            x, y = xy0[0] + v[0] * t, xy0[1] + v[1] * t
            i, j = int(y), int(x)
            img[i - STAMP: i + STAMP + 1, j - STAMP: j + STAMP + 1] += amp * ndimage.shift(
                s, (y - (i + 0.5), x - (j + 0.5)), order=3)
        cube.append(img)
    return frames_of(prep, years, np.array(cube))


def recover(frames, prep, use, grid, like, catwise, xy0, v, exact=False):
    """trackfit.fit as trackmotion.measure calls it; the seed is the truth plus a catalogue's
    error (0.3 px, 50 mas/yr) unless `exact`."""
    half = centroid._fit_half_width_px(prep[0].sigma_px)
    reach = half + prep[0].fwhm_px + 0.5 * math.hypot(*v) * float(np.ptp(frames.years))
    static = trackmotion._neighbours(like, catwise, grid, float(frames.years.mean()), xy0, reach)
    e = (0.0, 0.0, 0.0, 0.0) if exact else (*RNG.normal(0, 0.3, 2), *RNG.normal(0, 0.05, 2))
    return trackfit.fit(frames, prep[0].sigma_px, (xy0[0] + e[0], xy0[1] + e[1]),
                        (v[0] + e[2], v[1] + e[3]), static, half,
                        inflate=use[0].native_pixscale_arcsec / grid.pixscale_arcsec,
                        snr_min=centroid.SNR_MIN)


def planted(mode: str, d, catwise) -> list:
    """One row per planted mover: None, or (error along, across, pull x, pull y) in px/yr."""
    t, grid = d["target"], d["grid"]
    use, prep, years = w2_visits(d)
    star = psf_star(prep[0])
    if star is None:
        return []
    psfs, n, rows = stamps(prep, star), grid.size_px, []
    cases = []
    if mode == "sky":
        amp = 4.4 * float(np.median([f.noise for f in prep]))
        for _ in range(25):
            xy0, ang, sp = RNG.uniform(45, n - 45, 2), RNG.uniform(0, 2 * math.pi), RNG.uniform(0.3, 1)
            if min(math.hypot(xy0[0] - c[0], xy0[1] - c[1]) for c in ((n / 2, n / 2), star)) >= 30:
                cases.append((tuple(xy0), (sp * math.cos(ang), sp * math.sin(ang)), amp, t))
    else:
        for s in catwise:
            x, y = (float(q) for q in grid.sky_to_px(s["ra"], s["dec"]))
            ok = (s.get("w2_mag") is not None and 13.6 <= s["w2_mag"] <= 15.0
                  and not blend.is_catwise_piece(t, s) and 45 < x < n - 45 and 45 < y < n - 45
                  and math.hypot(x - n / 2, y - n / 2) >= 30)
            f = centroid._fit(prep[0], (x, y, 0.0)) if ok else None
            if f is None:
                continue
            like = replace(t, w2_mag=s["w2_mag"] + 2.5 * math.log10(RATIO))
            for a in (math.radians(k) for k in (0, 90, 180, 270)):
                cases.append(((x - PASS_PX * math.sin(a), y + PASS_PX * math.cos(a)),
                              (SPEED * math.cos(a), SPEED * math.sin(a)), f[4] / RATIO, like))
    for xy0, v, amp, like in cases:
        r = recover(plant(prep, psfs, years, xy0, v, amp), prep, use, grid, like, catwise, xy0, v)
        if r is None:
            rows.append(None)
            continue
        u, dv = np.array(v) / math.hypot(*v), np.array([r.vx - v[0], r.vy - v[1]])
        rows.append((float(dv @ u), float(dv @ np.array([-u[1], u[0]])),
                     dv[0] / r.err_v[0], dv[1] / r.err_v[1]))
    return rows


def controls(d, catwise) -> list[float]:
    """Motion / stated error, both axes, of static sources as bright as the target."""
    t, grid = d["target"], d["grid"]
    use, prep, years = w2_visits(d)
    n, pulls = grid.size_px, []
    for s in catwise:
        x, y = (float(q) for q in grid.sky_to_px(s["ra"], s["dec"]))
        if (s.get("w2_mag") is None or abs(s["w2_mag"] - t.w2_mag) > 0.8
                or blend.is_catwise_piece(t, s) or not (40 < x < n - 40 and 40 < y < n - 40)
                or math.hypot(x - n / 2, y - n / 2) < 30):
            continue
        r = trackfit.fit(frames_of(prep, years), prep[0].sigma_px, (x, y), (0.0, 0.0),
                         inflate=use[0].native_pixscale_arcsec / grid.pixscale_arcsec)
        if r is not None:
            pulls += [r.vx / r.err_v[0], r.vy / r.err_v[1]]
    return pulls


def shuffle(d, catwise, n_shuffles=40) -> None:
    t, grid = d["target"], d["grid"]
    use, prep, years = w2_visits(d)
    ra, dec = propagate(t.ra, t.dec, t.epoch, t.pmra_masyr, t.pmdec_masyr, float(years.mean()))
    xy0 = tuple(float(q) for q in grid.sky_to_px(ra, dec))
    v = (-t.pmra_masyr / 1000 / grid.pixscale_arcsec, -t.pmdec_masyr / 1000 / grid.pixscale_arcsec)
    true = recover(frames_of(prep, years), prep, use, grid, t, catwise, xy0, v, exact=True)
    if true is None:
        print(f"{t.slug}: no motion measured with the true order")
        return
    worse = 0
    for _ in range(n_shuffles):
        fr = frames_of(prep, years[RNG.permutation(years.size)])
        r = recover(fr, prep, use, grid, t, catwise, xy0, v, exact=True)
        worse += r is None or r.reduced_chi2 > true.reduced_chi2
    print(f"{t.slug}: reduced chi2 {true.reduced_chi2:.3f} with the true order; worse or "
          f"refused in {worse} of {n_shuffles} shuffles")


def main(argv: list[str]) -> int:
    mode, rows, pulls, split = argv[0], [], [], []
    for slug in argv[1:]:
        d, _, catwise = load(slug)
        if mode == "shuffle":
            shuffle(d, catwise)
        elif mode == "controls":
            pulls += controls(d, catwise)
        elif mode == "both":
            both = [planted(m, d, catwise) for m in ("sky", "pass")]
            print(f"{slug}: sky {sum(r is not None for r in both[0])} of {len(both[0])} measured, "
                  f"pass {sum(r is not None for r in both[1])} of {len(both[1])}")
            rows += both[0] + both[1]
            split.append(len(both[0]))
        else:
            rows += planted(mode, d, catwise)
    if mode == "controls":
        print(f"{len(pulls) // 2} static sources: rms of motion/error "
              f"{np.sqrt(np.mean(np.square(pulls))):.2f}, largest {np.max(np.abs(pulls)):.1f} "
              f"(errors include ERR_SCALE = {trackfit.ERR_SCALE})")
    elif rows:
        got = np.array([r for r in rows if r is not None])
        pull = got[:, 2:].ravel() * trackfit.ERR_SCALE  # against the unscaled error
        print(f"{mode}: planted {len(rows)}, measured {len(got)}; motion error along the track "
              f"median {1e3 * np.median(got[:, 0]):+.0f}, robust rms {1e3 * robust_rms(got[:, 0]):.0f}"
              f" mas/yr; across {1e3 * np.median(got[:, 1]):+.0f}, {1e3 * robust_rms(got[:, 1]):.0f}"
              f"; error / unscaled stated error: rms {np.sqrt(np.mean(pull**2)):.2f}, robust "
              f"{robust_rms(pull):.2f}; beyond 3 scaled sigma: "
              f"{(np.abs(pull) > 3 * trackfit.ERR_SCALE).mean():.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
