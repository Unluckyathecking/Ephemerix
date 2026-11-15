"""Build view manifests and images for one target or the whole gallery. Written with Claude Code.

    python -m pxs.build --target <slug> | --all  --out web/gallery [--fov 240 --size 240]

`build_view` works on any objects that implement the protocols in `pxs.sources`; the CLI
passes the real `pxs.wise` and `pxs.spherex` modules when they are installed. Angles in
degrees, field of view in arcsec, proper motion in mas/yr.
"""

from __future__ import annotations

import argparse
import importlib
import json
import logging
import math
import sys
from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from pxs import (
    astrometry,
    blend,
    catalog_reuse,
    catalogs,
    centroid,
    crossband,
    fieldcheck,
    fieldmovers,
    fitblend,
    render,
    trackmotion,
    typegate,
)
from pxs.concurrency import background
from pxs.grid import Grid, Stack
from pxs.manifest import assemble, frame_entry, target_block, validate
from pxs.sources import (
    Neighbours,
    SpherexSource,
    Target,
    WiseSource,
    collect_spherex,
    collect_wise,
    load_targets,
    ordered,
)
from pxs.spectra import PassAgreement, build_all, pass_checks
from pxs.typing import FEATURES
from pxs.vetting import vetting

log = logging.getLogger("pxs.build")

REPO = Path(__file__).resolve().parents[2]
TRACK_YEARS = (2010, 2027)
MARGIN_FRACTION = 0.1  # free border around the 2010-2027 path, as a share of the field

Overlays = Callable[[Grid], tuple[dict, list[str]]]
Progress = Callable[[str, float], None]  # (stage shown to the user, fraction done 0-1)


def _no_progress(stage: str, fraction: float) -> None:
    return None


class BuildError(RuntimeError):
    """A view cannot be built at all (no images from any source)."""


@dataclass(frozen=True)
class GridParams:
    """Requested field of view (arcsec) and image size (pixels)."""

    fov_arcsec: float = 240.0
    size_px: int = 240


def choose_grid(target: Target, params: GridParams) -> tuple[Grid, list[str]]:
    """Grid centred on the 2010-2027 path midpoint, widened (same pixel scale) to fit it."""
    fov = target.fov_arcsec or params.fov_arcsec
    scale = fov / params.size_px
    if not target.has_pm:
        return Grid(target.ra, target.dec, fov, params.size_px), []
    mid = sum(TRACK_YEARS) / 2.0
    ra0, dec0 = astrometry.propagate(target.ra, target.dec, target.epoch, target.pmra_masyr,
                                     target.pmdec_masyr, mid)
    ra0, dec0 = float(ra0), float(dec0)
    half_path = math.hypot(target.pmra_masyr, target.pmdec_masyr) * (mid - TRACK_YEARS[0]) / 1e3
    needed = 2.0 * half_path / (1.0 - 2.0 * MARGIN_FRACTION)
    if needed <= fov:
        return Grid(ra0, dec0, fov, params.size_px), []
    size = math.ceil(needed / scale)
    grid = Grid(ra0, dec0, size * scale, size)
    note = (f"The field of view was widened from {fov:g} to {grid.fov_arcsec:g} arcsec so the "
            f"whole {TRACK_YEARS[0]}-{TRACK_YEARS[1]} path fits.")
    return grid, [note]


def _ids(stacks: Sequence[tuple[str, Stack]]) -> list[str]:
    """Frame ids like "wise-w2-2010a" and "spx-b6-2025b"; letters count epochs per year."""
    seen: Counter = Counter()
    out = []
    for band, st in stacks:
        year = int(astrometry.decimal_year(st.mjd))
        stem = f"wise-{band.lower()}" if st.mission == "WISE" else band
        out.append(f"{stem}-{year}{chr(ord('a') + seen[(band, year)])}")
        seen[(band, year)] += 1
    return out


