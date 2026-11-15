"""Probe: diagnostic figures for the bright-star artefacts (docs/validation/img/movers_*).

    PYTHONPATH=probes/movers uv run --with matplotlib python probes/movers/diag_bright_plots.py
Reads cache/movers/diag/<field>.npz (diag_bright.py) and the cached Gaia catalogue.
"""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from diag_bright_catalog import load  # noqa: E402
from diag_bright_profile import profile  # noqa: E402

OUT = "docs/validation/img"
FIELDS = ("Haumea", "B5", "B6", "BarnardsStar", "WISE0855")
LABEL = {"BarnardsStar": "Barnard's Star", "WISE0855": "WISE 0855"}


def _snr(z) -> np.ndarray:
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(z["phi"] > 0, z["psi"] / np.sqrt(np.where(z["phi"] > 0, z["phi"], 1)),
                        np.nan)


def fig_profile() -> None:
    fig, axes = plt.subplots(1, 3, figsize=(10, 3.2), sharey=True)
    for ax, (lo, hi) in zip(axes, ((7.5, 9.0), (9.0, 10.5), (10.5, 12.0))):
        for name in FIELDS:
            k, rows = profile(name)[(lo, hi)]
            if not k:
                continue
            r, m, _, f = np.array(rows).T
            ok = f < 0.9
            ax.plot(r[ok] + 0.5, m[ok], "-o", ms=3, label=f"{LABEL.get(name, name)} ({k})")
        ax.axhline(0, color="k", lw=0.5)
        ax.set_title(f"stars G {lo}-{hi}")
        ax.set_xlabel("radius (px, 6.15\")")
        ax.legend(fontsize=7)
    axes[0].set_ylabel("mean single-frame S/N\n(unmasked pixels)")
    fig.suptitle("Mean residual around Gaia stars, all frames of the pass (0 = clean)", fontsize=10)
    fig.tight_layout()
    fig.savefig(f"{OUT}/movers_star_residual_profile.png", dpi=90)


def _closest(tr: np.ndarray, phi: np.ndarray, cx: np.ndarray, cy: np.ndarray) -> float:
    use = phi > 0
    return float(np.hypot(tr[0][use][:, None] - cx, tr[1][use][:, None] - cy).min())


def fig_peaks() -> None:
    """CDF of each S/N >= 7 track's closest approach to a Gaia G < 13 star, against the
    same for random start pixels with a 1.5 px track (the slowest searched)."""
    fig, ax = plt.subplots(figsize=(6, 3.4))
    rng = np.random.default_rng(0)
    for i, name in enumerate(FIELDS):
        z = np.load(f"cache/movers/diag/{name}.npz")
        cat = load(name)["gaia"]
        b = cat["g"] < 13
        cx, cy = cat["x"][b], cat["y"][b]
        d = [_closest(t, q, cx, cy) for tag in ("real", "null")
             for t, q, s in zip(z[f"{tag}_track"], z[f"{tag}_phi"], z[f"{tag}_snr"]) if s >= 7]
        n = z["img"].shape[0]
        rx, ry = rng.uniform(0, n, (2, 4000))
        dr = np.hypot(rx[:, None] - cx, ry[:, None] - cy).min(axis=1) - 1.5
        ax.plot(np.sort(dr), np.linspace(0, 1, dr.size), color=f"C{i}", lw=0.8, ls=":")
        if d:
            ax.step(np.sort(d), np.arange(1, len(d) + 1) / len(d), where="post",
                    color=f"C{i}", label=f"{LABEL.get(name, name)}: {len(d)} peaks")
    ax.set_xlim(0, 40)
    ax.set_xlabel("closest approach of the track to a Gaia star G < 13 (px)")
    ax.set_ylabel("cumulative share")
    ax.set_title("S/N >= 7 peaks, real + null (solid) vs random positions (dotted)",
                 fontsize=9)
    ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(f"{OUT}/movers_peaks_vs_stars.png", dpi=90)


def ring_by_frame(name: str, g_max: float = 8.6) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Per frame: wavelength, detector, mean S/N 6-12 px from the field's G < g_max stars
    (unmasked pixels)."""
    z = np.load(f"cache/movers/diag/{name}.npz")
    snr = _snr(z)
    cat = load(name)["gaia"]
    n = snr.shape[1]
    yy, xx = np.mgrid[0:n, 0:n]
    ring = np.zeros((n, n), bool)
    for x, y, g in zip(cat["x"], cat["y"], cat["g"]):
        if g < g_max and 5 < x < n - 5 and 5 < y < n - 5:
            r = np.hypot(xx - x, yy - y)
            ring |= (r >= 6) & (r < 12)  # outside the ~5-9 px core mask (profile figure)
    vals = np.array([np.nanmean(snr[i][ring]) for i in range(snr.shape[0])])
    return z["wave"], z["det"], vals


def fig_wavelength() -> None:
    fig, ax = plt.subplots(figsize=(6, 3.2))
    for name, mk in (("BarnardsStar", "o"), ("WISE0855", "s")):
        w, det, v = ring_by_frame(name)
        for d in (1, 2, 3):
            k = det == d
            ax.scatter(w[k], v[k], marker=mk, s=16, c=f"C{d - 1}",
                       label=f"{LABEL[name]} D{d}")
    ax.axhline(0, color="k", lw=0.5)
    ax.set_xlabel("frame wavelength at field centre (um)")
    ax.set_ylabel("mean S/N, ring outside mask")
    ax.set_title("Ring 6-12 px from the G 8.2 stars: mostly positive, no wavelength trend",
                 fontsize=9)
    ax.legend(fontsize=7, ncol=2)
    fig.tight_layout()
    fig.savefig(f"{OUT}/movers_ring_vs_wavelength.png", dpi=90)


if __name__ == "__main__":
    fig_profile()
    fig_peaks()
    fig_wavelength()
    for name in ("BarnardsStar", "WISE0855"):
        w, det, v = ring_by_frame(name)
        print(name, "ring mean S/N per frame: median", round(float(np.nanmedian(v)), 2),
              "positive in", int(np.sum(v > 0)), "of", int(np.isfinite(v).sum()),
              "| corr with wavelength", round(float(np.corrcoef(w[np.isfinite(v)],
                                                               v[np.isfinite(v)])[0, 1]), 2),
              "| per det median", {int(d): round(float(np.nanmedian(v[det == d])), 2)
                                   for d in (1, 2, 3)})
