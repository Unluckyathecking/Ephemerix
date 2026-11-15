"""PNG stamps for a candidate: the shift-and-stack coadd and one cutout per frame along the
track (an animation as a list of images). Difference images, symmetric stretch at +-5 sigma
of the field's robust scatter; masked pixels are mid-grey."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from .candidates import Detection, track_xy
from .core import CoreResult
from .matched import robust_sigma

HALF = 10  # 21x21 px stamps (2.15')
SCALE = 6  # each pixel drawn 6x6 for display
NSIG = 5.0


def cutout(img: np.ndarray, x: int, y: int, half: int = HALF) -> np.ndarray:
    """(2h+1)^2 cutout centred on pixel (x, y), NaN outside the image."""
    n = 2 * half + 1
    out = np.full((n, n), np.nan, np.float32)
    h, w = img.shape
    ya, yb, xa, xb = max(y - half, 0), min(y + half + 1, h), max(x - half, 0), min(x + half + 1, w)
    if ya < yb and xa < xb:
        out[ya - y + half:yb - y + half, xa - x + half:xb - x + half] = img[ya:yb, xa:xb]
    return out


def to_png(a: np.ndarray, sigma: float, path: Path) -> None:
    v = np.clip(np.nan_to_num(a / (NSIG * sigma), nan=0.0), -1, 1)
    g = ((v + 1) * 127.5).astype(np.uint8)
    Image.fromarray(np.kron(g, np.ones((SCALE, SCALE), np.uint8)), "L").save(path)


def coadd(core: CoreResult, det: Detection) -> np.ndarray:
    """Inverse-variance mean of the difference cutouts along the track."""
    xy = track_xy(core.trials, det)
    num = np.zeros((2 * HALF + 1,) * 2)
    den = np.zeros_like(num)
    for i in range(len(core.cube)):
        x, y = int(xy[0, i]), int(xy[1, i])
        d, v = cutout(core.cube.diff[i], x, y), cutout(core.cube.var[i], x, y)
        ok = np.isfinite(d) & np.isfinite(v) & (v > 0)
        w = np.where(ok, core.cube.template[i] / np.where(ok, v, 1), 0)
        num += w * np.where(ok, d, 0) / max(core.cube.template[i], 1e-6)
        den += w
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(den > 0, num / den, np.nan)


def write_stamps(core: CoreResult, det: Detection, out_dir: Path, tag: str) -> dict:
    """Write the coadd and per-frame PNGs; returns relative paths and frame MJDs."""
    out_dir.mkdir(parents=True, exist_ok=True)
    sig = np.nanmedian([robust_sigma(core.cube.diff[i]) for i in range(len(core.cube))])
    c = coadd(core, det)
    to_png(c, max(robust_sigma(c), 1e-9), out_dir / f"{tag}_coadd.png")
    xy = track_xy(core.trials, det)
    frames = []
    for k, i in enumerate(np.argsort(core.cube.mjd)):
        cut = cutout(core.cube.diff[i], int(xy[0, i]), int(xy[1, i]))
        if not np.isfinite(cut[HALF - 1:HALF + 2, HALF - 1:HALF + 2]).any():
            continue
        name = f"{tag}_f{k:02d}.png"
        to_png(cut, sig, out_dir / name)
        frames.append({"png": f"{out_dir.name}/{name}", "mjd": float(core.cube.mjd[i]),
                       "wave_um": float(core.cube.wave_um[i]),
                       "detector": int(core.cube.detector[i])})
    return {"coadd_png": f"{out_dir.name}/{tag}_coadd.png", "frames": frames}
