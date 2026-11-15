"""The trial grid covers every distance in 30-1000 au, not only its nodes (an injection
campaign found holes at 115-900 au between nodes), and the search finds a variable star's
residual no more than a static star's."""

from __future__ import annotations

import numpy as np

from pxs.movers.completeness import injected_track, match
from pxs.movers.core import THRESHOLD, run_core
from pxs.movers.geometry import implied_distance_range, pass_geometry, trajectory_grid
from pxs.movers.inject import Synthetic, draw_sources

from .conftest import Sky

HAUMEA_PASS = np.linspace(60846.617, 60855.721, 56)


def test_every_prior_rate_has_a_trial_within_dv() -> None:
    geom = pass_geometry(218.64, 15.04, HAUMEA_PASS, 6.15)
    grid = trajectory_grid(geom)
    rng = np.random.default_rng(3)

    class _G:  # draw_sources only needs the grid's size
        size_px = 4000

    for d_range in ((140.0, 160.0), (280.0, 320.0), (550.0, 650.0)):
        for s in draw_sources(rng, 40, _G(), geom, (0.1, 0.1), d_range, margin_px=0,
                              min_sep_px=0):
            gap = np.min(np.hypot(grid.vx - s.vx, grid.vy - s.vy))
            assert gap <= grid.dv_px_day, (s.d_au, gap)
            lo, hi = implied_distance_range(grid, s.vx, s.vy, geom)
            assert lo <= s.d_au * 1.05 and hi >= s.d_au * 0.95


def test_mover_between_distance_nodes_recovered_with_its_track(sky: Sky) -> None:
    d = 300.0
    v = sky.geom.reflex_px_day / d + np.array([0.15, -0.1])
    src = Synthetic(42.0, 30.0, d, float(v[0]), float(v[1]), 0.08 * 0.889)
    span = np.ptp(sky.geom.dt) * np.hypot(*v)
    assert span >= 3.0, "test geometry must move the source beyond MIN_MOTION_PX"
    search, refs = sky.layers(movers=[(src.x, src.y, d, src.vx, src.vy, 0.08)])
    core = run_core(search, refs, sky.grid.center_ra, sky.grid.center_dec,
                    sky.grid.pixscale_arcsec, with_null=False)
    trials, extra = match([src], core)
    assert trials[0].recovered and trials[0].at_position
    assert not extra
    assert injected_track(src, core).shape[1] == len(core.cube)


def test_variable_star_is_not_a_candidate(sky: Sky) -> None:
    search, _ = sky.layers(statics=[(40.0, 40.0, 1.0)])
    _, refs = sky.layers(statics=[(40.0, 40.0, 0.3)])  # 70% fainter in the other passes
    core = run_core(search, refs, sky.grid.center_ra, sky.grid.center_dec,
                    sky.grid.pixscale_arcsec)
    near = [c for c in core.above(THRESHOLD) if np.hypot(c.x - 40, c.y - 40) < 6]
    assert not near
