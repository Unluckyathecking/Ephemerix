"""Validation of the field mover search (src/pxs/fieldmovers) on the real WISE stacks.

    uv run python probes/astro/field_movers.py null|gallery|gaia|planted|fixture [slug ...]

null     the search with the visit dates shuffled (TRIALS shuffles per field), and static
         Gaia stars (proper motion under STATIC_MASYR) in the true order: how many "movers"
         each choice of the significance and shift limits lets through. The limits in
         fieldmovers/block.py were chosen from this table and from `planted`.
gallery  one line per field: was the target found without being told where it is, known
         movers, unexplained candidates, the null count, seconds taken.
gaia     Gaia stars whose motion the search should see: how many were found.
planted  movers of known per-visit S/N and speed planted in the real frames with the real
         PSF (`planted_movers.stamps`): the fraction recovered with the right motion.

Needs cache/astro/<slug>.pkl (dump_stacks.py; PXS_ASTRO_STACKS names another directory) and
the Gaia and CatWISE lists of the published manifests. Default: every field with a pickle.
Written with Claude Code.
"""

from __future__ import annotations

import json
import math
import os
import pickle
import sys
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
from planted_movers import stamps
from scipy import ndimage

from pxs import blend, centroid, fieldmovers
from pxs.astrometry import decimal_year
from pxs.build import REPO, _ids
from pxs.fieldmovers import block, detect, label
from pxs.fieldmovers.link import tracks

STACKS = Path(os.environ.get("PXS_ASTRO_STACKS", REPO / "cache" / "astro"))
TRIALS = 40
STATIC_MASYR = 20.0
SIGS = (4.0, 5.0, 6.0, 7.0, 8.0)
LIMITS = ((0.0, 0.0), (1.0, 0.0), (0.0, 0.7), (0.5, 0.7), (1.0, 0.5), (1.0, 0.6), (1.0, 0.7),
          (1.0, 0.8), (1.0, 0.9), (1.5, 0.7), (2.0, 0.7))  # (shift arcsec, coverage)
RNG = np.random.default_rng(11)
STAMP = 14  # planted_movers.STAMP
PLANT_SNR = (5.0, 6.0, 8.0, 12.0, 25.0)
PLANT_SPEED = (0.05, 0.1, 0.2, 0.4, 1.0, 3.0, 8.0)  # arcsec/yr
PER_RUN, RUNS = 5, 4


def load(slug: str) -> tuple[dict, list[dict], list[dict]]:
    """(dump payload, Gaia sources, CatWISE sources); the lists from the published view."""
    d = pickle.loads((STACKS / f"{slug}.pkl").read_bytes())  # our own, from dump_stacks.py
    ov = json.loads((REPO / "web" / "gallery" / slug / "manifest.json").read_text())["overlays"]
    return d, ov.get("gaia", []), ov.get("catwise", [])


def bands_of(d: dict, stacks=None) -> list[block.Band]:
    stacks = d["stacks"] if stacks is None else stacks
    out = [block.band_of(stacks, _ids(stacks), d["grid"], b) for b in block.BANDS]
    return [b for b in out if b is not None]


def with_limits(sig: float, shift: float, cover: float, fn):
    """`fn()` with the three limits of block.moved set (this process only)."""
    old = block.SIG_MIN, block.MIN_SHIFT_ARCSEC, block.COVER_MIN
    block.SIG_MIN, block.MIN_SHIFT_ARCSEC, block.COVER_MIN = sig, shift, cover
    try:
        return fn()
    finally:
        block.SIG_MIN, block.MIN_SHIFT_ARCSEC, block.COVER_MIN = old


def table(title: str, counts: dict, per: str) -> None:
    print(f"{title}\n   significance >=             " + "".join(f"{s:7.0f}" for s in SIGS))
    for sh, cv in LIMITS:
        print(f"   shift >= {sh:3.1f}\", cover >= {cv:3.1f}  "
              + "".join(f"{counts[(s, sh, cv)]:7d}" for s in SIGS))
    print(f"   ({per})")


