"""The search on synthetic stacks: a mover is found at its rate, a static source is not,
and pure noise gives no candidates in the real or the mirrored (null) search."""

from __future__ import annotations

import numpy as np

from pxs.movers.core import THRESHOLD, rate_of, run_core

from .conftest import SIGMA, Sky


def _run(sky: Sky, search, refs):
    return run_core(search, refs, sky.grid.center_ra, sky.grid.center_dec,
                    sky.grid.pixscale_arcsec)


def test_mover_recovered_with_its_rate(sky: Sky) -> None:
    d = 50.0
    vx, vy = sky.geom.reflex_px_day / d + np.array([0.3, -0.2])
    amp = 0.06  # about 2 sigma per frame
    search, refs = sky.layers(movers=[(40.0, 38.0, d, vx, vy, amp)])
    core = _run(sky, search, refs)
    top = core.above(THRESHOLD)
    assert top, "mover not detected"
    best = top[0]
    assert abs(best.x - 40) <= 1 and abs(best.y - 38) <= 1
    rvx, rvy, _ = rate_of(core, best)
    assert abs(rvx - vx) < 0.3 and abs(rvy - vy) < 0.3
    # Flux in mJy: amp x MJYSR_TO_MJY x 1/template(1 um) ~ 0.06 x 0.889.
    assert abs(best.flux_mjy - amp * 0.889) < 0.3 * amp * 0.889
    assert not core.above(THRESHOLD, null=True)


def test_static_source_not_a_candidate(sky: Sky) -> None:
    search, refs = sky.layers(statics=[(40.0, 40.0, 2.0)])  # 200 sigma per frame
    core = _run(sky, search, refs)
    near = [c for c in core.above(THRESHOLD) if np.hypot(c.x - 40, c.y - 40) < 6]
    assert not near


def test_pure_noise_has_no_candidates_and_null_matches(sky: Sky) -> None:
    search, refs = sky.layers()
    core = _run(sky, search, refs)
    assert not core.above(THRESHOLD)
    assert not core.above(THRESHOLD, null=True)
    real_max = max((d.snr for d in core.detections), default=0.0)
    null_max = max((d.snr for d in core.null_detections), default=0.0)
    # Gaussian noise over ~1e7 correlated trials peaks near 5-6 sigma in both searches.
    assert real_max < 6.5 and null_max < 6.5
    assert abs(real_max - null_max) < 1.5


def test_noise_normalisation_is_unit(sky: Sky) -> None:
    search, refs = sky.layers()
    core = _run(sky, search, refs)
    # Difference of a frame and a ~14-frame reference: variance is SIGMA^2 x (1 + 1/14),
    # which the pipeline variance already carries, so the empirical scale is ~1.
    assert np.all(np.abs(core.planes.noise_scale - 1.0) < 0.25)
    assert SIGMA > 0
