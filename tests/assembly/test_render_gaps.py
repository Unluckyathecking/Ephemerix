"""Display gaps: pixels flagged in most exposures are not drawn through the stretch.

A frame inside a bright star's glare (Betelgeuse in W2) has a large `saturated_mask` that the
saturated-core test does not call a core. Its masked pixels hold a fill or the values of the one
or two exposures that were not flagged, which used to show as black squares and crosses."""

import numpy as np
from build_fakes import GRID

from pxs import render
from pxs.grid import Stack

N = GRID.size_px


def _stack(image: np.ndarray, mask: np.ndarray | None) -> Stack:
    return Stack(image=image.astype(np.float32), mission="WISE", band="W2",
                 wavelength_um=(4.0, 5.2), mjd=58000.0, date_span_days=1.0, n_exposures=12,
                 native_pixscale_arcsec=2.75, unit="DN", saturated_mask=mask)


def glare_stack(seed: int = 0) -> Stack:
    """A broad halo with a large flagged plateau in the middle; inside it, a scatter of single
    pixels and crosses at a tenth of the plateau (the unflagged exposures)."""
    rng = np.random.default_rng(seed)
    i, j = np.mgrid[:N, :N]
    r = np.hypot(i - N / 2, j - N / 2)
    img = 100.0 + 5e4 / (1.0 + (r / 10.0) ** 2) + rng.standard_normal((N, N))
    mask = r < N / 4
    img[mask] = 3e3
    specks = mask & (rng.random((N, N)) < 0.03)
    img[specks] = 300.0
    return _stack(img, mask)


def test_flagged_specks_are_not_drawn_dark():
    st = glare_stack()
    u = render.to_uint8(st, render.shared_stretch([st]))
    inside = st.saturated_mask
    assert u[inside].min() == u[inside].max()  # one even tone, no squares or crosses
    edge = np.zeros_like(inside)
    edge[N // 2, N // 4 - 3] = True  # halo just outside the plateau
    assert abs(int(u[inside][0]) - int(u[edge][0])) < 60  # the tone of its surroundings


def test_no_data_mask_and_fraction():
    st = glare_stack()
    gaps = render.no_data_mask(st)
    assert gaps[st.saturated_mask].all()
    assert render.no_data_fraction(st) == float(gaps.mean())
    img = np.full((N, N), 10.0)
    img[:, :5] = np.nan
    clean = _stack(img, None)
    assert np.array_equal(render.no_data_mask(clean), ~np.isfinite(img))
    assert abs(render.no_data_fraction(clean) - 5 / N) < 1e-9
    assert render.no_data_fraction(_stack(np.ones((N, N)), None)) == 0.0


def test_unflagged_frame_renders_as_before():
    rng = np.random.default_rng(3)
    img = 10.0 + rng.standard_normal((N, N))
    img[40:43, 40:43] += 500.0
    st = _stack(img, np.zeros((N, N), bool))
    plain = _stack(img, None)
    s = render.shared_stretch([st])
    assert np.array_equal(render.to_uint8(st, s), render.to_uint8(plain, s))


def test_gaps_png_marks_the_gaps(tmp_path):
    st = glare_stack()
    p = render.write_gaps_png(st, tmp_path / "g.png")
    from PIL import Image
    a = np.asarray(Image.open(p))
    assert a.shape == (N, N) and set(np.unique(a)) == {0, 255}
    assert np.array_equal(a == 255, render.no_data_mask(st))