def null(slugs: list[str]) -> None:
    shuf = {(s, sh, cv): 0 for s in SIGS for sh, cv in LIMITS}
    stat = dict(shuf)
    n_static = n_runs = 0
    for slug in slugs:
        d, gaia, _ = load(slug)
        real = bands_of(d)
        still = [g for g in gaia if g.get("pmra_masyr") is not None
                 and math.hypot(g["pmra_masyr"], g["pmdec_masyr"]) < STATIC_MASYR]
        ids = set()
        for b in real:  # tracks that are a static Gaia star
            for tr in b.tracks:
                hit = label._gaia(tr, still, d["grid"])
                if hit is not None and not label.is_target(tr, d["target"], d["grid"]):
                    ids.add(id(tr))
        n_static += len(ids)
        for key in stat:
            found, _ = with_limits(*key, lambda real=real: block.movers(real))
            stat[key] += sum(id(m.track) in ids for m in found)
        for k in range(TRIALS):
            fake = []
            for b in real:
                ep = detect.scrambled(b.ep, np.random.default_rng(1000 + k))
                fake.append(block.Band(ep, tuple(tracks(ep))))
            n_runs += 1
            for key in shuf:
                shuf[key] += len(with_limits(*key, lambda fake=fake: block.movers(fake))[0])
    table("movers found with the dates shuffled", shuf, f"in {n_runs} shuffled searches of "
          f"{len(slugs)} fields")
    table(f"static Gaia stars (under {STATIC_MASYR:g} mas/yr) called movers, true order", stat,
          f"of {n_static} tracks of such stars")


def gallery(slugs: list[str]) -> None:
    for slug in slugs:
        d, gaia, catwise = load(slug)
        t0 = time.perf_counter()
        b = fieldmovers.search(d["target"], d["grid"], d["stacks"], _ids(d["stacks"]), gaia,
                               catwise)
        dt = time.perf_counter() - t0
        if b["status"] != "searched":
            print(f"{slug}: {b['sentence']}")
            continue
        lab = [m["label"] for m in b["movers"]]
        tgt = next((m for m in b["movers"] if m["label"] == "target"), None)
        print(f"{slug}: target {'FOUND' if tgt else 'not found'}; known {b['n_known']} "
              f"(gaia {lab.count('gaia')}, catwise {lab.count('catwise')}); candidates "
              f"{b['n_candidates']}; contradicted {b['n_contradicted']}; band conflicts "
              f"{b['n_band_conflicts']}; null {b['null_count']} (max {b['null_max']}); tracked "
              f"{b['n_tracked']}; {dt:.2f} s")
        t = d["target"]
        if tgt:
            print(f"     target measured ({tgt['pmra_masyr']}, {tgt['pmdec_masyr']}) +- "
                  f"{tgt['err_masyr']} mas/yr, catalogue ({t.pmra_masyr}, {t.pmdec_masyr}); "
                  f"sig {tgt['significance']}, {tgt['n_epochs']} visits, bands {tgt['bands']}")
        else:
            print(f"     why: {why_missed(d, b)}")
        for m in b["movers"]:
            if m["label"] != "target":
                print(f"     {m['label']:9s} px {m['px']} ({m['pmra_masyr']}, {m['pmdec_masyr']}) "
                      f"+- {m['err_masyr']} sig {m['significance']} snr {m['snr']} n "
                      f"{m['n_epochs']} {m['bands']} gaia {m['gaia_id']} cw {m['catwise_id']}")


