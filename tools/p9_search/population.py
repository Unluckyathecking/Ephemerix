"""The Brown & Batygin (2021) Planet Nine reference population and its sky density.

Source: Caltech data repository, record 8fjad-x7y61 (doi 10.22002/D1.20235), file
reference_population.csv: 100,000 synthetic Planet Nines drawn from the orbital-element
posterior of Brown & Batygin 2021 (AJ 162, 219; arXiv:2108.09868), with RA/Dec, heliocentric
distance and V at the epoch JD 2458270.0 (1 June 2018), and flags for whether ZTF, DES and
Pan-STARRS1 would have detected each one. The file is downloaded into cache/ and checked
against SHA256 below; it is not committed.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

URL = ("https://data.caltech.edu/api/records/8fjad-x7y61/files/"
       "reference_population.csv/content")
SHA256 = "050b68182ecbf7fd76f280d8cc43c0683d207499aba1488a68092b834420a422"
COLUMNS = ("index", "mass", "a", "e", "inc", "varpi", "Omega", "M", "ra", "dec", "R", "rad",
           "albedo", "V", "ZTF", "DES", "PS1")
HEADER_LINES = 5  # four "#" comment lines and the column-name line


@dataclass(frozen=True)
class Population:
    """Per-member arrays: ra, dec (deg, 2018.4), R (au), V, and `survives` = not detectable
    by any of ZTF, DES or PS1 according to the file's flags."""

    ra: np.ndarray
    dec: np.ndarray
    r_au: np.ndarray
    vmag: np.ndarray
    survives: np.ndarray

    def __len__(self) -> int:
        return len(self.ra)


def parse(text: str) -> Population:
    rows = np.loadtxt(text.splitlines()[HEADER_LINES:], delimiter=",", ndmin=2)
    if rows.shape[1] != len(COLUMNS):
        raise ValueError(f"expected {len(COLUMNS)} columns, got {rows.shape[1]}")
    c = {k: rows[:, i] for i, k in enumerate(COLUMNS)}
    survives = (c["ZTF"] == 0) & (c["DES"] == 0) & (c["PS1"] == 0)
    return Population(c["ra"], c["dec"], c["R"], c["V"], survives)


def load(path: Path) -> Population:
    """Download (once) into `path`, check the hash, parse."""
    if not path.exists():
        import requests

        r = requests.get(URL, timeout=120, headers={"User-Agent": "planet-x-spherex"})
        r.raise_for_status()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(r.content)
    data = path.read_bytes()
    got = hashlib.sha256(data).hexdigest()
    if got != SHA256:
        raise ValueError(f"{path}: sha256 {got} is not the expected {SHA256}")
    return parse(data.decode())


def unit_vectors(ra: np.ndarray, dec: np.ndarray) -> np.ndarray:
    r, d = np.radians(ra), np.radians(dec)
    return np.column_stack([np.cos(d) * np.cos(r), np.cos(d) * np.sin(r), np.sin(d)])


def galactic_b(ra: np.ndarray, dec: np.ndarray) -> np.ndarray:
    """Galactic latitude (deg) of ICRS positions."""
    import astropy.units as u
    from astropy.coordinates import SkyCoord

    return SkyCoord(np.asarray(ra) * u.deg, np.asarray(dec) * u.deg).galactic.b.deg


def chord(sep_deg: float) -> float:
    return 2.0 * math.sin(math.radians(sep_deg) / 2.0)


def cap_area_deg2(radius_deg: float) -> float:
    return 2 * math.pi * (1 - math.cos(math.radians(radius_deg))) * (180 / math.pi) ** 2


def local_density(pop_xyz: np.ndarray, at_xyz: np.ndarray, radius_deg: float,
                  weights: np.ndarray | None = None) -> np.ndarray:
    """Fraction of the population per deg^2 around each point of `at_xyz` (top-hat kernel
    of radius_deg). With `weights` (0/1 or fractional per member), only that part counts;
    the result is still a fraction of the whole population."""
    from scipy.spatial import cKDTree

    tree = cKDTree(pop_xyz)
    w = np.ones(len(pop_xyz)) if weights is None else np.asarray(weights, float)
    hits = tree.query_ball_point(at_xyz, chord(radius_deg))
    counts = np.array([w[h].sum() for h in hits])
    return counts / len(pop_xyz) / cap_area_deg2(radius_deg)


def members_near(pop_xyz: np.ndarray, at_xyz: np.ndarray, radius_deg: float) -> list[list[int]]:
    from scipy.spatial import cKDTree

    return cKDTree(pop_xyz).query_ball_point(at_xyz, chord(radius_deg))
