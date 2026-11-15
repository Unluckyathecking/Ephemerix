"""Load the real stacks pickled by dump_stacks.py, with the catalogue lists of the published
view (the dump's own catalogue queries can time out). Shared by the motion probes.
Written with Claude Code."""

from __future__ import annotations

import json
import pickle

import numpy as np

from pxs import centroid
from pxs.astrometry import decimal_year
from pxs.build import REPO


def load(slug: str) -> tuple[dict, list[dict], list[dict]]:
    """(dump payload: target, grid, stacks; Gaia sources; CatWISE sources)."""
    # our own pickle, written by dump_stacks.py
    d = pickle.loads((REPO / "cache" / "astro" / f"{slug}.pkl").read_bytes())
    ov = json.loads((REPO / "web" / "gallery" / slug / "manifest.json").read_text())["overlays"]
    return d, ov.get("gaia", []), ov.get("catwise", [])


def w2_visits(d: dict):
    """(stacks, prepared frames, decimal years) of the W2 visits."""
    use = [st for b, st in d["stacks"] if b == "W2" and st.mission == "WISE"]
    prep = [centroid._prepare(st, d["grid"].pixscale_arcsec) for st in use]
    return use, prep, np.array([float(decimal_year(st.mjd)) for st in use])


def robust_rms(v) -> float:
    v = np.asarray(v, float)
    return float(1.4826 * np.median(np.abs(v - np.median(v))))
