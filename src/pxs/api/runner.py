"""The default build function: `pxs.build.build_view` with the real data modules.

Every warning in a built manifest is a sentence written in this codebase: the assembly
(`pxs.sources`, `pxs.catalogs`, `pxs.build`) logs exception details and never copies them
into the manifest, and job errors are fixed sentences chosen in `pxs.api.jobs`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pxs import build, catalogs
from pxs.api.params import ViewParams
from pxs.api.progress import Combined, Report, SpherexProgress, WiseProgress
from pxs.concurrency import background


def source_status() -> dict[str, bool]:
    """Which data modules are importable (they are developed on other branches)."""
    return {"wise": build.real_source("pxs.wise") is not None,
            "spherex": build.real_source("pxs.spherex") is not None}


def make_builder(spherex: Any | None, wise: Any | None, overlays: build.Overlays | None = None):
    """A BuildFn over the given data sources; sources are wrapped to report progress."""

    def run(params: ViewParams, out_dir: Path, report: Report) -> dict:
        both = Combined(report)  # WISE and SPHEREx run at once; one bar, both named
        target, grid_params = params.target(), build.GridParams(params.fov, int(params.fov))
        spx = (SpherexProgress(spherex, both.part("spherex"), (0.0, 1.0))
               if spherex is not None else None)
        grid = build.choose_grid(target, grid_params)[0]
        # The catalogue query starts now, once, for both the build and the SPHEREx head start.
        ov_job = background(overlays or catalogs.overlays, grid)
        if spx is not None:  # work on indexed SPHEREx frames while the archive search runs
            spx.warm(grid, target, build._gaia_neighbours(target, ov_job))  # as the build does
        return build.build_view(
            target, grid_params, spx,
            WiseProgress(wise, both.part("wise"), (0.0, 1.0)) if wise is not None else None,
            out_dir, overlays=lambda _grid: ov_job.result(), progress=report)

    return run


def default_builder():
    return make_builder(build.real_source("pxs.spherex"), build.real_source("pxs.wise"))
