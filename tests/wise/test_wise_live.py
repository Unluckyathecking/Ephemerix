"""Live checks against IRSA and s3://nasa-irsa-wise. Run with PXS_NETWORK=1."""

import numpy as np
import pytest

from pxs.grid import Grid
from pxs.wise import find_visits, path_from_motion, stack_visit

# WISE 0855-0714, CatWISE2020 motion-fit position (tests/fixtures/astrometry_targets.json)
RA, DEC, EPOCH, PMRA, PMDEC = 133.7835555, -7.244052, 2015.405, -8123.7, 673.2


@pytest.mark.network
def test_wise0855_has_about_23_visits_and_a_w2_stack() -> None:
    path = path_from_motion(RA, DEC, EPOCH, PMRA, PMDEC)
    visits = find_visits(RA, DEC, path=path)
    assert 20 <= len(visits) <= 26
    grid = Grid(center_ra=RA, center_dec=DEC, fov_arcsec=240.0, size_px=120)
    stack = stack_visit(visits[-1], "W2", grid, max_frames=4)
    assert stack is not None and stack.n_exposures >= 3
    assert np.isfinite(stack.image).mean() > 0.9