def why_missed(d: dict, b: dict) -> str:
    """Why the target is not among the movers: its own track, if it has one."""
    t, grid = d["target"], d["grid"]
    pm = math.hypot(t.pmra_masyr or 0.0, t.pmdec_masyr or 0.0)
    out = []
    for band in bands_of(d):
        tr = next((x for x in band.tracks if label.is_target(x, t, grid)), None)
        if tr is None:
            out.append(f"{band.ep.band}: no track (W2 {t.w2_mag}, W1 {t.w1_mag})")
            continue
        _, _, err = label.motion_masyr(tr, grid.pixscale_arcsec)
        out.append(f"{band.ep.band}: tracked in {len(tr.epochs)} visits, snr {tr.snr:.0f}, "
                   f"sig {tr.significance:.1f}, shift {block.shift_arcsec(tr, band.ep):.2f}\", "
                   f"err {err:.0f} mas/yr, wings {block._in_wings(tr, band)}")
    return f"catalogue motion {pm:.0f} mas/yr; " + "; ".join(out)


def gaia_stars(slugs: list[str]) -> None:
    """Gaia stars that should be seen: motion at least SIG_MIN times the error of the track
    at their place and a shift of MIN_SHIFT_ARCSEC over the baseline."""
    should = found = tracked = 0
    for slug in slugs:
        d, gaia, catwise = load(slug)
        grid, t = d["grid"], d["target"]
        real = bands_of(d)
        got = {m["gaia_id"] for m in block.assemble(real, t, grid, gaia, catwise)["movers"]
               if m["label"] == "gaia"}
        for g in gaia:
            if g.get("pmra_masyr") is None or blend.is_target(t, g):
                continue
            pm = math.hypot(g["pmra_masyr"], g["pmdec_masyr"])
            errs = []
            for b in real:
                for tr in b.tracks:
                    if label._gaia(tr, [g], grid) is not None or _at_star(tr, g, grid):
                        errs.append((label.motion_masyr(tr, grid.pixscale_arcsec)[2], b))
            if not errs:
                continue
            tracked += 1
            err, b = min(errs, key=lambda e: e[0])
            if pm >= block.SIG_MIN * err and pm / 1000 * np.ptp(b.ep.years) >= block.MIN_SHIFT_ARCSEC:
                should += 1
                found += g["id"] in got
                print(f"   {slug} Gaia {g['id']} G {g['g_mag']} pm {pm:.0f} mas/yr, track error "
                      f"{err:.0f}: {'found' if g['id'] in got else 'MISSED'}")
    print(f"Gaia stars with a track: {tracked}; moving enough to be seen: {should}; found: {found}")


def _at_star(tr, g: dict, grid) -> bool:
    xy = label._px([g], grid, tr.t0)[0]
    return math.hypot(xy[0] - tr.x0, xy[1] - tr.y0) * grid.pixscale_arcsec <= label.MATCH_ARCSEC


def _planted_stacks(d: dict, cases: list[tuple], psfs: dict) -> list:
    """The stacks with each case (band amplitudes, x0, y0, vx, vy px/yr about 2017) added."""
    out = []
    per_band = {b: iter(psfs[b]) for b in psfs}
    for band, st in d["stacks"]:
        if st.mission != "WISE" or band not in psfs:
            out.append((band, st))
            continue
        s = next(per_band[band])
        img = st.image.copy()
        tau = float(decimal_year(st.mjd)) - 2017.0
        for amps, x0, y0, vx, vy in cases:
            x, y = x0 + vx * tau, y0 + vy * tau
            i, j = int(y), int(x)
            n = img.shape[0]
            if s is None or not (STAMP <= i < n - STAMP and STAMP <= j < n - STAMP):
                continue
            img[i - STAMP: i + STAMP + 1, j - STAMP: j + STAMP + 1] += amps[band] * ndimage.shift(
                s, (y - (i + 0.5), x - (j + 0.5)), order=3)
        out.append((band, replace(st, image=img)))
    return out