def _position_px(target: Target, grid: Grid, mjd: float) -> tuple[float, float]:
    """Predicted pixel position at `mjd`; the catalogue position if pm is unknown."""
    ra, dec = target.ra, target.dec
    if target.has_pm:
        ra, dec = astrometry.propagate(ra, dec, target.epoch, target.pmra_masyr,
                                       target.pmdec_masyr, float(astrometry.decimal_year(mjd)))
    x, y = grid.sky_to_px(ra, dec)
    return float(x), float(y)


def _measure(target: Target, grid: Grid, st: Stack, guess: tuple[float, float], gaia=(),
             catwise=()):
    pm = math.hypot(target.pmra_masyr, target.pmdec_masyr) if target.has_pm else 0.0
    year = float(astrometry.decimal_year(st.mjd))
    radius = centroid.search_radius_arcsec(centroid.psf_fwhm_arcsec(st), pm, year - target.epoch)
    avoid = blend.field_px(target, gaia, grid, year)
    near = fitblend.neighbours_px(target, catwise, st, grid)
    return centroid.detect(st, guess, grid.pixscale_arcsec, radius, avoid_px=avoid,
                           neighbours_px=near)


def _safe_measure(target: Target, grid: Grid, st: Stack, guess: tuple[float, float], gaia,
                  catwise=()):
    """`_measure`, but a frame whose measurement fails is "not detected" with a note instead
    of aborting the whole view."""
    if not _inside(guess, grid.size_px):
        return None, ()
    try:
        return _measure(target, grid, st, guess, gaia, catwise)
    except Exception:
        log.exception("centroid failed for a %s frame", st.mission)
        return None, ("the position could not be measured in this frame",)


def _inside(p: tuple[float, float], size: int) -> bool:
    return 0.0 <= p[0] <= size and 0.0 <= p[1] <= size


def _frames(target, grid, stacks, out_dir, gaia=(), catwise=()) -> tuple[list[dict], dict]:
    """Render every stack, measure the target, return (frame entries, centroids by id)."""
    sets: dict[str, list[Stack]] = defaultdict(list)
    for band, st in stacks:
        sets[band].append(st)
    stretches = {band: render.shared_stretch(s) for band, s in sets.items()}
    frames, found = [], {}
    for fid, (band, st) in zip(_ids(stacks), stacks):
        guess = _position_px(target, grid, st.mjd)
        c, notes = _safe_measure(target, grid, st, guess, gaia, catwise)
        image = f"frames/{fid}.png"
        render.write_png(st, stretches[band], out_dir / image)
        pred = guess if target.has_pm and _inside(guess, grid.size_px) else None
        gaps = fieldcheck.frame_gaps(st, guess, grid.pixscale_arcsec)
        gaps_image = f"frames/{fid}-gaps.png" if gaps["no_data_fraction"] > 0 else None
        if gaps_image:
            render.write_gaps_png(st, out_dir / gaps_image)
        frames.append({**frame_entry(fid, band, st, image, pred, c, notes), **gaps,
                       "gaps_image": gaps_image})
        found[fid] = (band, st, c)
    return frames, {"stretches": stretches, "found": found}


def _thumb(info: dict, out_dir: Path) -> None:
    """Thumbnail of the band where the target is best detected (W2 if detected at all)."""
    found = info["found"]
    det = [(v[2].snr, k) for k, v in found.items() if v[2] is not None]
    w2 = [d for d in det if found[d[1]][0] == "W2"]
    pick = max(w2 or det)[1] if det else max(found)
    band, st, _ = found[pick]
    render.write_thumb(st, info["stretches"][band], out_dir / "thumb.png")


def _frame_warnings(frames: Sequence[dict], target: Target) -> list[str]:
    out = []
    sat = sorted({f["band"] for f in frames if "saturated" in f["warnings"]})
    if sat:
        out.append(f"The target saturates some frames ({', '.join(sat)}); positions there "
                   "are less reliable.")
    if not any(f["centroid_px"] for f in frames):
        out.append("The target was not detected in any frame.")
    if not target.has_pm:
        out.append("No proper motion is known, so no predicted path is drawn.")
    if n := fitblend.n_blended(frames):
        out.append(f"{n} detection{'s are' if n > 1 else ' is'} left out of the motion fit "
                   "because a catalogued source of similar brightness lies within the area "
                   "the position is fitted over.")
    return out


