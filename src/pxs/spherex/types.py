"""Value types for the SPHEREx data path, with input validation at construction.

`Target` and `check_position` live in `pxs.target` and are re-exported here.
"""

from __future__ import annotations

from dataclasses import dataclass

from pxs.target import Target, check_position

__all__ = ["Frame", "Pass", "SpecPoint", "Target", "check_position"]


@dataclass(frozen=True)
class Frame:
    """One SPHEREx Level-2 exposure on one detector, as returned by SIA.

    mjd is the middle of the exposure; em_*_um is the detector's full wavelength range.
    """

    collection: str
    obs_id: str
    detector: int
    mjd: float
    s3_key: str
    em_min_um: float
    em_max_um: float


@dataclass(frozen=True)
class Pass:
    """Frames from one survey visit: no gap between consecutive frames exceeds 20 days."""

    frames: tuple[Frame, ...]

    @property
    def mjd_start(self) -> float:
        return self.frames[0].mjd

    @property
    def mjd_end(self) -> float:
        return self.frames[-1].mjd

    @property
    def detectors(self) -> tuple[int, ...]:
        return tuple(sorted({f.detector for f in self.frames}))


@dataclass(frozen=True)
class SpecPoint:
    """Forced photometry of one frame. Wavelengths in um, flux density F_nu in mJy.

    A flagged point has NaN flux and err and a `reason` ("saturated", "masked",
    "no psf", "no background").
    """

    wl_um: float
    bw_um: float
    flux_mjy: float
    err_mjy: float
    detector: int
    flagged: bool
    mjd: float
    reason: str = ""
    # Forced fluxes (mJy) at the 8 empty positions of photometry.OFFSETS in the same frame,
    # NaN where not measurable; used to measure the real noise of binned means.
    empty_mjy: tuple[float, ...] = ()
