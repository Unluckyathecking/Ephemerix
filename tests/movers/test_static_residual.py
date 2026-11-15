"""A bright star's subtraction residual that is the same in every frame of the pass, as in
the Barnard's Star and WISE 0855 control fields, stacks into
S/N >= 7 peaks along the slowest tracks, and the mirrored null finds the same peak at the
same place: the null search measures this artefact rather than hiding it."""

from __future__ import annotations

import numpy as np

from pxs.movers.core import THRESHOLD, run_core

from .conftest import Sky, paint

STAR = (40.0, 40.0, 2.0)  # 200 sigma per frame, in the search pass and the references
RESIDUAL = (45.0, 40.0, 0.1)  # its wing residual, 5 px out: in every search frame only


def _with_residual(sky: Sky):
    search, refs = sky.layers(statics=[STAR])
    for i, layer in enumerate(search):
        img = paint(layer.image, *RESIDUAL)
        search[i] = type(layer)(layer.frame, layer.mjd, img.astype(np.float32), layer.variance,
                                layer.wave, layer.band, layer.psf)
    return search, refs


def _near_residual(dets) -> list:
    return [d for d in dets if d.snr >= THRESHOLD and np.hypot(d.x - 45, d.y - 40) < 6]


def _run(sky: Sky, search, refs):
    return run_core(search, refs, sky.grid.center_ra, sky.grid.center_dec,
                    sky.grid.pixscale_arcsec)


def test_static_residual_makes_matching_real_and_null_peaks(sky: Sky) -> None:
    core = _run(sky, *_with_residual(sky))
    real, null = _near_residual(core.detections), _near_residual(core.null_detections)
    assert real and null
    assert abs(real[0].snr - null[0].snr) < 0.25 * real[0].snr


def test_bright_star_alone_leaves_no_peak(sky: Sky) -> None:
    core = _run(sky, *sky.layers(statics=[STAR]))
    assert not _near_residual(core.detections)
    assert not _near_residual(core.null_detections)