def _gaia_neighbours(target: Target, ov_job: Future) -> Neighbours:
    """Gaia sources other than the target at each SPHEREx pass's mid-epoch, for the
    recentring; None when the Gaia query failed (so the recentring stays cautious)."""
    def at_pass(pas) -> list[tuple[float, float]] | None:
        ov, warn = ov_job.result()
        if catalogs.gaia_failed(warn):
            return None
        year = float(astrometry.decimal_year(0.5 * (pas.mjd_start + pas.mjd_end)))
        return blend.sky_neighbours(target, ov.get("gaia", []), year)
    return at_pass


def _with_pass_checks(match: dict | None, agreement: PassAgreement | None,
                      spectra: list[dict]) -> dict | None:
    """The (vetted) match with the per-pass calls added; unchanged when there are none."""
    if match is None or agreement is None:
        return match
    return {**match, **pass_checks(agreement, spectra)}


def build_view(target: Target, params: GridParams, spherex: SpherexSource | None,
               wise: WiseSource | None, out_dir: Path,
               overlays: Overlays | None = None, progress: Progress | None = None) -> dict:
    """Write frames/*.png, thumb.png and manifest.json to `out_dir` and return the manifest.

    Either data source may be None or fail; the view is built from what exists, with a
    warning. `overlays` defaults to the live catalogue queries. Raises BuildError when no
    source gives a single image. `progress`, if given, is called at each stage boundary.
    """
    out_dir = Path(out_dir)
    report = progress or _no_progress
    grid, warnings = choose_grid(target, params)
    report("Searching WISE and SPHEREx frames", 0.02)
    # The catalogues start with the archives (the SPHEREx spectra wait for the Gaia
    # neighbours), on a daemon thread so a view with no images does not wait for them.
    ov_job = (background(overlays or catalogs.overlays, grid)
              if spherex is not None or wise is not None else None)
    with ThreadPoolExecutor(max_workers=2) as ex:  # different archives, so fetch both at once
        w_job = ex.submit(collect_wise, wise, target, grid)
        s_job = ex.submit(collect_spherex, spherex, target, grid,
                          _gaia_neighbours(target, ov_job))
        w, s = w_job.result(), s_job.result()
    stacks = ordered(w.stacks + s.stacks)
    if not stacks:
        raise BuildError(f"no images for {target.name}: {' '.join(w.warnings + s.warnings)}")
    report("Querying Gaia and CatWISE", 0.8)
    ov, ov_warn = ov_job.result()
    gaia_down = catalogs.gaia_failed(ov_warn)
    ov_failed = gaia_down or catalogs.catwise_failed(ov_warn)
    gaia = ov.get("gaia", [])
    catwise = None if catalogs.catwise_failed(ov_warn) else ov.get("catwise", [])
    ov_warn = [*ov_warn, *blend.blend_warnings(target, gaia, blend.pass_years(s.passes)),
               *(() if catwise is not None else (blend.CHECKS_NOT_RUN,))]
    report("Rendering images and measuring the target", 0.84)
    frames, info = _frames(target, grid, stacks, out_dir, gaia, catwise or [])
    frames = crossband.check(frames, grid.pixscale_arcsec)
    frames = fitblend.flag(frames, target, catwise or [], grid.pixscale_arcsec)
    _thumb(info, out_dir)
    report("Fitting the spectrum", 0.9)
    typed = build_all(s.passes)
    spectra = typed.spectra
    years = blend.pass_years(s.passes)
    blocked = blend.blend_blocks_typing(target, gaia, years)
    refuse, caution = blend.contamination_gate(target, catwise, years)
    checked = typegate.neighbours_checked(target, catwise, gaia_down)
    match, type_notes = typegate.vet(typed.match, spectra, blocked, refuse,
                                     seen=any(f["centroid_px"] for f in frames), caution=caution,
                                     checked=checked)
    match = _with_pass_checks(match, typed.agreement, spectra)
    block = target_block(target)
    center = {"ra": grid.center_ra, "dec": grid.center_dec}
    track = astrometry.track(block, center, grid.fov_arcsec, grid.size_px, *TRACK_YEARS)
    manifest = assemble(
        target=target, grid=grid, frames=frames, track=track, spectra=spectra, match=match,
        features=FEATURES, overlays=ov, vetting=vetting(target, ov.get("catwise", [])),
        degraded=w.failed or s.failed or ov_failed,
        parallax_mas=blend.target_parallax(target, gaia),
        warnings=[*warnings, *w.warnings, *s.warnings, *ov_warn, *type_notes,
                  *_frame_warnings(frames, target)],
    )
    manifest = trackmotion.fill(manifest, target, grid, stacks, catwise)
    manifest = fieldcheck.apply(manifest, catwise, wise_failed=w.failed)
    manifest = {**manifest, "field_movers": fieldmovers.search(
        target, grid, stacks, _ids(stacks), None if gaia_down else gaia, catwise)}
    report("Writing the view", 0.97)
    validate(manifest, out_dir)
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1, allow_nan=False) + "\n")
    return manifest


