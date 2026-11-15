"""CLI argument handling (no network: search_field is replaced)."""

from __future__ import annotations

from pathlib import Path

import pytest

from pxs.movers import __main__ as cli
from pxs.search import __main__ as alias


def test_fov_is_arcsec_and_reaches_the_search(monkeypatch, tmp_path: Path) -> None:
    seen = {}

    class _Res:
        candidates: tuple = ()

        def write(self, path: Path) -> None:
            seen["path"] = path

    def fake(center, size, pass_index, out_dir, completeness_runs):
        seen.update(center=center, size=size, pass_index=pass_index)
        return _Res()

    monkeypatch.setattr(cli, "search_field", fake)
    assert alias.main(["--ra", "10", "--dec", "-5", "--fov", "900", "--out", str(tmp_path)]) == 0
    assert seen["size"] == 15.0 and seen["center"] == (10.0, -5.0)
    assert cli.main(["--ra", "10", "--dec", "-5", "--out", str(tmp_path)]) == 0
    assert seen["size"] == 20.0


@pytest.mark.parametrize("args", [["--ra", "400", "--dec", "0"], ["--ra", "1", "--dec", "0",
                                  "--fov", "60"], ["--ra", "1", "--dec", "0", "--fov", "900",
                                                   "--size", "15"]])
def test_bad_arguments_rejected(args: list[str], tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as e:
        cli.main([*args, "--out", str(tmp_path)])
    assert e.value.code == 2