def _zero_point(d: dict, catwise: list[dict]) -> float | None:
    """W2 magnitude of a source of per-visit S/N 1, from the field's CatWISE sources."""
    band = next((b for b in bands_of(d) if b.ep.band == "W2"), None)
    xy = label._px(catwise, d["grid"], None)
    zp = []
    for tr in band.tracks if band else ():
        near = np.hypot(xy[:, 0] - tr.x0, xy[:, 1] - tr.y0) * d["grid"].pixscale_arcsec
        i = int(np.argmin(near)) if len(near) else -1
        if i >= 0 and near[i] <= label.MATCH_ARCSEC and catwise[i].get("w2_mag") is not None \
                and tr.snr < detect.SATURATED_SNR:
            zp.append(catwise[i]["w2_mag"] + 2.5 * math.log10(tr.snr))
    return float(np.median(zp)) if zp else None


def _cases(snr: float, speed: float, unit: float, grid) -> list[tuple]:
    out = []
    for _ in range(PER_RUN):
        a = RNG.uniform(0, 2 * math.pi)
        v = speed / grid.pixscale_arcsec
        out.append(({"W2": snr * unit}, *RNG.uniform(50, grid.size_px - 50, 2),
                    v * math.cos(a), v * math.sin(a)))
    return out


def _psf_star(d: dict) -> tuple[float, float, float] | None:
    """(x, y, S/N) of the brightest unsaturated source that stands still in every W2 visit
    with nothing comparable within 18 px (`planted_movers.psf_star` takes the brightest of the
    first visit, which in two gallery fields is the moving target)."""
    band = next((b for b in bands_of(d) if b.ep.band == "W2"), None)
    n, ok = d["grid"].size_px, []
    for tr in band.tracks if band else ():
        alone = all(o is tr or o.snr < 0.15 * tr.snr
                    or math.hypot(o.x0 - tr.x0, o.y0 - tr.y0) > 18 for o in band.tracks)
        if (len(tr.epochs) == len(band.ep.years) and 20 <= tr.snr < detect.SATURATED_SNR
                and block.shift_arcsec(tr, band.ep) < 0.5 and alone
                and 30 < tr.x0 < n - 30 and 30 < tr.y0 < n - 30):
            ok.append((tr.x0, tr.y0, tr.snr))
    return max(ok, key=lambda p: p[2]) if ok else None


def _tally(found, base: int, cases: list[tuple], pix: float) -> tuple[int, int, int]:
    """(planted movers recovered with the right motion, found at the planted place with
    another motion, movers that are neither planted nor the field's own)."""
    right = sum(any(_is(m.track, *c[1:], pix) for m in found) for c in cases)
    near = sum(any(_near(m.track, c[1], c[2], pix) for c in cases) for m in found)
    return right, sum(any(_near(m.track, c[1], c[2], pix) for m in found)
                      for c in cases) - right, max(0, len(found) - near - base)


