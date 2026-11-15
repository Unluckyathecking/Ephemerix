"""Stamp-level cache: a warm read needs neither the network nor the byte cache."""

from __future__ import annotations

import numpy as np

from pxs.spherex import Frame, config
from pxs.spherex.net import BlockStore
from pxs.spherex.stamps import read_many, read_one

from .conftest import _no_network


def _frame(key: str) -> Frame:
    return Frame("spherex_dr1", "obs", 3, 61000.0, key, 0.7, 1.6)


def test_second_read_comes_from_the_stamp_cache(offline_store, recorded, tmp_path) -> None:
    rec = recorded["eps_d3"]
    f = _frame(rec["key"])
    first = read_one(f, rec["ra"], rec["dec"], rec["half"], True, offline_store)
    dead = BlockStore(fetch=_no_network, root=tmp_path / "empty")
    again = read_one(f, rec["ra"], rec["dec"], rec["half"], True, dead)
    for name in ("image", "flags", "variance", "zodi", "psf"):
        np.testing.assert_array_equal(getattr(first, name), getattr(again, name))
    assert (again.xpix, again.wave_um, again.detector, again.header) == (
        first.xpix, first.wave_um, first.detector, first.header)
    assert again.wave_at_pixel(10.0, 20.0) == first.wave_at_pixel(10.0, 20.0)
    assert not again.image.flags.writeable
    files = list((config.cache_dir() / "stamps").rglob("*.npz"))
    assert len(files) == 1 and not (config.cache_dir() / "blocks").exists()


def test_off_detector_is_cached_as_a_miss(offline_store, recorded, tmp_path) -> None:
    rec = recorded["eps_d3"]
    f, ra = _frame(rec["key"]), (rec["ra"] + 20) % 360
    assert read_one(f, ra, rec["dec"], rec["half"], True, offline_store) is None
    dead = BlockStore(fetch=_no_network, root=tmp_path / "empty")
    batch = read_many([(f, ra, rec["dec"])], rec["half"], store=dead)
    assert (batch.n_off_detector, batch.n_failed) == (1, 0)


def test_failures_are_not_cached(recorded, tmp_path) -> None:
    rec = recorded["eps_d3"]
    dead = BlockStore(fetch=_no_network, root=tmp_path / "empty")
    batch = read_many([(_frame(rec["key"]), rec["ra"], rec["dec"])], rec["half"], store=dead)
    assert batch.n_failed == 1
    assert not list((config.cache_dir() / "stamps").rglob("*.npz"))


def test_byte_cache_is_off_by_default(monkeypatch) -> None:
    monkeypatch.delenv("PXS_BYTE_CACHE", raising=False)
    assert not config.byte_cache_enabled()
    monkeypatch.setenv("PXS_BYTE_CACHE", "1")
    assert config.byte_cache_enabled()
