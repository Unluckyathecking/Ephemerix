"""Injection-recovery bookkeeping: matching injections to detections and completeness curves."""

from __future__ import annotations

import math

import numpy as np

from pxs.movers.completeness import Curve, Trial, curve, match
from pxs.movers.core import run_core
from pxs.movers.inject import Synthetic, draw_sources, position_px

from .conftest import Sky


def test_bright_recovered_faint_missed_no_double_count(sky: Sky) -> None:
    d = 60.0
    v = sky.geom.reflex_px_day / d
    bright = Synthetic(25.0, 25.0, d, float(v[0]), float(v[1]), 0.12 * 0.889)
    faint = Synthetic(55.0, 50.0, d, float(v[0]), float(v[1]), 0.005 * 0.889)
    movers = [(s.x, s.y, s.d_au, s.vx, s.vy, s.flux_mjy / 0.889) for s in (bright, faint)]
    search, refs = sky.layers(movers=movers)
    core = run_core(search, refs, sky.grid.center_ra, sky.grid.center_dec,
                    sky.grid.pixscale_arcsec, with_null=False)
    trials, extra = match([bright, faint, bright], core)
    assert trials[0].recovered and not trials[1].recovered
    assert not trials[2].recovered  # one detection is never matched to two injections
    assert not extra
    assert math.isnan(trials[1].snr)


def test_position_px_follows_geometry(sky: Sky) -> None:
    s = Synthetic(10.0, 20.0, 100.0, 1.0, -0.5, 0.1)
    i = 3
    x, y = position_px(s, sky.geom, float(sky.mjd[i]))
    dt = sky.mjd[i] - sky.geom.t0
    assert np.isclose(x, 10 + dt + sky.geom.curve_px[0, i] / 100)
    assert np.isclose(y, 20 - 0.5 * dt + sky.geom.curve_px[1, i] / 100)


def test_draw_sources_inside_and_separated(sky: Sky) -> None:
    rng = np.random.default_rng(3)
    srcs = draw_sources(rng, 5, sky.grid, sky.geom, (0.01, 0.1), (30, 1000), margin_px=8,
                        min_sep_px=10)
    assert srcs
    for a in srcs:
        assert 0.01 <= a.flux_mjy <= 0.1 and 30 <= a.d_au <= 1000
        for b in srcs:
            if a is not b:
                assert math.hypot(a.x - b.x, a.y - b.y) >= 10


def _trial(flux: float, rec: bool) -> Trial:
    return Trial(Synthetic(0, 0, 50, 1, 0, flux), 1.0, rec, 8.0 if rec else math.nan, flux)


def test_curve_and_flux_at() -> None:
    trials = [_trial(f, f > 0.1) for f in np.exp(np.linspace(np.log(0.01), np.log(1), 200))]
    c = curve(trials, n_bins=10)
    assert c.n.sum() == 200
    assert c.completeness[0] == 0 and c.completeness[-1] == 1
    assert 0.07 < c.flux_at(0.5) < 0.15
    assert math.isnan(Curve(np.array([1.0]), np.array([0.2]), np.array([5])).flux_at(0.5))