def index_entry(target: Target, manifest: dict) -> dict:
    """One `gallery/index.json` entry: the published type beside the tool's best match."""
    match = manifest.get("match")
    return {"slug": target.slug, "name": target.name, "blurb": target.blurb,
            "manifest": f"{target.slug}/manifest.json", "thumb": f"{target.slug}/thumb.png",
            "ra": target.ra, "dec": target.dec, "known_type": target.known_type,
            "tool_type": match["best"]["type"] if match else None, "group": target.group}


def write_index(out: Path, entries: list[dict], merge: bool) -> None:
    """Write index.json. With `merge`, keep existing entries whose slug was not rebuilt."""
    path = out / "index.json"
    old = []
    if merge and path.exists():
        old = json.loads(path.read_text()).get("targets", [])
    built = {e["slug"] for e in entries}
    targets = [e for e in old if e.get("slug") not in built] + entries
    out.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(".index.json.tmp")  # written whole, then swapped in
    tmp.write_text(json.dumps({"schema": 1, "targets": targets}, indent=1) + "\n")
    tmp.replace(path)


def real_source(name: str):
    """Import a data module, or None if it is not there yet. Errors inside it still raise."""
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError as exc:
        if exc.name != name:
            raise
        log.warning("%s is not installed; views are built without it", name)
        return None


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m pxs.build", description=__doc__.splitlines()[0])
    pick = ap.add_mutually_exclusive_group(required=True)
    pick.add_argument("--target", help="slug of one target in the targets file")
    pick.add_argument("--all", action="store_true", help="build every target")
    ap.add_argument("--out", type=Path, default=REPO / "web" / "gallery")
    ap.add_argument("--targets", type=Path, default=REPO / "data" / "targets.json")
    ap.add_argument("--fov", type=float, default=240.0, help="field of view, arcsec")
    ap.add_argument("--size", type=int, default=240, help="image size, pixels")
    ap.add_argument("--catalogs-from", type=Path, help="directory of <slug>/manifest.json whose "
                    "Gaia and CatWISE lists are reused when the live query fails")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    targets = load_targets(args.targets)
    if args.target:
        targets = [t for t in targets if t.slug == args.target]
        if not targets:
            ap.error(f"no target with slug {args.target!r} in {args.targets}")
    spherex, wise = real_source("pxs.spherex"), real_source("pxs.wise")
    entries, failed = [], []
    for t in targets:
        try:
            ov = (catalog_reuse.with_stored(catalogs.overlays, args.catalogs_from, t.slug)
                  if args.catalogs_from else None)
            m = build_view(t, GridParams(args.fov, args.size), spherex, wise, args.out / t.slug,
                           overlays=ov)
        except Exception:
            log.exception("failed to build %s", t.slug)
            failed.append(t.slug)
            continue
        entries.append(index_entry(t, m))
        log.info("built %s: %d frames", t.slug, len(m["frames"]))
    write_index(args.out, entries, merge=not args.all)
    if failed:
        log.error("%d of %d targets failed and are not in the index: %s", len(failed),
                  len(targets), ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