def planted(slugs: list[str]) -> None:
    """Recovered = a mover within 3" of the planted place at 2017 whose motion agrees with
    the planted one (`label.agrees`). Movers are planted in W2 only, at a per-visit S/N: a
    cold brown dwarf, invisible in W1, so the band check cannot help."""
    hits = {(s, v): [0, 0] for s in PLANT_SNR for v in PLANT_SPEED}
    wrong = false = runs = 0
    zps = []
    for slug in slugs:
        d, _, catwise = load(slug)
        pix = d["grid"].pixscale_arcsec
        use = [st for b, st in d["stacks"] if b == "W2" and st.mission == "WISE"]
        prep = [centroid._prepare(st, pix) for st in use]
        star = _psf_star(d)
        if star is None:
            print(f"{slug}: no isolated bright static star to take the PSF from; skipped",
                  flush=True)
            continue
        psfs = {"W2": stamps(prep, star)}
        unit = centroid._fit(prep[0], star)[4] / star[2]  # amplitude per unit S/N
        base = len(block.movers(bands_of(d))[0])
        zps.append(_zero_point(d, catwise))
        got = [0, 0]
        for (snr, speed), tally in hits.items():
            for _ in range(RUNS):
                cases = _cases(snr, speed, unit, d["grid"])
                found, _ = block.movers(bands_of(d, _planted_stacks(d, cases, psfs)))
                r, w, f = _tally(found, base, cases, pix)
                tally[1] += len(cases)
                tally[0] += r
                got = [got[0] + r, got[1] + len(cases)]
                wrong, false, runs = wrong + w, false + f, runs + 1
        print(f"{slug}: {got[0]} of {got[1]} recovered; PSF star S/N {star[2]:.0f}, "
              f"{sum(s is not None for s in psfs['W2'])} of {len(prep)} stamps; S/N 1 is W2 "
              f"{zps[-1]:.2f}", flush=True)
    zp = float(np.median([z for z in zps if z is not None]))
    print(f"fraction recovered (rows: per-visit S/N and the W2 magnitude it is at the median "
          f"zero point {zp:.2f}; columns: speed, arcsec/yr); "
          f"{next(iter(hits.values()))[1]} planted per cell, detection limit S/N {detect.SNR_MIN:g}")
    print("   S/N    W2  " + "".join(f"{v:7.2f}" for v in PLANT_SPEED))
    for s in PLANT_SNR:
        print(f"   {s:4.0f} {zp - 2.5 * math.log10(s):5.1f} " + "".join(
            f"{hits[(s, v)][0] / max(hits[(s, v)][1], 1):7.2f}" for v in PLANT_SPEED))
    print(f"in {runs} searches: {wrong} planted movers found with another motion; {false} "
          "movers that are neither planted nor the field's own")


def _near(tr, x0, y0, pix) -> bool:
    x, y = tr.at(2017.0)
    return math.hypot(x - x0, y - y0) * pix <= label.MATCH_ARCSEC


def _is(tr, x0, y0, vx, vy, pix) -> bool:
    x, y = tr.at(2017.0)
    k = pix * 1000.0
    return (math.hypot(x - x0, y - y0) * pix <= label.MATCH_ARCSEC
            and label.agrees((tr.vx * k, tr.vy * k), tr.err_v * k, (vx * k, vy * k)))


def fixture(slugs: list[str]) -> None:
    """Record the W2 sources (S/N 3.5 and up) of every visit of a field for the offline test
    tests/test_fieldmovers_recorded.py: a few kB instead of the 13 MB of stacks."""
    detect.SNR_MIN = 3.5
    for slug in slugs:
        d, _, _ = load(slug)
        ep = detect.epochs(d["stacks"], _ids(d["stacks"]), d["grid"], "W2")
        rows = [np.column_stack([xy, snr, err]).round(3).tolist()
                for xy, snr, err in zip(ep.xy, ep.snr, ep.err_px)]
        out = REPO / "tests" / "fixtures" / "astro" / f"{slug}-w2-sources.json"
        out.write_text(json.dumps({
            "band": ep.band, "ids": list(ep.ids), "years": ep.years.round(4).tolist(),
            "pixscale_arcsec": ep.pixscale_arcsec, "size_px": ep.size_px,
            "sources": rows}, separators=(",", ":")) + "\n")
        print(f"{out}: {sum(len(r) for r in rows)} sources in {len(rows)} visits")


def main(argv: list[str]) -> int:
    if "FM_SNR_MIN" in os.environ:  # try another per-visit detection limit (this process only)
        detect.SNR_MIN = float(os.environ["FM_SNR_MIN"])
    global PLANT_SNR, PLANT_SPEED
    if "FM_PLANT" in os.environ:  # "4,5,6;0.2,1,3": per-visit S/N values; speeds in arcsec/yr
        PLANT_SNR, PLANT_SPEED = (tuple(float(v) for v in part.split(","))
                                  for part in os.environ["FM_PLANT"].split(";"))
    slugs = argv[1:] or sorted(p.stem for p in STACKS.glob("*.pkl"))
    {"null": null, "gallery": gallery, "gaia": gaia_stars, "planted": planted,
     "fixture": fixture}[argv[0]](slugs)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
