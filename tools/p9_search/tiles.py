"""Choose 20' tiles in the densest part of the Planet Nine reference population, seeded.

Rule (recorded in tiles.json with the parameters and the population's SHA256):
1. Local sky density of the full reference population (2018 positions) around each member,
   top-hat kernel of KERNEL_DEG.
2. Eligible members: |b| >= B_MIN_DEG + the tile's half-diagonal, so the whole tile is
   outside |b| < 15.
3. Keep the densest DENSE_FRACTION of eligible members (density >= that quantile): the
   region holding that share of the |b| > 15 probability mass.
4. Walk those members in a seeded random order (so tiles fall in proportion to density
   inside the region) and accept one as a tile centre if it is at least MIN_SEP_DEG from
   every accepted centre, until N_RANKED tiles. The order is the rank; the search takes the
   first N that pass the SPHEREx coverage pre-flight.

2018 positions are used as they are: a Planet Nine at 400-800 au moves 0.3-0.5 deg on the
sky in seven years, far less than the kernel, so the choice of dense region does not change.

    uv run python -m p9_search.tiles      # (PYTHONPATH=tools) writes tools/p9_search/tiles.json
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from . import population as P

SEED = 20261115
N_RANKED = 48
KERNEL_DEG = 2.0
B_MIN_DEG = 15.0
TILE_ARCMIN = 20.0
DENSE_FRACTION = 0.5
MIN_SEP_DEG = 1.0
HALF_DIAG_DEG = TILE_ARCMIN / 60 / 2 * math.sqrt(2)
HERE = Path(__file__).resolve().parent
CSV = HERE.parent.parent / "cache" / "p9" / "reference_population.csv"


@dataclass(frozen=True)
class Tile:
    rank: int
    name: str
    ra: float
    dec: float
    b_deg: float
    density_per_deg2: float  # fraction of the reference population per deg^2 (kernel)


def tile_area_deg2(size_arcmin: float = TILE_ARCMIN) -> float:
    return (size_arcmin / 60.0) ** 2


def dense_mask(density: np.ndarray, eligible: np.ndarray, fraction: float) -> np.ndarray:
    """Eligible members whose density is in the top `fraction` of eligible members."""
    if not eligible.any():
        return np.zeros_like(eligible)
    cut = np.quantile(density[eligible], 1.0 - fraction)
    return eligible & (density >= cut)


def pick_separated(xyz: np.ndarray, order: np.ndarray, n: int, min_sep_deg: float) -> list[int]:
    """Indices (into xyz) taken in `order`, each >= min_sep_deg from all taken before."""
    cos_min = math.cos(math.radians(min_sep_deg))
    taken: list[int] = []
    for i in order:
        if all(float(xyz[i] @ xyz[j]) <= cos_min for j in taken):
            taken.append(int(i))
            if len(taken) == n:
                break
    return taken


def select(ra: np.ndarray, dec: np.ndarray, b_deg: np.ndarray, seed: int = SEED,
           n: int = N_RANKED, kernel_deg: float = KERNEL_DEG, b_min: float = B_MIN_DEG,
           fraction: float = DENSE_FRACTION, min_sep_deg: float = MIN_SEP_DEG) -> list[Tile]:
    """The ranked tiles (rule in the module docstring)."""
    xyz = P.unit_vectors(ra, dec)
    density = P.local_density(xyz, xyz, kernel_deg)
    eligible = np.abs(b_deg) >= b_min + HALF_DIAG_DEG
    dense = np.flatnonzero(dense_mask(density, eligible, fraction))
    order = np.random.default_rng(seed).permutation(dense)
    picked = pick_separated(xyz, order, n, min_sep_deg)
    return [Tile(rank=k + 1, name=f"P9T{k + 1:02d}", ra=round(float(ra[i]), 5),
                 dec=round(float(dec[i]), 5), b_deg=round(float(b_deg[i]), 2),
                 density_per_deg2=float(density[i])) for k, i in enumerate(picked)]


def main() -> None:
    pop = P.load(CSV)
    b = P.galactic_b(pop.ra, pop.dec)
    tiles = select(pop.ra, pop.dec, b)
    xyz = P.unit_vectors(pop.ra, pop.dec)
    density = P.local_density(xyz, xyz, KERNEL_DEG)
    eligible = np.abs(b) >= B_MIN_DEG + HALF_DIAG_DEG
    out = {
        "source": {"url": P.URL, "sha256": P.SHA256, "n_members": len(pop),
                   "epoch": "JD 2458270.0 (2018-06-01)",
                   "paper": "Brown & Batygin 2021, AJ 162, 219 (arXiv:2108.09868)"},
        "rule": {"seed": SEED, "n_ranked": N_RANKED, "kernel_deg": KERNEL_DEG,
                 "b_min_deg": B_MIN_DEG, "tile_arcmin": TILE_ARCMIN,
                 "dense_fraction": DENSE_FRACTION, "min_sep_deg": MIN_SEP_DEG,
                 "density_cut_per_deg2": float(np.quantile(density[eligible],
                                                           1 - DENSE_FRACTION)),
                 "eligible_fraction_of_population": float(eligible.mean()),
                 "text": __doc__.split("\n\n")[1]},
        "tiles": [asdict(t) for t in tiles],
    }
    (HERE / "tiles.json").write_text(json.dumps(out, indent=1) + "\n")
    print(f"{len(tiles)} tiles; density {tiles[0].density_per_deg2:.2e} ... "
          f"cut {out['rule']['density_cut_per_deg2']:.2e} per deg^2")


if __name__ == "__main__":
    main()
